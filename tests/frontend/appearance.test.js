'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = path.resolve(__dirname, '../../exam_room/ui/appearance.js');
let appearance;
try { appearance = require(source); } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }
function api() { assert.ok(appearance, 'appearance preferences module must exist'); return appearance; }
function storage(initial) {
  const values = new Map(initial ? [['exam-room-ui-preferences', initial]] : []);
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), values };
}
function environment(saved, dark = false) {
  const listeners = new Map();
  const styles = new Map();
  const attributes = new Map();
  const media = { matches: dark, count: 0, addEventListener(type, listener) { this.count++; listeners.set(type, listener); }, removeEventListener(type) { listeners.delete(type); }, change(value) { this.matches = value; listeners.get('change')?.({ matches: value }); } };
  function control() {
    const events = new Map();
    return { value: '', textContent: '', disabled: false, addEventListener(type, fn) { events.set(type, [...(events.get(type) || []), fn]); }, fire(type) { for (const fn of events.get(type) || []) fn({ target: this }); }, events };
  }
  const ids = Object.fromEntries(['themeSelect', 'fontMinus', 'fontPlus', 'fontReset', 'fontPercent', 'densitySelect', 'resetAppearance'].map(id => [id, control()]));
  const env = { localStorage: storage(saved), matchMedia: () => media, document: { documentElement: { dataset: {}, style: { setProperty: (key, value) => styles.set(key, value) }, setAttribute: (key, value) => attributes.set(key, value) }, getElementById: id => ids[id] } };
  return { env, media, ids, styles, attributes };
}

test('normalization keeps only known preferences, validates values and rounds font increments', () => {
  assert.deepEqual(api().normalizePreferences({ theme: 'dark', fontScale: 1.234, density: 'compact', secret: 'ignored' }), { theme: 'dark', fontScale: 1.25, density: 'compact' });
  assert.deepEqual(api().normalizePreferences({ theme: 'invalid', fontScale: NaN, density: 'invalid' }), { theme: 'system', fontScale: 1, density: 'standard' });
  assert.equal(api().normalizePreferences({ fontScale: 5 }).fontScale, 1.5);
  assert.equal(api().normalizePreferences({ fontScale: .1 }).fontScale, .9);
  assert.equal(api().normalizePreferences({ fontScale: '1.25' }).fontScale, 1);
  assert.deepEqual(api().normalizePreferences(null), { theme: 'system', fontScale: 1, density: 'standard' });
});

test('malformed, missing and unavailable storage all fall back without throwing', () => {
  for (const saved of ['{broken', 'null', '[]', '"wrong"', undefined]) assert.deepEqual(api().readPreferences(storage(saved)), { theme: 'system', fontScale: 1, density: 'standard' });
  assert.deepEqual(api().readPreferences({ getItem() { throw Error('blocked'); } }), { theme: 'system', fontScale: 1, density: 'standard' });
  assert.doesNotThrow(() => api().createAppearance({ localStorage: { getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); } } }).changeFont(.05));
});

test('boot applies saved theme and root rem size before controls are mounted', () => {
  const { env, styles, attributes } = environment(JSON.stringify({ theme: 'dark', fontScale: 1.25, density: 'compact' }));
  api().createAppearance(env);
  assert.equal(attributes.get('data-theme'), 'dark');
  assert.equal(attributes.get('data-density'), 'compact');
  assert.equal(styles.get('--font-scale'), '1.25');
  assert.equal(env.document.documentElement.style.fontSize, '18.75px');
});

test('system changes update the live theme only while system is selected', () => {
  const { env, media, attributes } = environment(undefined, true);
  const ui = api().createAppearance(env);
  assert.equal(attributes.get('data-theme'), 'dark');
  media.change(false);
  assert.equal(attributes.get('data-theme'), 'light');
  ui.setTheme('dark');
  media.change(false);
  assert.equal(attributes.get('data-theme'), 'dark');
  ui.setTheme('system');
  assert.equal(attributes.get('data-theme'), 'light');
  assert.equal(media.count, 1);
});

