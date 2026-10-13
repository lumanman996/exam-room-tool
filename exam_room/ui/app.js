'use strict';
const $ = id => document.getElementById(id),
  esc = s =>
    String(s ?? '').replace(
      /[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
    );
let view,
  activePage = 'home',
  currentKind = 'students',
  entityPage = 0,
  seatPage = 0,
  formAction = null,
  upload = null,
  preview = null,
  polling = false,
  uploadRequest = 0;
const raw = html => ({ html }),
  clone = x => JSON.parse(JSON.stringify(x));
function table(head, rows) {
  return `<div class="table-wrap"><table><thead><tr>${head.map(x => `<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(x => `<td>${x?.html ?? esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function toast(message, bad = false) {
  document.querySelectorAll('.toast').forEach(x => x.remove());
  const el = document.createElement('div');
  el.textContent = message;
  el.className = 'toast ' + (bad ? 'bad' : '');
  el.setAttribute('role', bad ? 'alert' : 'status');
  document.body.append(el);
  $('liveStatus').textContent = message;
  setTimeout(() => el.remove(), bad ? 12000 : 4500);
}
const writingApis = new Set([
  'new',
  'demo',
  'open',
  'recover',
  'clone',
  'delete',
  'restore',
  'save',
  'confirm',
  'numbers',
  'number_undo',
  'room_save',
  'room_batch',
  'import',
  'plan_import',
  'adjust_seat',
  'adjust_invigilator',
  'monitor_lock_resolve',
  'undo',
  'report_layout_save',
  'edit_undo',
  'bulk_apply',
  'subject_catalog_save',
  'subject_batch',
  'seat_labels_apply',
]);
async function api(name, body = {}) {
  if (polling && writingApis.has(name)) throw Error('正在编排，请等待结束或取消后再修改方案。');
  let r;
  try {
    r = await fetch('/api/' + name, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN },
      body: JSON.stringify(body),
      keepalive: name === 'ui_preferences_save',
    });
  } catch (e) {
    throw Error('本机服务暂时无法连接。你的输入仍保留，请重试或重新打开软件。');
  }
  if (!r.ok) throw Error('本机服务返回错误（' + r.status + '），请重试。');
  const x = await r.json();
  if (!x.ok) throw Error(x.error || '操作未完成，请重试。');
  return x.data;
}
let preferenceQueue = Promise.resolve();
window.saveAppearancePreferences = preferences => {
  if ($('uiPreferences').textContent.trim() === '__UI_PREFS__') return;
  const snapshot = clone(preferences);
  preferenceQueue = preferenceQueue
    .then(() => api('ui_preferences_save', { preferences: snapshot }))
    .catch(e => toast('显示设置本次已应用，但未能保存到本机：' + e.message, true));
};
function bind(id, fn) {
  const el = $(id);
  if (!el) return;
  el.onclick = async () => {
    if (el.disabled || el.dataset.pending) return;
    el.dataset.pending = 'true';
    try {
      await fn();
    } catch (e) {
      toast(e.message, true);
    } finally {
      delete el.dataset.pending;
    }
  };
}
function page(name, force = false) {
  if (name !== 'home' && !view?.plan) {
    toast('请先新建或打开考试。', true);
    return;
  }
  if (!force && name !== activePage && window.Workspace) return Workspace.requestNavigation(() => page(name, true));
  window.Workspace?.remember();
  if (name !== activePage) window.DraggingUI?.cancel();
  activePage = name;
  document.querySelectorAll('main>.page').forEach(x => x.classList.toggle('active', x.id === name));
  document.querySelectorAll('#nav button').forEach(x => x.classList.toggle('active', x.dataset.page === name));
  ({
    home: renderRecent,
    overview: () => Workspace.overview(),
    data: renderData,
    schedule: renderSchedule,
    seats: renderSeats,
    invigilate: renderDuties,
    check: renderChecks,
    export: renderExport,
  })[name]();
  window.Workspace?.header();
  window.Workspace?.restoreScrolls();
  window.EditingUI?.rendered();
  return true;
}
async function refresh() {
  view = await api('state');
  renderAll();
}
let lastRenderedPlanId = null;
function renderAll() {
  const p = view.plan,
    same = p?.id === lastRenderedPlanId;
  const drafts = same && window.Workspace ? Workspace.captureDrafts() : [],
    scroll = window.scrollY,
    focused = document.activeElement?.id;
  window.Workspace?.activatePlan();
  const changed = view.validation?.errors.filter(x => x.code === 'number_seat_mismatch') || [];
  $('numberWarning').classList.toggle('hidden', !changed.length);
  $('numberWarningText').textContent = changed.length + ' 名学生的考号与固定位置不一致，请核对后更新。';
  $('version').textContent = view.version;
  $('saveStatus').textContent = p ? '已保存 · ' + p.updated_at.replace('T', ' ') : '所有操作保存在本机';
  $('saveStatus').classList.remove('save-failed');
  const l = view.license;
  $('licence').textContent = l.broken
    ? '许可异常 · 导出已锁定'
    : l.state === 'open'
      ? '源码开发版'
      : l.state === 'active'
        ? '已激活'
        : l.state === 'trial'
          ? `试用中 · 剩 ${l.daysLeft} 天`
          : '试用结束 · 导出需激活';
  page(p ? activePage : 'home', true);
  lastRenderedPlanId = p?.id || null;
  if (same) {
    window.Workspace?.restoreDrafts(drafts);
    if (focused && $(focused)) $(focused).focus({ preventScroll: true });
    window.scrollTo(0, scroll);
  }
  window.EditingUI?.rendered();
}
async function save(p = view.plan) {
  if (savePending) throw Error('正在保存上一项修改，请稍候再保存。');
  savePending = true;
  const source = document.activeElement,
    row = source?.closest('tr,.slot-row'),
    rules = source?.closest(
      '#seatSettings,#solverSettings,#numberDialog,#printOptions,#invigilate details,#planMenu,#examGroupsPanel'
    );
  window.Workspace?.remember();
  $('saveStatus').textContent = '正在保存…';
  try {
    const result = await api('save', { plan: p, revision: view.plan.revision });
    row?.classList.remove('unsaved');
    rules?.classList.remove('dirty');
    window.EditingUI?.committed(source);
    view = result;
    renderAll();
    return view;
  } catch (e) {
    $('saveStatus').textContent = '保存失败 · 修改尚未提交';
    $('saveStatus').classList.add('save-failed');
    throw e;
  } finally {
    savePending = false;
  }
}
function option(value, label, selected) {
  return `<option value="${esc(value)}" ${selected ? 'selected' : ''}>${esc(label)}</option>`;
}
function form(title, html, action) {
  $('formTitle').textContent = title;
  $('formContent').innerHTML = html;
  $('formError').classList.add('hidden');
  $('formSave').textContent = '保存';
  $('formSave').disabled = false;
  formAction = action;
  $('formDialog').classList.remove('dirty');
  $('formDialog').showModal();
  window.EditingUI?.watchDialog($('formDialog'));
}
function field(id, label, value = '', type = 'text') {
  return `<label>${esc(label)}<input id="${id}" type="${type}" value="${esc(value)}"></label>`;
}
function errorAt(id, e) {
  $(id).textContent = e.message;
  $(id).classList.remove('hidden');
}
bind('formSave', async () => {
  try {
    $('formSave').disabled = true;
    await formAction();
    window.EditingUI?.committed($('formDialog'));
    $('formDialog').classList.remove('dirty');
    $('formDialog').close();
  } catch (e) {
    errorAt('formError', e);
  } finally {
    $('formSave').disabled = false;
  }
});
bind('formCancel', () => Workspace.requestNavigation(() => $('formDialog').close()));
document.querySelectorAll('#nav button').forEach(b => (b.onclick = () => page(b.dataset.page)));
function renderRecent() {
  const a = view.recent || [];
  $('recentList').innerHTML = a.length
    ? a
        .map(
          x =>
            `<div class="recent-row"><button class="link-button" ${x.damaged ? 'data-recover' : 'data-open'}="${esc(x.id)}" ${x.damaged && !x.recoverable ? 'disabled' : ''}>${esc(x.name)}</button><span>${x.damaged ? '文件需要恢复' : x.students + ' 人'}</span><span>${esc(x.updated_at.slice(0, 10))}</span><button class="secondary" data-delete="${esc(x.id)}">删除</button></div>`
        )
        .join('')
    : '<p class="muted empty">还没有保存的考试。</p>';
  document.querySelectorAll('[data-open]').forEach(
    b =>
      (b.onclick = async () => {
        try {
          view = await api('open', { id: b.dataset.open });
          activePage = 'overview';
          renderAll();
        } catch (e) {
          toast(e.message, true);
        }
      })
  );
  document.querySelectorAll('[data-recover]').forEach(
    b =>
      (b.onclick = async () => {
        try {
          const backup = await api('recovery_preview', { id: b.dataset.recover });
          if (!backup.available) throw Error('没有可恢复的备份，请保留原文件并联系软件提供者。');
          form(
            '从备份恢复考试',
            `<p>${esc(backup.name)} · ${esc(backup.updated_at)}</p><p>将恢复这个备份，保留损坏的原文件。</p>`,
            async () => {
              view = await api('recover', { id: b.dataset.recover, backup_revision: backup.revision });
              activePage = 'overview';
              renderAll();
              toast('已从备份恢复考试。');
            }
          );
          $('formSave').textContent = '恢复这份备份';
        } catch (e) {
          toast(e.message, true);
        }
      })
  );
  document.querySelectorAll('[data-delete]').forEach(
    b =>
      (b.onclick = () =>
        form('移入回收站', '<p>删除后可在首页回收站恢复这份考试。</p>', async () => {
          view = await api('delete', { id: b.dataset.delete });
          renderAll();
        }))
  );
  $('trashList').innerHTML =
    (view.trash || [])
      .map(x => `<p>${esc(x.name)}　<button class="secondary" data-restore="${esc(x.id)}">恢复</button></p>`)
      .join('') || '<p class="muted">回收站为空。</p>';
  document.querySelectorAll('[data-restore]').forEach(
    b =>
      (b.onclick = async () => {
        view = await api('restore', { id: b.dataset.restore });
        renderAll();
      })
  );
}
function pager(id, count, index, set) {
  const pages = Math.max(1, Math.ceil(count / 100));
  $(id).innerHTML =
    `<span>共 ${count} 条 · 第 ${index + 1} / ${pages} 页</span><button class="secondary" id="${id}Prev" ${index <= 0 ? 'disabled' : ''}>上一页</button><button class="secondary" id="${id}Next" ${index + 1 >= pages ? 'disabled' : ''}>下一页</button>`;
  bind(id + 'Prev', () => set(index - 1));
  bind(id + 'Next', () => set(index + 1));
}
function renderData() {
  Workspace.data();
}
function entityValue(x, key) {
  const v = x[key];
  if (Array.isArray(v))
    return key === 'availability' || key === 'unavailable'
      ? v.map(w => `${w.date} ${w.start}-${w.end}`).join('；')
      : v.join('、');
  if (typeof v === 'boolean') return v ? '是' : '否';
  if (key === 'direction') return v === 'vertical' ? '竖排' : '横排';
  if (key === 'order') return v === 'snake' ? '蛇形' : '顺排';
  return v ?? '';
}
function renderEntities() {
  Workspace.entities();
}
function editEntity(kind, id) {
  if (!requireGrades(kind)) return;
  if (kind === 'rooms') {
    openRoomSettings(id);
    return;
  }
  const row = id ? view.plan[kind].find(x => x.id === id) : view.defaults[kind],
    fields = view.fields[kind];
  const html =
    '<div class="form-grid">' +
    Object.entries(fields)
      .map(([k, label]) => {
        const v = entityValue(row, k);
        if (k === 'grade')
          return `<label>${esc(label)}<select id="edit-grade">${formalGrades(view.plan)
            .map(g => option(g, g, g === v))
            .join('')}</select></label>`;
        if (kind === 'exams' && ['start', 'end'].includes(k))
          return `<label>${esc(label)}${clockControl('edit-' + k, v, label)}</label>`;
        if (['locked', 'special_seating'].includes(k))
          return `<label>${label}<select id="edit-${k}">${option('否', '否', !row[k])}${option('是', '是', row[k])}</select></label>`;
        if (k === 'order')
          return `<label>${label}<select id="edit-${k}">${option('顺排', '顺排', row[k] !== 'snake')}${option('蛇形', '蛇形', row[k] === 'snake')}</select></label>`;
        return field(
          'edit-' + k,
          label,
          v,
          k === 'date'
            ? 'date'
            : ['rows', 'cols', 'per_desk', 'capacity', 'duration', 'invigilators'].includes(k)
              ? 'number'
              : 'text'
        );
      })
      .join('') +
    '</div><p class="muted">多项用顿号分隔；时段用日期和起止时间，多段用分号分隔。</p>';
  form((id ? '编辑' : '添加') + '资料', html, async () => {
    const values = {},
      mapping = {};
    for (const k of Object.keys(fields)) {
      values[k] =
        kind === 'exams' && ['start', 'end'].includes(k) && $('edit-' + k).value
          ? parseClock($('edit-' + k).value)
          : $('edit-' + k).value;
      mapping[k] = k;
    }
    if (kind === 'exams' && values.start && values.end) {
      const duration = clockMinutes(values.end) - clockMinutes(values.start);
      if (duration <= 0) throw Error('结束时间须晚于开始时间。');
      values.duration = duration;
    }
    const normalized = await api('entity_prepare', { kind, row: values, mapping });
    const p = clone(view.plan);
    if (id) {
      const index = p[kind].findIndex(x => x.id === id);
      p[kind][index] = { ...p[kind][index], ...normalized, id };
      if (kind === 'students') p[kind][index].original = row.original;
    } else p[kind].push(normalized);
    await save(p);
  });
  if (kind === 'students' && row.original && Object.keys(row.original).length)
    $('formContent').insertAdjacentHTML(
      'beforeend',
      '<details><summary>查看原始导入列</summary>' +
        table(['原始列', '内容'], Object.entries(row.original)) +
        '</details>'
    );
  if (kind === 'exams') {
    bindClocks($('formContent'));
    window.SubjectUI?.setupEntity();
  }
  window.EditingUI?.watchDialog($('formDialog'), () => editEntity(kind, id));
}
async function encodeFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
$('fileInput').onchange = async () => {
  const f = $('fileInput').files[0];
  if (!f) return;
  if (!requireGrades(currentKind)) {
    $('fileInput').value = '';
    return;
  }
  const request = ++uploadRequest;
  try {
    const nextUpload = { kind: currentKind, filename: f.name, data: await encodeFile(f) },
      nextPreview = await api('import_preview', nextUpload);
    if (request !== uploadRequest) return;
    upload = nextUpload;
    preview = nextPreview;
    renderPreview();
    $('importDialog').showModal();
  } catch (e) {
    if (request === uploadRequest) toast(e.message, true);
  }
};
function renderPreview() {
  invalidateImport();
  $('importSheet').innerHTML = preview.sheets.map(s => option(s, s, s === preview.sheet)).join('');
  $('headerRow').value = preview.header_row;
  $('importSummary').textContent = `已识别 ${preview.count} 条资料，预览前 5 条。请检查每个字段对应的列。`;
  $('columnMapping').innerHTML = Object.entries(preview.fields)
    .map(
      ([key, label]) =>
        `<label>${label}<select data-map="${key}">${option('', '不导入')}${preview.headers.map(h => option(h, h, preview.mapping[key] === h)).join('')}</select></label>`
    )
    .join('');
  $('importPreview').innerHTML = table(
    preview.headers,
    preview.rows.slice(0, 5).map(r => preview.headers.map(h => r[h]))
  );
  $('importError').classList.add('hidden');
  document.querySelectorAll('[data-map]').forEach(el => (el.onchange = invalidateImport));
}
let importSnapshot = null,
  importRequest = 0;
function invalidateImport() {
  importRequest++;
  importSnapshot = null;
  $('importConfirm').disabled = true;
  $('importPreflightResult').innerHTML = '';
}
function importOptions() {
  return {
    kind: upload.kind,
    rows: preview.rows,
    mapping: Object.fromEntries([...document.querySelectorAll('[data-map]')].map(el => [el.dataset.map, el.value])),
    mode: $('importMode').value,
    revision: view.plan.revision,
  };
}
bind('reloadPreview', async () => {
  const request = ++uploadRequest;
  try {
    invalidateImport();
    const nextPreview = await api('import_preview', {
      ...upload,
      sheet: $('importSheet').value,
      header_row: Number($('headerRow').value),
    });
    if (request !== uploadRequest) return;
    preview = nextPreview;
    renderPreview();
  } catch (e) {
    errorAt('importError', e);
  }
});
bind('importCancel', () => {
  uploadRequest++;
  $('importDialog').close();
  invalidateImport();
});
bind('importPreflightBtn', async () => {
  const request = ++importRequest;
  try {
    const options = importOptions(),
      result = await api('import_preflight', options);
    if (request !== importRequest) return;
    importSnapshot = result.errors.length ? null : options;
    $('importPreflightResult').innerHTML =
      `<div class="${result.errors.length ? 'issue' : 'ok'}">新增 ${result.added} 条 · 更新 ${result.updated} 条 · 删除 ${result.removed} 条</div>` +
      [...result.errors, ...result.warnings]
        .slice(0, 100)
        .map(
          e =>
            `<p class="${result.errors.includes(e) ? 'issue' : 'warning'}">${e.row ? '数据第 ' + e.row + ' 行 · ' : ''}${esc(e.field || '')} ${esc(e.message)}</p>`
        )
        .join('') +
      (result.errors.length > 100 ? '<p class="muted">问题较多，修正前 100 项后再检查。</p>' : '');
    $('importConfirm').disabled = !!result.errors.length;
    $('importError').classList.add('hidden');
  } catch (e) {
    errorAt('importError', e);
  }
});
bind('importConfirm', async () => {
  if (!importSnapshot) return;
  try {
    $('importConfirm').disabled = true;
    view = await api('import', importSnapshot);
    $('importDialog').close();
    invalidateImport();
    renderAll();
    toast('资料已导入并保存。已有编排的变动请在检查页复核。');
  } catch (e) {
    errorAt('importError', e);
    importSnapshot = null;
  }
});
for (const id of ['importMode', 'importSheet', 'headerRow']) $(id).oninput = invalidateImport;
function renderSchedule() {
  renderScheduleControls();
}
function scopeOptions() {
  const p = view.plan,
    old = $('seatScope').value || 'base';
  $('seatScope').innerHTML =
    option('base', '整次考试固定座位', old === 'base') +
    p.exams
      .map(e => option(e.id, e.grade + ' ' + e.subject + (e.special_seating ? '（单独）' : ''), old === e.id))
      .join('');
}
function seatRows() {
  return Workspace.context().students;
}
function seatMapping() {
  return Workspace.context().mapping;
}
function renderSeats() {
  Workspace.seats();
}
function renderSeatTable() {
  Workspace.seatTable();
}
function renderRoom() {
  Workspace.room();
}
function editSeat(sid) {
  Workspace.seatEditor(sid);
}
function renderDuties() {
  Workspace.duties();
}
function editTeacher(d, index) {
  Workspace.teacherEditor(d, index);
}
function issueText(x) {
  const p = view.plan,
    ids = x.student_ids || [x.student_id].filter(Boolean),
    names = ids.map(id => {
      const s = p.students.find(x => x.id === id);
      return s ? s.name + '（' + s.class_name + '，' + s.number + '）' : id;
    });
  const room = p.rooms.find(r => r.id === x.room_id),
    ex = p.exams.find(e => e.id === x.exam_id);
  return [x.message, ...names, room?.name, x.seat ? '座号 ' + x.seat : '', ex ? ex.grade + ' ' + ex.subject : '']
    .filter(Boolean)
    .join(' · ');
}
function renderChecks() {
  Workspace.checks();
}
function renderExport() {
  ExportUI.render();
}
function selected() {
  return [...document.querySelectorAll('[data-export]:checked')].map(x => x.dataset.export);
}
function download(x) {
  if (!view.desktop) {
    const a = document.createElement('a');
    a.href = x.url;
    a.download = x.name;
    a.click();
  } else if (activePage !== 'export') {
    form('文件已生成', `<p>${esc(x.name)}</p><p>${esc(x.path)}</p><p>点击保存按钮在本机打开。</p>`, () =>
      api('open_file', { path: x.path })
    );
  }
  if (x.message) toast(x.message);
  if (activePage === 'export') {
    $('exportStatus').innerHTML =
      `<div class="ok">已生成：${esc(x.name)}<p>${esc(x.path)}</p><button class="secondary" id="openExport">打开文件</button><button class="secondary" id="openOutput">打开所在文件夹</button></div>`;
    bind('openExport', () => api('open_file', { path: x.path }));
    bind('openOutput', () => api('open_folder'));
  }
}
let busyTimer = null,
  savePending = false,
  taskObserver = null;
const taskDisabled = new Map();
const taskWriteSelectors =
  '#globalUndo,#restoreSaved,#newBtn,#demoBtn,#importPlanBtn,#savePlanBtn,#cloneBtn,#planInfoSave,#planName,#schoolName,#importEntityBtn,#addEntityBtn,#roomBatchBtn,#bulkEditSelected,#deleteSelected,#subjectCatalogBtn,#subjectBatchBtn,#gradeDeleteSelected,#editGrades,[data-edit],[data-remove],[data-copy-room],#schedule input,#schedule button,[data-default-group],[data-drag-mode],#labelPointPreview,#labelReset,#bulkDialog input,#bulkDialog select,#bulkDialog button,#solverSettings input,#solverSave,#roomDialog input,#roomDialog select,#roomDialog button,#roomBatchDialog input,#roomBatchDialog select,#roomBatchDialog button,#formDialog input,#formDialog select,#formSave,#seatSettings input,#seatSettings select,#seatSettings button,#applyLayoutBtn,#seatBtn,#undoBtn,#numberApply,#numberUndo,#seatAdjustContent input,#seatAdjustContent select,#seatAdjustSave,#invigilatorBtn,#invigilate details input,#applySettings,#teacherAdjustContent input,#teacherAdjustContent select,#teacherAdjustSave,#confirmBtn,#printSave,[data-open],[data-delete],[data-restore],[data-recover]';
function taskLockControls() {
  document.querySelectorAll(taskWriteSelectors).forEach(el => {
    if (!taskDisabled.has(el)) taskDisabled.set(el, el.disabled);
    if (!el.disabled) el.disabled = true;
  });
}
function taskBusy(on) {
  if (on) {
    document.body.append($('busy'));
    $('busy').classList.remove('hidden');
    $('cancelBtn').disabled = false;
    taskLockControls();
    taskObserver = new MutationObserver(taskLockControls);
    taskObserver.observe(document.querySelector('.shell'), {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['disabled'],
    });
    const began = Date.now();
    $('busyElapsed').textContent = '已用时 0 秒';
    busyTimer = setInterval(
      () => ($('busyElapsed').textContent = '已用时 ' + Math.floor((Date.now() - began) / 1000) + ' 秒'),
      1000
    );
  } else {
    clearInterval(busyTimer);
    taskObserver?.disconnect();
    taskDisabled.forEach((disabled, el) => {
      if (el.isConnected) el.disabled = disabled;
    });
    taskDisabled.clear();
    $('busy').classList.add('hidden');
  }
}
async function solve(kind, timeLimit = null, scopeOverride = null) {
  if (polling) return;
  timeLimit = timeLimit ?? view.plan.settings.time_limit ?? 30;
  if (Workspace.dirty()) {
    Workspace.requestNavigation(() => solve(kind, timeLimit));
    return;
  }
  const scopeKey = kind === 'seats' ? (scopeOverride ?? $('seatScope').value) : 'base',
    examId = scopeKey !== 'base' ? scopeKey : undefined;
  polling = true;
  taskBusy(true);
  $('busyText').textContent = '正在编排，请稍候…';
  let finished;
  try {
    await api('solve', { kind, time_limit: timeLimit, exam_id: examId, revision: view.plan.revision });
    while (polling) {
      await new Promise(resolve => setTimeout(resolve, 500));
      const x = await api('task');
      $('busyText').textContent = x.task?.message || '正在处理…';
      if (x.task?.state !== 'running') {
        finished = x.task;
        view = x.view || view;
        renderAll();
        toast(
          x.task?.message || '处理已结束。',
          ['error', 'infeasible', 'timeout', 'stale', 'partial'].includes(x.task?.status)
        );
        break;
      }
    }
  } finally {
    polling = false;
    taskBusy(false);
  }
  if (finished?.status === 'timeout' || (kind !== 'seats' && finished?.status === 'feasible')) {
    form(
      '本次编排结果',
      `<p>${esc(finished.message)}</p><p>可以使用当前结果，或增加求解时间后再次编排。</p>${field('extendTime', '再次求解最多秒数', 60, 'number')}`,
      () => {
        const limit = Number($('extendTime').value);
        if (!Number.isFinite(limit) || limit < 1 || limit > 300) throw Error('求解时间须为 1～300 秒。');
        setTimeout(() => solve(kind, limit, scopeKey).catch(e => toast(e.message, true)), 0);
      }
    );
    $('formSave').textContent = '延长时间再编排';
  }
}
bind('newBtn', openNewExam);
bind('demoBtn', async () => {
  view = await api('demo');
  activePage = 'overview';
  renderAll();
});
bind('refreshBtn', refresh);
bind('savePlanBtn', async () => download(await api('plan_export')));
bind('cloneBtn', () =>
  form('复制为新考试', field('cloneName', '新考试名称', view.plan.name + '（副本）'), async () => {
    view = await api('clone', { id: view.plan.id, name: $('cloneName').value });
    renderAll();
  })
);
for (const id of ['planName', 'schoolName']) $(id).oninput = () => $('planMenu').classList.add('dirty');
bind('planInfoSave', async () => {
  try {
    $('planInfoError').classList.add('hidden');
    const p = clone(view.plan);
    p.name = $('planName').value;
    p.school = $('schoolName').value;
    await save(p);
    $('planMenu').classList.remove('dirty');
    $('planMenu').open = false;
    toast('考试信息已保存。');
  } catch (e) {
    $('planMenu').open = true;
    errorAt('planInfoError', e);
  }
});
document.addEventListener('click', e => {
  if ($('planMenu').open && !$('planMenu').contains(e.target)) $('planMenu').open = false;
});
$('entityKind').onchange = () => {
  entityPage = 0;
  renderEntities();
};
$('entitySearch').oninput = () => {
  entityPage = 0;
  renderEntities();
};
bind('addEntityBtn', () => editEntity($('entityKind').value));
bind('numberBtn', () => openNumberSettings());
bind('addSlotBtn', async () => {
  if (scheduleHasUnsaved()) throw Error('请先保存黄色行，再添加时段。');
  const p = clone(view.plan);
  p.settings.slots.push({ date: '', start: '08:00', end: '12:00' });
  await save(p);
});
bind('scheduleBtn', () => {
  if (scheduleHasUnsaved()) throw Error('请先保存黄色行中的时间，再自动安排。');
  return solve('schedule');
});
bind('applyLayoutBtn', applySeatLayout);
$('seatScope').onchange = () => {
  seatPage = 0;
  renderSeatTable();
  renderRoom();
};
$('previewRoom').onchange = () => {
  renderRoom();
  syncLayoutControls();
};
$('seatSearch').oninput = () => {
  seatPage = 0;
  renderSeatTable();
};
bind('seatBtn', async () => {
  const p = clone(view.plan);
  collectSeatSettings(p);
  await save(p);
  $('seatSettings').classList.remove('dirty');
  await solve('seats');
});
bind('undoBtn', async () => {
  view = await api('undo');
  renderAll();
});
bind('applySettings', async () => {
  const p = clone(view.plan);
  Object.assign(p.settings, {
    avoid_subject: $('avoidSubject').checked,
    avoid_class: $('avoidClass').checked,
    invigilators: Number($('invigilatorCount').value),
  });
  await save(p);
});
bind('invigilatorBtn', () => solve('invigilators'));
bind('cancelBtn', async () => {
  await api('cancel');
  $('cancelBtn').disabled = true;
  $('busyText').textContent = '正在取消，请稍候…';
});
bind('confirmBtn', async () => {
  view = await api('confirm', { revision: view.plan.revision });
  renderAll();
  toast('当前方案已复核确认');
});
bind('exportXlsx', () => ExportUI.generate('xlsx'));
bind('exportPdf', () => ExportUI.generate('pdf'));
bind('helpBtn', () => $('helpDialog').showModal());
bind('licenceBtn', () =>
  form(
    '激活考场编排',
    `<p>${esc(view.license.message)}</p><p>本机机器码：<b>${esc(view.license.machine)}</b></p><p>${esc(view.license.contact || '请向软件提供者获取本机激活码。')}</p><label>激活码<textarea id="activationCode" rows="4"></textarea></label>`,
    async () => {
      view = await api('activate', { code: $('activationCode').value });
      renderAll();
      toast('激活成功');
    }
  )
);
bind('updateBtn', async () => {
  const x = await api('update_check');
  form(
    '软件更新',
    `<p>${esc(x.reason || x.error || (x.newer ? '发现新版本' : '当前没有可用的新版本'))}</p><p>${esc(x.latest || '')}</p><p>更新前自动保存当前方案。用户方案和激活记录保留在本机。</p>`,
    async () => {
      if (!x.canAuto) return;
      await api('update_start');
      $('busy').classList.remove('hidden');
      while (true) {
        const s = await api('update_status');
        $('busyText').textContent = '正在下载更新… ' + s.percent + '%';
        if (s.phase === 'ready') {
          await api('update_apply');
          break;
        }
        if (s.phase === 'error') throw Error(s.error || s.message);
        await new Promise(resolve => setTimeout(resolve, 700));
      }
    }
  );
});
bind('importPlanBtn', () => {
  $('planFileInput').value = '';
  $('planFileInput').click();
});
$('planFileInput').onchange = async () => {
  const f = $('planFileInput').files[0];
  if (!f) return;
  try {
    view = await api('plan_import', { data: await encodeFile(f) });
    activePage = 'overview';
    renderAll();
  } catch (e) {
    toast(e.message, true);
  }
};
setInterval(() => api('ping').catch(() => {}), 10000);
refresh().catch(e => toast(e.message, true));
