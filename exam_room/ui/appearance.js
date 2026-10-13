/* Local display preferences; independent from exam revisions and persisted by the local app. */
(function (root) {
  'use strict';
  const STORAGE_KEY = 'exam-room-ui-preferences';
  const DEFAULTS = Object.freeze({ theme: 'system', fontScale: 1, density: 'standard' });
  const validScale = value => typeof value === 'number' && Number.isFinite(value);

  function normalizePreferences(value) {
    const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    const scale = validScale(source.fontScale)
      ? Math.round(Math.max(0.9, Math.min(1.5, source.fontScale)) * 20) / 20
      : 1;
    return {
      theme: ['system', 'light', 'dark'].includes(source.theme) ? source.theme : 'system',
      fontScale: scale,
      density: source.density === 'compact' ? 'compact' : 'standard',
    };
  }

  function readStored(storage) {
    try {
      const value = JSON.parse(storage?.getItem(STORAGE_KEY) || 'null');
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch (_) {
      return {};
    }
  }

  function readPreferences(storage) {
    return normalizePreferences(readStored(storage));
  }

  function createAppearance(env) {
    env = env || {};
    let storage;
    // Merely accessing localStorage can throw in a restricted webview.
    try {
      storage = env.localStorage;
    } catch (_) {
      storage = undefined;
    }
    let bootstrap;
    try {
      bootstrap = JSON.parse(env.document?.getElementById('uiPreferences')?.textContent || 'null');
    } catch (_) {
      bootstrap = null;
    }
    const stored =
      bootstrap && typeof bootstrap === 'object' && !Array.isArray(bootstrap) ? bootstrap : readStored(storage);
    let preferences = normalizePreferences(stored);
    let hasLocalScale = validScale(stored.fontScale);
    let media;
    try {
      media = env.matchMedia?.('(prefers-color-scheme: dark)');
    } catch (_) {
      media = undefined;
    }
    const bound = new WeakSet();
    const element = id => env.document?.getElementById(id);

    function updateControls() {
      const theme = element('themeSelect'),
        density = element('densitySelect');
      if (theme) theme.value = preferences.theme;
      if (density) density.value = preferences.density;
      const percent = element('fontPercent');
      if (percent) percent.textContent = Math.round(preferences.fontScale * 100) + '%';
      const minus = element('fontMinus'),
        plus = element('fontPlus');
      if (minus) minus.disabled = preferences.fontScale <= 0.9;
      if (plus) plus.disabled = preferences.fontScale >= 1.5;
    }

    function apply() {
      const html = env.document?.documentElement;
      if (html) {
        const theme = preferences.theme === 'system' ? (media?.matches ? 'dark' : 'light') : preferences.theme;
        html.setAttribute('data-theme', theme);
        html.setAttribute('data-density', preferences.density);
        html.style.setProperty('--font-scale', String(preferences.fontScale));
        html.style.fontSize = 15 * preferences.fontScale + 'px';
        html.style.colorScheme = theme;
      }
      updateControls();
    }

    function persist() {
      // An unavailable store should never prevent changing this session's display.
      try {
        storage?.setItem(STORAGE_KEY, JSON.stringify(preferences));
      } catch (_) {
        /* session preference remains usable */
      }
      try {
        env.saveAppearancePreferences?.({ ...preferences });
      } catch (_) {
        /* UI remains usable; the app reports its own save error. */
      }
    }

    function setPreferences(patch) {
      preferences = normalizePreferences({ ...preferences, ...patch });
      if (Object.prototype.hasOwnProperty.call(patch, 'fontScale')) hasLocalScale = true;
      apply();
      persist();
      return { ...preferences };
    }

    function changeFont(delta) {
      if (!validScale(delta)) return { ...preferences };
      return setPreferences({ fontScale: preferences.fontScale + delta });
    }

    function setTheme(value) {
      return setPreferences({ theme: value });
    }
    function setDensity(value) {
      return setPreferences({ density: value });
    }
    function reset() {
      return setPreferences({ ...DEFAULTS });
    }

    function migrateLegacy(scale) {
      if (hasLocalScale || !validScale(scale) || scale <= 0) return false;
      setPreferences({ fontScale: scale });
      return true;
    }

    function initControls() {
      const bindings = [
        ['themeSelect', 'change', event => setTheme(event.target.value)],
        ['densitySelect', 'change', event => setDensity(event.target.value)],
        ['fontMinus', 'click', () => changeFont(-0.05)],
        ['fontPlus', 'click', () => changeFont(0.05)],
        ['fontReset', 'click', () => setPreferences({ fontScale: 1 })],
        ['resetAppearance', 'click', reset],
      ];
      for (const [id, type, listener] of bindings) {
        const control = element(id);
        if (!control || bound.has(control)) continue;
        control.addEventListener(type, listener);
        bound.add(control);
      }
      updateControls();
    }

    function onSystemChange() {
      if (preferences.theme === 'system') apply();
    }
    if (media?.addEventListener) media.addEventListener('change', onSystemChange);
    else if (media?.addListener) media.addListener(onSystemChange);
    function destroy() {
      if (media?.removeEventListener) media.removeEventListener('change', onSystemChange);
      else if (media?.removeListener) media.removeListener(onSystemChange);
    }
    apply();
    return {
      initControls,
      migrateLegacy,
      changeFont,
      setTheme,
      setDensity,
      reset,
      getPreferences: () => ({ ...preferences }),
      destroy,
    };
  }

  const helpers = { STORAGE_KEY, DEFAULTS, normalizePreferences, readPreferences, createAppearance };
  if (typeof module === 'object' && module.exports) module.exports = helpers;
  if (root.document) root.Appearance = Object.assign(createAppearance(root), helpers);
})(typeof globalThis !== 'undefined' ? globalThis : this);