test('font controls clamp 90 to 150 percent and persist without an exam or solver API', () => {
  const { env, ids } = environment();
  env.fetch = () => { throw Error('appearance must not call backend'); };
  env.save = () => { throw Error('appearance must not save a plan'); };
  const ui = api().createAppearance(env);
  ui.initControls();
  ui.initControls();
  ids.fontPlus.fire('click');
  assert.equal(ui.getPreferences().fontScale, 1.05);
  assert.equal(ids.fontPercent.textContent, '105%');
  for (let i = 0; i < 30; i++) ids.fontPlus.fire('click');
  assert.equal(ui.getPreferences().fontScale, 1.5);
  assert.equal(ids.fontPlus.disabled, true);
  for (let i = 0; i < 30; i++) ids.fontMinus.fire('click');
  assert.equal(ui.getPreferences().fontScale, .9);
  assert.equal(ids.fontMinus.disabled, true);
  ids.fontReset.fire('click');
  assert.equal(ui.getPreferences().fontScale, 1);
  assert.equal(JSON.parse(env.localStorage.getItem('exam-room-ui-preferences')).fontScale, 1);
  assert.equal(ids.fontPlus.events.get('click').length, 1);
});

test('saved font wins over legacy plan scale; missing local scale migrates once', () => {
  const existing = api().createAppearance(environment(JSON.stringify({ fontScale: 1.1 })).env);
  assert.equal(existing.migrateLegacy(1.4), false);
  assert.equal(existing.getPreferences().fontScale, 1.1);
  const { env } = environment(JSON.stringify({ theme: 'dark' }));
  const migrated = api().createAppearance(env);
  assert.equal(migrated.migrateLegacy(undefined), false);
  assert.equal(migrated.migrateLegacy(1.25), true);
  assert.equal(migrated.migrateLegacy(1.4), false);
  assert.equal(migrated.getPreferences().fontScale, 1.25);
  assert.equal(migrated.getPreferences().theme, 'dark');
  const reopened = api().createAppearance(env);
  assert.equal(reopened.migrateLegacy(1.4), false);
});

test('theme and density controls persist and reset returns to defaults following the system', () => {
  const { env, ids, attributes } = environment(undefined, true);
  const ui = api().createAppearance(env);
  ui.initControls();
  ids.themeSelect.value = 'light'; ids.themeSelect.fire('change');
  ids.densitySelect.value = 'compact'; ids.densitySelect.fire('change');
  assert.deepEqual(ui.getPreferences(), { theme: 'light', fontScale: 1, density: 'compact' });
  ids.resetAppearance.fire('click');
  assert.deepEqual(ui.getPreferences(), { theme: 'system', fontScale: 1, density: 'standard' });
  assert.equal(attributes.get('data-theme'), 'dark');
  assert.equal(ui.migrateLegacy(1.4), false);
});

test('no DOM or theme detection is required when importing or using helpers in Node', () => {
  assert.doesNotThrow(() => api().createAppearance({}).initControls());
  const { env, attributes } = environment();
  env.matchMedia = () => { throw Error('unavailable'); };
  const ui = api().createAppearance(env);
  assert.equal(attributes.get('data-theme'), 'light');
  assert.doesNotThrow(() => ui.setTheme('dark'));
});

test('all visible theme surfaces use the specified tokens and maintain density through padding', () => {
  const css = fs.readFileSync(path.resolve(__dirname, '../../exam_room/ui/style.css'), 'utf8');
  assert.match(css, /\[data-theme=["']?dark/);
  assert.match(css, /#171b24/i);
  assert.match(css, /#fcfbf8/i);
  assert.match(css, /\[data-density=["']?compact/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /forced-colors/);
});

test('startup preferences from the local app survive a new HTTP origin and override old browser storage',()=>{
  const {env,ids,attributes}=environment(JSON.stringify({theme:'light',fontScale:1,density:'standard'}));
  ids.uiPreferences={textContent:JSON.stringify({theme:'dark',fontScale:1.3,density:'compact'})};
  const ui=api().createAppearance(env);
  assert.deepEqual(ui.getPreferences(),{theme:'dark',fontScale:1.3,density:'compact'});
  assert.equal(attributes.get('data-theme'),'dark');
  assert.equal(ui.migrateLegacy(1.5),false);
});
test('preference changes publish detached snapshots to the local app and tolerate an unavailable persistence hook',()=>{
  const {env}=environment();const snapshots=[];env.saveAppearancePreferences=x=>snapshots.push(x);
  const ui=api().createAppearance(env);ui.setTheme('dark');ui.changeFont(.05);
  assert.deepEqual(snapshots,[{theme:'dark',fontScale:1,density:'standard'},{theme:'dark',fontScale:1.05,density:'standard'}]);
  env.saveAppearancePreferences=()=>{throw Error('disk unavailable')};assert.doesNotThrow(()=>ui.setDensity('compact'));
});
