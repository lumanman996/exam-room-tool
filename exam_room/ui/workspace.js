'use strict';
// Pure view helpers keep identity, effective seating and filtering consistent.
const WorkspaceCore = (() => {
  const searchCache = new WeakMap();
  function searchText(row) {
    if (!searchCache.has(row)) {
      const values = Object.entries(row)
        .filter(([k]) => !['id', 'student_id', 'teacher_id', 'original'].includes(k))
        .map(([, v]) => (Array.isArray(v) ? v.join(' ') : typeof v === 'object' ? '' : v));
      searchCache.set(row, [...values, ...Object.values(row.original || {})].join(' ').toLocaleLowerCase());
    }
    return searchCache.get(row);
  }
  function filterRecords(rows, query = '', filters = {}) {
    const q = String(query).trim().toLocaleLowerCase();
    return rows.filter(
      row => Object.entries(filters).every(([k, v]) => !v || row[k] === v) && (!q || searchText(row).includes(q))
    );
  }
  function pageRows(rows, index = 0, size = 100) {
    const pages = Math.max(1, Math.ceil(rows.length / size));
    index = Math.max(0, Math.min(pages - 1, Number(index) || 0));
    return { rows: rows.slice(index * size, (index + 1) * size), index, pages, count: rows.length };
  }
  function participants(plan, exam) {
    return plan.students.filter(
      s => s.grade === exam.grade && (!s.subjects?.length || s.subjects.includes(exam.subject))
    );
  }
  // 与后端 engine.fixed_seat_students 一致：按考场座位编考号时人人需要固定座位；
  // 流水号方式下只参加单独排座科目的学生不占固定座位。
  function fixedSeatStudents(plan) {
    if (plan.settings?.number_rule !== 'serial') return plan.students;
    const ids = new Set(plan.exams.filter(e => !e.special_seating).flatMap(e => participants(plan, e).map(s => s.id)));
    return plan.students.filter(s => ids.has(s.id));
  }
  function seatContext(plan, scope = 'base') {
    const exam = plan.exams.find(e => e.id === scope);
    return {
      exam,
      students: exam ? participants(plan, exam) : fixedSeatStudents(plan),
      mapping: (exam?.special_seating ? plan.seats[exam.id] : plan.seats.base) || {},
    };
  }
  function occupants(plan, scope, roomId, session = '') {
    let { students, mapping } = seatContext(plan, scope);
    if (scope === 'base' && session) {
      const ids = new Set(
        plan.exams
          .filter(e => [e.date, e.start, e.end].join('|') === session)
          .flatMap(e => participants(plan, e).map(s => s.id))
      );
      students = students.filter(s => ids.has(s.id));
    }
    const bySeat = {};
    for (const s of students) {
      const a = mapping[s.id];
      if (a?.room_id === roomId) (bySeat[a.seat] ??= []).push(s);
    }
    return bySeat;
  }
  function nextStep(v) {
    const p = v.plan;
    if (!p) return { page: 'home', label: '新建考试', message: '新建考试，开始准备资料。' };
    if (!p.grades?.length)
      return {
        page: 'data',
        grades: true,
        label: '设置本次考试年级',
        message: '先确定参试年级数量和名称，再准备资料。',
      };
    for (const [key, label] of [
      ['students', '学生名单'],
      ['rooms', '考场资料'],
      ['teachers', '教师资料'],
      ['exams', '考试科目'],
    ])
      if (!p[key]?.length)
        return { page: 'data', kind: key, label: '准备' + label, message: '还没有' + label + '，先导入或添加资料。' };
    if (p.exams.some(e => !e.date || !e.start || !e.end))
      return { page: 'schedule', label: '安排考试日程', message: '还有考试未填写日期或起止时间。' };
    const missing = fixedSeatStudents(p).filter(s => !p.seats?.base?.[s.id]).length;
    if (missing) return { page: 'seats', label: '编排学生座位', message: `还有 ${missing} 名学生未安排固定座位。` };
    const numbers = p.students.filter(s => !s.number).length;
    if (numbers)
      return {
        page: 'seats',
        tab: 'numbering',
        label: '核对并生成考号',
        message: `还有 ${numbers} 名学生未填写考号。`,
      };
    if ((v.duties || []).some(d => (p.invigilation[d.id] || []).filter(x => x.teacher_id).length < d.required))
      return { page: 'invigilate', label: '补齐监考安排', message: '还有监考位置待安排。' };
    if (v.validation?.errors.length || p.stale?.length)
      return { page: 'check', label: '检查并确认方案', message: '核对当前方案，处理必须修正或需要重新检查的问题。' };
    return { page: 'export', label: '导出考务材料', message: '硬性检查通过，可以核对版式并生成材料。' };
  }
  return { filterRecords, pageRows, seatContext, occupants, nextStep, participants, fixedSeatStudents };
})();
if (typeof module !== 'undefined') module.exports = WorkspaceCore;

if (typeof document !== 'undefined') {
  window.Workspace = (() => {
    const memory = new Map(),
      ui = { seatTab: 'seating', seatView: 'map', dutyView: 'duties', dutyPage: 0, workloadPage: 0 };
    const remembered = [
      'entityKind',
      'entitySearch',
      'entityGrade',
      'entityClass',
      'seatScope',
      'previewRoom',
      'seatSession',
      'seatSearch',
      'seatUnassigned',
      'dutySearch',
      'dutyDate',
      'dutyMissing',
    ];
    let pendingNavigation = null,
      editingSeat = null,
      editingDuty = null,
      renderedId = null,
      candidateRequest = 0;
    const labels = { students: '学生名单', rooms: '考场资料', teachers: '教师资料', exams: '考试科目' };
    const stages = ['overview', 'data', 'schedule', 'seats', 'invigilate', 'check', 'export'];
    function remember() {
      if (!view?.plan || view.plan.id !== renderedId) return;
      const data = {};
      for (const id of remembered) {
        const el = $(id);
        if (el) data[id] = el.type === 'checkbox' ? el.checked : el.value;
      }
      const scrolls = { ...(memory.get(view.plan.id)?.scrolls || {}) };
      document.querySelectorAll('.page.active .table-wrap,.page.active .room-layout').forEach(el => {
        const id = el.id || el.parentElement.id;
        if (id) scrolls[id] = { top: el.scrollTop, left: el.scrollLeft };
      });
      memory.set(view.plan.id, { data, entityPage, seatPage, scrolls, ...ui });
    }
    function activatePlan() {
      if (renderedId === view.plan?.id) return;
      renderedId = view.plan?.id || null;
      $('planMenu').open = false;
      $('planInfoError').classList.add('hidden');
      Object.assign(ui, { seatTab: 'seating', seatView: 'map', dutyView: 'duties', dutyPage: 0, workloadPage: 0 });
      entityPage = seatPage = 0;
      for (const id of remembered) {
        const el = $(id);
        if (el) {
          if (el.type === 'checkbox') el.checked = false;
          else el.value = id === 'entityKind' ? 'students' : id === 'seatScope' ? 'base' : '';
        }
      }
      editingSeat = editingDuty = null;
      discardDrafts(false);
      restore();
    }
    function restore() {
      const state = memory.get(view.plan?.id);
      if (!state) return;
      Object.assign(ui, {
        seatTab: state.seatTab,
        seatView: state.seatView,
        dutyView: state.dutyView,
        dutyPage: state.dutyPage,
        workloadPage: state.workloadPage,
      });
      entityPage = state.entityPage;
      seatPage = state.seatPage;
      for (const [id, value] of Object.entries(state.data)) {
        const el = $(id);
        if (!el) continue;
        if (el.type === 'checkbox') el.checked = value;
        else if (el.tagName !== 'SELECT' || [...el.options].some(o => o.value === value)) el.value = value;
      }
    }
    function restoreScrolls() {
      const scrolls = memory.get(view.plan?.id)?.scrolls || {};
      for (const [id, pos] of Object.entries(scrolls)) {
        const owner = $(id),
          el = owner?.matches('.table-wrap,.room-layout') ? owner : owner?.querySelector('.table-wrap,.room-layout');
        if (el) {
          el.scrollTop = pos.top;
          el.scrollLeft = pos.left;
        }
      }
    }
    function fillSelect(id, values, allLabel) {
      const el = $(id),
        old = el.value;
      el.innerHTML = option('', allLabel, !old) + values.map(v => option(v, v, v === old)).join('');
    }
    function bindSearch(id, fn) {
      let timer,
        composing = false;
      const el = $(id);
      el.addEventListener('compositionstart', () => {
        composing = true;
        clearTimeout(timer);
      });
      el.addEventListener('compositionend', () => {
        composing = false;
        clearTimeout(timer);
        timer = setTimeout(fn, 150);
      });
      el.oninput = e => {
        clearTimeout(timer);
        if (!composing && !e.isComposing) timer = setTimeout(fn, 150);
      };
    }
    function header() {
      const p = view.plan,
        v = view.validation;
      Appearance.migrateLegacy(p?.settings.font_scale);
      $('planMenu').classList.toggle('hidden', !p);
      $('currentName').textContent = p?.name || '我的考试';
      $('currentSchool').textContent = p?.school || '';
      if (!$('planMenu').classList.contains('dirty')) {
        $('planName').value = p?.name || '';
        $('schoolName').value = p?.school || '';
      }
      const status = $('headerCheckBtn');
      status.textContent = !p ? '准备开始' : v?.errors.length ? `${v.errors.length} 项需处理` : '检查通过';
      status.classList.toggle('has-issues', !!v?.errors.length);
      $('pageFooter').classList.toggle('hidden', !p || activePage === 'home');
      const i = stages.indexOf(activePage);
      $('previousStep').disabled = i <= 0;
      $('nextStep').disabled = i < 0 || i === stages.length - 1;
      document.querySelectorAll('#nav button').forEach(b => {
        b.disabled = !p;
        b.setAttribute('aria-current', b.dataset.page === activePage ? 'page' : 'false');
      });
    }
    function overview() {
      const p = view.plan,
        next = WorkspaceCore.nextStep(view);
      const counts = [
        ['students', '学生名单', p.students.length + ' 人'],
        ['rooms', '考场资料', p.rooms.length + ' 间'],
        ['teachers', '教师资料', p.teachers.length + ' 人'],
        ['exams', '考试科目', p.exams.length + ' 场'],
      ];
      $('overviewContent').innerHTML =
        `<div class="overview-next"><div><span class="eyebrow">下一步</span><h2>${esc(next.message)}</h2></div><button class="primary" id="overviewNext">${esc(next.label)} →</button></div><div class="workflow-strip">${[
          ['data', '资料'],
          ['schedule', '日程'],
          ['seats', '座位'],
          ['numbering', '考号'],
          ['invigilate', '监考'],
          ['check', '检查'],
          ['export', '导出'],
        ]
          .map(
            ([key, name], i) =>
              `<button data-flow="${key}"><span>${String(i + 1).padStart(2, '0')}</span>${name}</button>`
          )
          .join(
            ''
          )}</div><div class="section-head"><h2>资料准备</h2></div><div class="overview-list">${counts.map(([key, name, count]) => `<button class="overview-row" data-overview-kind="${key}"><span>${name}</span><b>${count}</b><span>查看 →</span></button>`).join('')}</div><div class="overview-note"><b>${view.validation.errors.length} 项必须处理</b><span>${view.validation.warnings.length} 项核对提示</span><button class="link-button" data-flow="check">查看检查结果 →</button></div>`;
      bind('overviewNext', () => {
        page(next.page);
        if (next.grades) openGradeSettings();
        if (next.kind) selectKind(next.kind);
        if (next.tab) selectSeatTab(next.tab);
      });
      document.querySelectorAll('[data-flow]').forEach(
        b =>
          (b.onclick = () => {
            if (b.dataset.flow === 'numbering') openNumberSettings();
            else page(b.dataset.flow);
          })
      );
      document.querySelectorAll('[data-overview-kind]').forEach(
        b =>
          (b.onclick = () => {
            page('data');
            selectKind(b.dataset.overviewKind);
          })
      );
    }
    function selectKind(kind) {
      $('entityKind').value = kind;
      entityPage = 0;
      $('entitySearch').value = '';
      $('entityGrade').value = '';
      $('entityClass').value = '';
      remember();
      data();
    }
    function data() {
      const p = view.plan;
      renderGradeSummary();
      restore();
      const kind = $('entityKind').value;
      document.querySelectorAll('[data-kind]').forEach(b => {
        const active = b.dataset.kind === kind;
        b.setAttribute('aria-selected', String(active));
        b.textContent = labels[b.dataset.kind] + ` · ${p[b.dataset.kind].length}`;
      });
      $('importEntityBtn').textContent = '导入' + labels[kind];
      $('addEntityBtn').textContent =
        '添加' + { students: '学生', rooms: '考场', teachers: '教师', exams: '科目' }[kind];
      $('entitySearch').placeholder =
        '搜索' +
        (kind === 'students'
          ? '姓名、班级或考号'
          : kind === 'rooms'
            ? '考场或教室位置'
            : kind === 'teachers'
              ? '教师或学科'
              : '年级或科目');
      $('entityGrade').classList.toggle('hidden', !['students', 'exams'].includes(kind));
      $('entityClass').classList.toggle('hidden', kind !== 'students');
      fillSelect('entityGrade', formalGrades(p), '全部年级');
      updateClasses();
      entities();
    }
    function updateClasses() {
      fillSelect(
        'entityClass',
        [
          ...new Set(
            view.plan.students
              .filter(s => !$('entityGrade').value || s.grade === $('entityGrade').value)
              .map(s => s.class_name)
          ),
        ].sort(),
        '全部班级'
      );
    }
    function entities() {
      const kind = $('entityKind').value,
        p = view.plan,
        fields = view.fields[kind];
      const filters =
        kind === 'students'
          ? { grade: $('entityGrade').value, class_name: $('entityClass').value }
          : kind === 'exams'
            ? { grade: $('entityGrade').value }
            : {};
      const all = WorkspaceCore.filterRecords(p[kind], $('entitySearch').value, filters),
        slice = WorkspaceCore.pageRows(all, entityPage);
      entityPage = slice.index;
      const main = {
        students: ['grade', 'class_name', 'name', 'student_no', 'number', 'subjects'],
        rooms: ['code', 'name', 'location', 'capacity', 'rows', 'cols', 'per_desk', 'direction', 'order'],
        teachers: ['name', 'subjects', 'classes', 'unavailable'],
        exams: ['grade', 'subject', 'duration', 'date', 'start', 'end'],
      };
      const keys = main[kind].filter(k => fields[k]);
      $('roomBatchBtn').classList.toggle('hidden', kind !== 'rooms');
      $('entityTable').innerHTML = slice.count
        ? table(
            ['选择', ...keys.map(k => fields[k]), '操作'],
            slice.rows.map(x => [
              raw(
                `<input type="checkbox" data-select-entity="${esc(x.id)}" aria-label="选择${esc(x.name || x.subject || x.code)}">`
              ),
              ...keys.map(k => entityValue(x, k)),
              raw(
                `<button class="link-button" data-edit="${esc(x.id)}">${kind === 'rooms' ? '设置行列／布局' : '编辑'}</button> ${kind === 'rooms' ? `<button class="link-button" data-copy-room="${esc(x.id)}">复制</button>` : ''} <button class="link-button" data-remove="${esc(x.id)}">删除</button>`
              ),
            ])
          )
        : `<div class="empty-state">${p[kind].length ? '没有找到符合条件的资料，请调整搜索或筛选。' : '还没有' + labels[kind] + '，请导入资料或添加。'}</div>`;
      document.querySelectorAll('[data-edit]').forEach(b => (b.onclick = () => editEntity(kind, b.dataset.edit)));
      document.querySelectorAll('[data-copy-room]').forEach(b => (b.onclick = () => openRoomBatch(b.dataset.copyRoom)));
      document
        .querySelectorAll('[data-remove]')
        .forEach(b => (b.onclick = () => BulkUI.open(kind, 'delete', [b.dataset.remove])));
      window.DataSelection?.render(all, kind);
      pager('entityPager', all.length, entityPage, i => {
        entityPage = i;
        entities();
        remember();
      });
      remember();
    }
    function selectSeatTab(tab) {
      ui.seatTab = tab;
      $('seatingPanel').classList.toggle('hidden', tab !== 'seating');
      $('numberDialog').classList.toggle('hidden', tab !== 'numbering');
      $('seatBtn').classList.toggle('hidden', tab === 'numbering');
      document
        .querySelectorAll('[data-seat-tab]')
        .forEach(b => b.setAttribute('aria-selected', String(b.dataset.seatTab === tab)));
      remember();
    }
    function selectSeatView(mode) {
      ui.seatView = mode;
      $('roomPreview').classList.toggle('hidden', mode !== 'map');
      $('seatTablePanel').classList.toggle('hidden', mode !== 'table');
      document
        .querySelectorAll('[data-seat-view]')
        .forEach(b => b.setAttribute('aria-pressed', String(b.dataset.seatView === mode)));
      remember();
    }
    function seats() {
      restore();
      scopeOptions();
      const p = view.plan;
      $('mode').value = p.settings.mode;
      $('seed').value = p.settings.seed;
      renderMixControls();
      const keys = [...new Set(p.students.flatMap(s => Object.keys(s.original || {})))];
      $('scoreField').innerHTML =
        option('score', '资料中的“成绩”', !p.settings.score_field) +
        keys.map(k => option(k, k, p.settings.score_field === k)).join('');
      const old = $('previewRoom').value;
      $('previewRoom').innerHTML = p.rooms.map(r => option(r.id, r.code + ' · ' + r.name, r.id === old)).join('');
      const session = $('seatSession').value,
        ss = [...new Set(p.exams.filter(e => e.date && e.start && e.end).map(e => [e.date, e.start, e.end].join('|')))];
      $('seatSession').innerHTML =
        option('', '固定安排总览', !session) + ss.map(s => option(s, s.replaceAll('|', ' · '), s === session)).join('');
      $('seatSessionRow').classList.toggle('hidden', $('seatScope').value !== 'base');
      seatTable();
      room();
      syncLayoutControls();
      $('solverLimit').value = p.settings.time_limit || 30;
      syncNumberRule();
      modeVisibility();
      route();
      selectSeatTab(ui.seatTab);
      selectSeatView(ui.seatView);
      $('seatSettings').open = !Object.keys(p.seats.base || {}).length;
      if (
        editingSeat &&
        !$('seatAdjustPanel').classList.contains('hidden') &&
        !$('seatAdjustPanel').classList.contains('dirty')
      )
        seatEditor(editingSeat);
    }
    function modeVisibility() {
      $('scoreFieldRow').classList.toggle('hidden', $('mode').value !== 'score');
      $('seedRow').classList.toggle('hidden', $('mode').value !== 'random');
      $('seatSettingsSummary').textContent = $('mode').selectedOptions[0]?.textContent || '';
    }
    function route() {
      const vertical = $('seatDirection').value === 'vertical',
        snake = $('seatOrder').value === 'snake';
      const numbers = [];
      for (let r = 0; r < 3; r++) {
        const row = [];
        for (let c = 0; c < 3; c++) {
          const major = vertical ? c : r,
            minor = vertical ? r : c;
          row.push(major * 3 + (snake && major % 2 ? 2 - minor : minor) + 1);
        }
        numbers.push(row);
      }
      $('routeSketch').innerHTML =
        '<span class="muted">讲台在上方 · 编号方向示意</span><div>' +
        numbers
          .map(row => '<span>' + row.map(n => '<b>' + String(n).padStart(2, '0') + '</b>').join('') + '</span>')
          .join('') +
        '</div>';
    }
    function context() {
      return WorkspaceCore.seatContext(view.plan, $('seatScope').value || 'base');
    }
    function seatTable() {
      const p = view.plan,
        x = context();
      let students = WorkspaceCore.filterRecords(x.students, $('seatSearch').value);
      if ($('seatUnassigned').checked) students = students.filter(s => !x.mapping[s.id]);
      const slice = WorkspaceCore.pageRows(students, seatPage);
      seatPage = slice.index;
      const count = x.students.filter(s => x.mapping[s.id]).length;
      $('seatSummary').textContent =
        `已安排 ${count} / ${x.students.length} 人 · ${x.students.filter(s => !s.number).length} 人尚无考号${x.exam ? ' · ' + (x.exam.special_seating ? '本页调整仅用于 ' + x.exam.subject : '当前使用固定座位；调整后建立本场独立方案') : ''}`;
      $('seatTable').innerHTML = students.length
        ? table(
            ['座号', '考号', '年级', '班级', '姓名', '考场', '状态', '操作'],
            slice.rows.map(s => {
              const a = x.mapping[s.id] || {},
                r = p.rooms.find(r => r.id === a.room_id);
              return [
                a.seat ? String(a.seat).padStart(2, '0') : '—',
                s.number || '待生成',
                s.grade,
                s.class_name,
                s.name,
                r?.name || '未安排',
                a.locked ? '已锁定' : '',
                raw(`<button class="link-button" data-seat="${esc(s.id)}">调整</button>`),
              ];
            })
          )
        : '<div class="empty-state">没有符合条件的学生。</div>';
      document.querySelectorAll('[data-seat]').forEach(b => (b.onclick = () => editSeat(b.dataset.seat)));
      pager('seatPager', students.length, seatPage, i => {
        seatPage = i;
        seatTable();
      });
      remember();
    }
    function room() {
      const p = view.plan,
        r = p.rooms.find(x => x.id === $('previewRoom').value),
        x = context();
      $('roomList').innerHTML =
        p.rooms
          .map(room => {
            const count = x.students.filter(s => x.mapping[s.id]?.room_id === room.id).length;
            return `<button class="room-list-item ${room.id === r?.id ? 'active' : ''}" data-room="${esc(room.id)}"><span>${esc(room.code)} · ${esc(room.name)}</span><small>${count} 人 / ${room.capacity} 座</small></button>`;
          })
          .join('') || '<p class="muted">还没有考场。</p>';
      document.querySelectorAll('[data-room]').forEach(
        b =>
          (b.onclick = () => {
            $('previewRoom').value = b.dataset.room;
            room();
            syncLayoutControls();
            route();
            remember();
          })
      );
      if (!r) {
        $('roomPreview').innerHTML = '<div class="empty-state">先在基础资料中添加考场。</div>';
        return;
      }
      $('roomCanvasTitle').textContent = r.code + ' · ' + r.name;
      const layout = view.layouts[r.id] || [],
        physical = view.physical_layouts?.[r.id] || [],
        byPosition = Object.fromEntries(layout.map(s => [s.row + '-' + s.col, s])),
        full = Object.fromEntries(physical.map(s => [s.row + '-' + s.col, s])),
        ss = WorkspaceCore.occupants(p, $('seatScope').value, r.id, $('seatSession').value);
      let html =
        '<div class="room-layout"><div class="platform">讲台</div><div class="seat-grid" style="grid-template-columns:repeat(' +
        r.cols * r.per_desk +
        ',minmax(72px,1fr))">';
      for (let row = 1; row <= r.rows; row++)
        for (let col = 1; col <= r.cols * r.per_desk; col++) {
          const pos = byPosition[row + '-' + col],
            ph = full[row + '-' + col],
            students = pos ? ss[pos.seat] || [] : [],
            state = ph && r.disabled.includes(ph.seat) ? '停用' : '未使用',
            gap = col % r.per_desk === 0 && r.aisles.includes(col / r.per_desk);
          html += `<div data-seat="${pos?.seat || ph?.seat || 0}" data-room-id="${esc(r.id)}" tabindex="${pos ? 0 : -1}" role="group" aria-label="座位 ${pos?.seat || ph?.seat || 0}" class="seat-cell ${gap ? 'aisle' : ''} ${!pos ? 'disabled' : ''} ${students.some(s => s.id === editingSeat) ? 'selected' : ''}"><small>${pos ? `<button class="seat-number" data-label-drag="${pos.seat}" aria-label="座号 ${pos.seat}">${String(pos.seat).padStart(2, '0')} 号</button>` : ph ? String(ph.seat).padStart(2, '0') + ' 号 · ' + state : state}</small>${students.map(s => `<button class="link-button" data-room-seat="${esc(s.id)}" data-student-drag="${esc(s.id)}">${esc(s.name)}${x.mapping[s.id]?.locked ? ' · 锁定' : ''}</button><span>${esc(s.grade)} · ${esc(s.class_name)}</span><small>${esc(s.number || '考号待生成')}</small>`).join('') || '<span>' + (pos ? '空位' : '') + '</span>'}</div>`;
        }
      html += '</div></div>';
      if ($('seatScope').value === 'base' && !$('seatSession').value)
        html += '<p class="muted">固定安排总览可能包含不同时段复用位置的学生。选择日期／时段可查看该场参试人员。</p>';
      else if (x.exam)
        html +=
          '<p class="muted">' +
          esc(x.exam.grade + ' ' + x.exam.subject + (x.exam.special_seating ? ' · 单独安排' : ' · 使用固定座位')) +
          '</p>';
      $('roomPreview').innerHTML = html;
      document.querySelectorAll('[data-room-seat]').forEach(b => (b.onclick = () => editSeat(b.dataset.roomSeat)));
      window.DraggingUI?.render();
      remember();
    }
    function seatEditor(sid) {
      if ($('seatAdjustPanel').classList.contains('dirty') && editingSeat !== sid) {
        requestNavigation(() => seatEditor(sid));
        return;
      }
      const p = view.plan,
        s = p.students.find(s => s.id === sid);
      if (!s) return;
      editingSeat = sid;
      const a = context().mapping[sid] || {};
      $('seatAdjustPanel').classList.remove('hidden', 'dirty');
      document.querySelector('.seat-workspace').classList.add('has-adjustment');
      $('seatAdjustContent').innerHTML =
        `<h3>${esc(s.name)}</h3><p class="muted">${esc(s.grade)} · ${esc(s.class_name)}<br>考号 ${esc(s.number || '待生成')}</p><label>目标考场<select id="adjustRoom">${p.rooms.map(r => option(r.id, r.code + ' · ' + r.name, r.id === a.room_id)).join('')}</select></label><label>目标座号<input id="adjustSeat" type="number" min="1" max="99" value="${a.seat || 1}"></label><label class="check"><input id="swapSeat" type="checkbox">目标有人时交换座位</label><label class="check"><input id="lockSeat" type="checkbox" ${a.locked ? 'checked' : ''}>锁定此位置</label><p id="seatImpact" class="muted"></p><p id="seatAdjustError" class="issue hidden"></p><button class="primary" id="seatAdjustSave">保存座位调整</button>`;
      const update = () => {
        $('seatAdjustPanel').classList.add('dirty');
        const target = view.plan.students.filter(t => {
          const b = context().mapping[t.id];
          return t.id !== sid && b?.room_id === $('adjustRoom').value && b.seat === Number($('adjustSeat').value);
        });
        $('seatImpact').textContent = target.length
          ? '该位置关联 ' +
            target.map(t => t.name + '（' + t.class_name + '）').join('、') +
            '。是否需要交换由实际考试时间和规则检查决定。'
          : '保存时会检查停用位置、同时占座和时间兼容。';
      };
      $('seatAdjustContent')
        .querySelectorAll('input,select')
        .forEach(el => (el.oninput = update));
      bind('seatAdjustSave', saveSeatEditor);
      room();
    }
    async function saveSeatEditor() {
      try {
        await DraggingUI.studentPreview(
          {
            student_id: editingSeat,
            room_id: $('adjustRoom').value,
            seat: Number($('adjustSeat').value),
            exam_id: $('seatScope').value || 'base',
            swap: $('swapSeat').checked,
            locked: $('lockSeat').checked,
          },
          $('seatAdjustPanel')
        );
        return false;
      } catch (e) {
        errorAt('seatAdjustError', e);
        return false;
      }
    }
    function duties() {
      restore();
      const p = view.plan;
      $('avoidSubject').checked = p.settings.avoid_subject;
      $('avoidClass').checked = p.settings.avoid_class;
      $('invigilatorCount').value = p.settings.invigilators;
      $('dutyRuleSummary').textContent =
        `每场 ${p.settings.invigilators} 人` +
        (p.settings.avoid_subject ? ' · 学科回避' : '') +
        (p.settings.avoid_class ? ' · 班级回避' : '');
      fillSelect('dutyDate', [...new Set(view.duties.map(d => d.date))], '全部日期');
      dutyTables();
      selectDutyView(ui.dutyView);
      if (
        editingDuty &&
        !$('teacherAdjustPanel').classList.contains('hidden') &&
        !$('teacherAdjustPanel').classList.contains('dirty')
      ) {
        const d = view.duties.find(d => d.id === editingDuty.d.id);
        if (d && editingDuty.index < d.required) teacherEditor(d, editingDuty.index);
        else $('teacherAdjustPanel').classList.add('hidden');
      }
    }
    function dutyTables() {
      const p = view.plan,
        teachers = Object.fromEntries(p.teachers.map(t => [t.id, t]));
      const query = $('dutySearch').value.toLowerCase(),
        date = $('dutyDate').value;
      const all = view.duties.filter(
        d =>
          (!date || d.date === date) &&
          (!$('dutyMissing').checked || (p.invigilation[d.id] || []).filter(a => a.teacher_id).length < d.required) &&
          [
            p.rooms.find(r => r.id === d.room_id)?.name,
            ...d.subjects,
            ...(p.invigilation[d.id] || []).map(a => teachers[a.teacher_id]?.name),
          ]
            .join(' ')
            .toLowerCase()
            .includes(query)
      );
      const slice = WorkspaceCore.pageRows(all, ui.dutyPage);
      ui.dutyPage = slice.index;
      const missing = view.duties.reduce(
        (n, d) => n + Math.max(0, d.required - (p.invigilation[d.id] || []).filter(a => a.teacher_id).length),
        0
      );
      $('dutySummary').textContent = `共 ${view.duties.length} 场监考 · ${missing} 个位置待安排`;
      $('dutyTable').innerHTML = all.length
        ? table(
            ['日期', '时间', '考场', '科目', '人数', '监考位置'],
            slice.rows.map(d => [
              d.date,
              d.start + '—' + d.end,
              p.rooms.find(r => r.id === d.room_id)?.name,
              d.subjects.join('、'),
              d.student_ids.length,
              raw(
                Array.from({ length: d.required }, (_, i) => {
                  const a = p.invigilation[d.id]?.[i];
                  return `<button class="secondary ${!a?.teacher_id ? 'missing-duty' : ''}" data-duty-id="${esc(d.id)}" data-position="${i}">${esc(teachers[a?.teacher_id]?.name || '待安排')}${a?.locked ? ' · 锁定' : ''}</button>`;
                }).join(' ')
              ),
            ])
          )
        : '<div class="empty-state">' +
          (view.duties.length ? '没有符合条件的场次。' : '先完成日程与学生座位，才能查看监考场次。') +
          '</div>';
      document.querySelectorAll('[data-duty-id]').forEach(
        b =>
          (b.onclick = () =>
            editTeacher(
              view.duties.find(d => d.id === b.dataset.dutyId),
              Number(b.dataset.position)
            ))
      );
      pager('dutyPager', all.length, ui.dutyPage, i => {
        ui.dutyPage = i;
        dutyTables();
      });
      const loads = view.workload.filter(t => t.name.toLowerCase().includes(query)),
        ls = WorkspaceCore.pageRows(loads, ui.workloadPage);
      ui.workloadPage = ls.index;
      $('workloadTable').innerHTML = table(
        ['姓名', '场次', '总时长', '具体安排'],
        ls.rows.map(t => [
          t.name,
          t.count,
          t.minutes + ' 分钟',
          raw(`<button class="link-button" data-teacher-id="${esc(t.teacher_id)}">查看安排</button>`),
        ])
      );
      document
        .querySelectorAll('[data-teacher-id]')
        .forEach(b => (b.onclick = () => teacherDetails(b.dataset.teacherId)));
      pager('workloadPager', loads.length, ui.workloadPage, i => {
        ui.workloadPage = i;
        dutyTables();
      });
      $('shortageList').innerHTML = (p.unfilled_invigilators || [])
        .slice(0, 10)
        .map(
          x =>
            `<div class="warning"><b>待补 ${x.missing} 个位置</b>${(x.reasons || []).map(r => '<p>' + esc(r) + '</p>').join('')}</div>`
        )
        .join('');
      remember();
    }
    function selectDutyView(mode) {
      ui.dutyView = mode;
      $('dutyPanel').classList.toggle('hidden', mode !== 'duties');
      $('teacherPanel').classList.toggle('hidden', mode !== 'teachers');
      document
        .querySelectorAll('[data-duty-view]')
        .forEach(b => b.setAttribute('aria-pressed', String(b.dataset.dutyView === mode)));
      remember();
    }
    function teacherDetails(id) {
      const t = view.plan.teachers.find(t => t.id === id),
        ds = view.duties.filter(d => (view.plan.invigilation[d.id] || []).some(a => a.teacher_id === id));
      form(
        '监考安排 · ' + t.name,
        table(
          ['日期', '时间', '考场', '科目'],
          ds.map(d => [
            d.date,
            d.start + '—' + d.end,
            view.plan.rooms.find(r => r.id === d.room_id)?.name,
            d.subjects.join('、'),
          ])
        ),
        () => {}
      );
      $('formSave').textContent = '知道了';
    }
    async function teacherEditor(d, index) {
      if ($('teacherAdjustPanel').classList.contains('dirty')) {
        requestNavigation(() => teacherEditor(d, index));
        return;
      }
      editingDuty = { d, index };
      const a = view.plan.invigilation[d.id]?.[index] || {};
      $('teacherAdjustPanel').classList.remove('hidden', 'dirty');
      $('teacherAdjustContent').innerHTML =
        `<p>${esc(d.date + ' ' + d.start + '—' + d.end)}<br>${esc(view.plan.rooms.find(r => r.id === d.room_id)?.name)} · 第 ${index + 1} 个位置</p><label>教师<select id="adjustTeacher">${option('', '留空待安排', !a.teacher_id)}${view.plan.teachers.map(t => option(t.id, t.name + ' · ' + t.subjects.join('、'), t.id === a.teacher_id)).join('')}</select></label><label class="check"><input id="lockTeacher" type="checkbox" ${a.locked ? 'checked' : ''}>锁定，自动补排时保留</label><p class="muted">保存时核对时间、不可用时段及任课回避。</p><p id="teacherAdjustError" class="issue hidden"></p><button class="primary" id="teacherAdjustSave">保存监考安排</button>`;
      $('teacherAdjustContent')
        .querySelectorAll('input,select')
        .forEach(el => (el.oninput = () => $('teacherAdjustPanel').classList.add('dirty')));
      bind('teacherAdjustSave', saveTeacherEditor);
      if (view.capabilities?.monitor_candidates) {
        const request = ++candidateRequest;
        $('teacherAdjustSave').disabled = true;
        try {
          const result = await api('monitor_candidates', { duty_id: d.id, index });
          if (request !== candidateRequest || editingDuty?.d.id !== d.id || editingDuty?.index !== index) return;
          const eligible = result.teachers.filter(t => t.eligible),
            blocked = result.teachers.filter(t => !t.eligible);
          $('adjustTeacher').innerHTML =
            option('', '留空待安排', !a.teacher_id) +
            result.teachers
              .map(
                t =>
                  `<option value="${esc(t.id)}" ${t.id === a.teacher_id ? 'selected' : ''} ${t.eligible ? '' : 'disabled'}>${esc(t.name)} · ${t.count} 场 / ${t.minutes} 分钟${t.eligible ? '' : '（不可安排）'}</option>`
              )
              .join('');
          $('teacherAdjustContent').insertAdjacentHTML(
            'beforeend',
            `<p class="muted">可安排 ${eligible.length} 人 · 按工作量从少到多排列</p>${blocked.length ? '<details><summary>不能安排的教师与原因 · ' + blocked.length + ' 人</summary>' + blocked.map(t => '<p class="muted">' + esc(t.name + '：' + t.reasons.map(r => r.message).join('；')) + '</p>').join('') + '</details>' : ''}`
          );
          $('teacherAdjustSave').disabled = false;
        } catch (e) {
          errorAt('teacherAdjustError', e);
        }
      }
    }
    async function saveTeacherEditor() {
      try {
        $('teacherAdjustSave').disabled = true;
        const result = await api('adjust_invigilator', {
          revision: view.plan.revision,
          duty_id: editingDuty.d.id,
          index: editingDuty.index,
          teacher_id: $('adjustTeacher').value,
          locked: $('lockTeacher').checked,
        });
        acceptEdited(result, $('teacherAdjustPanel'), $('teacherAdjustPanel'));
        toast('监考安排已保存。');
        return true;
      } catch (e) {
        errorAt('teacherAdjustError', e);
        return false;
      } finally {
        if ($('teacherAdjustSave')) $('teacherAdjustSave').disabled = false;
      }
    }
    function checks() {
      if (window.IssueUI) IssueUI.render();
    }
    function locateIssue(x) {
      if (x.code === 'monitor_lock_conflict') {
        const d = view.duties.find(d => d.id === x.duty_id);
        if (d && x.index < d.required) {
          page('invigilate');
          teacherEditor(d, x.index);
        } else
          form(
            '解除超出位置的旧锁定',
            `<p>${esc(x.message)}</p><p>教师：${esc((x.teacher_ids || []).map(id => view.plan.teachers.find(t => t.id === id)?.name || id).join('、'))}</p><p>确认后解除这项旧锁定，再重新核对监考安排。</p>`,
            async () => {
              view = await api('monitor_lock_resolve', {
                duty_id: x.duty_id,
                index: x.index,
                action: 'discard',
                revision: view.plan.revision,
              });
              renderAll();
            }
          );
        return;
      }
      if (x.entity) {
        page('data');
        selectKind(x.entity);
        if (x.entity_id) {
          editEntity(x.entity, x.entity_id);
          setTimeout(() => {
            const el = $('edit-' + x.field) || $('room-' + x.field);
            el?.focus();
          }, 0);
        }
        return;
      }
      if (x.code?.includes('number')) {
        openNumberSettings();
        return;
      }
      const teacher = x.teacher_id;
      if (teacher || x.duty_id || /invigil|teacher/.test(x.code || '')) {
        page('invigilate');
        $('dutySearch').value = teacher ? view.plan.teachers.find(t => t.id === teacher)?.name || '' : '';
        dutyTables();
        return;
      }
      const sid = x.student_id || x.student_ids?.[0];
      if (sid || x.room_id || /seat|capacity|mix/.test(x.code || '')) {
        page('seats');
        if (x.exam_id) $('seatScope').value = x.exam_id;
        else $('seatScope').value = 'base';
        if (x.room_id) $('previewRoom').value = x.room_id;
        selectSeatTab('seating');
        seatTable();
        room();
        if (sid) editSeat(sid);
        return;
      }
      if (x.exam_id || /time|schedule|exam/.test(x.code || '')) {
        page('schedule');
        return;
      }
      page('data');
      if (/room/.test(x.code || '')) selectKind('rooms');
      else if (/teacher/.test(x.code || '')) selectKind('teachers');
      else selectKind('students');
    }
    function dirty() {
      return !!document.querySelector(
        '#schedule .unsaved,.adjust-panel.dirty,#seatSettings.dirty,#invigilate details.dirty,#planMenu.dirty,#examGroupsPanel.dirty,#numberDialog.dirty,#printOptions.dirty,#solverSettings.dirty,dialog.dirty'
      );
    }
    function requestNavigation(action) {
      if (dirty()) {
        pendingNavigation = action;
        $('unsavedError').classList.add('hidden');
        if (!$('unsavedDialog').open) $('unsavedDialog').showModal();
        return false;
      }
      performNavigation(action);
      return true;
    }
    function performNavigation(action) {
      try {
        const promise = action?.();
        if (promise?.catch) promise.catch(e => toast(e.message, true));
      } catch (e) {
        toast(e.message, true);
      }
    }
    async function saveDrafts() {
      if ($('bulkDialog').open && $('bulkDialog').classList.contains('dirty')) await BulkUI.apply();
      if ($('printOptions').classList.contains('dirty')) await ExportUI.saveLayouts();
      if ($('formDialog').open && $('formDialog').classList.contains('dirty')) {
        await formAction();
        $('formDialog').classList.remove('dirty');
        $('formDialog').close();
      }
      if ($('roomDialog').open && $('roomDialog').classList.contains('dirty') && !(await saveRoomSettings()))
        return false;
      if ($('roomBatchDialog').open && $('roomBatchDialog').classList.contains('dirty') && !(await saveRoomBatch()))
        return false;
      if ($('seatAdjustPanel').classList.contains('dirty') && !(await saveSeatEditor())) return false;
      if ($('teacherAdjustPanel').classList.contains('dirty') && !(await saveTeacherEditor())) return false;
      const q = clone(view.plan);
      let changed = false;
      if ($('numberDialog').classList.contains('dirty')) {
        const n = numberOptions();
        Object.assign(q.settings, {
          number_rule: n.rule,
          number_prefix: n.prefix,
          number_prefixes: n.prefixes,
          number_width: Number(n.width),
          number_start: Number(n.start),
        });
        changed = true;
      }
      if ($('solverSettings').classList.contains('dirty')) {
        const limit = Number($('solverLimit').value);
        if (!Number.isInteger(limit) || limit < 1 || limit > 300) throw Error('求解时间须为1～300秒。');
        q.settings.time_limit = limit;
        changed = true;
      }
      if ($('examGroupsPanel').classList.contains('dirty')) {
        q.settings.exam_groups = readExamGroups();
        changed = true;
      }
      if ($('planMenu').classList.contains('dirty')) {
        q.name = $('planName').value;
        q.school = $('schoolName').value;
        changed = true;
      }
      document.querySelectorAll('#schedule .unsaved').forEach(row => {
        const b = row.querySelector('[data-save-exam],[data-save-slot]');
        if (b?.dataset.saveExam !== undefined) {
          const i = Number(b.dataset.saveExam),
            w = readExamDraft(i);
          Object.assign(q.exams[i], w, { locked: $('exam-lock-' + i).checked });
          changed = true;
        } else if (b) {
          const i = Number(b.dataset.saveSlot);
          q.settings.slots[i] = readWindow('slot-date-' + i, 'slot-start-' + i, 'slot-end-' + i);
          changed = true;
        }
      });
      if ($('seatSettings').classList.contains('dirty')) {
        Object.assign(q.settings, {
          mode: $('mode').value,
          seed: Number($('seed').value) || 0,
          ...readMixControls(),
          score_field: $('scoreField').value === 'score' ? '' : $('scoreField').value,
        });
        const current = q.rooms.find(r => r.id === $('previewRoom').value);
        if (current && (current.direction !== $('seatDirection').value || current.order !== $('seatOrder').value)) {
          for (const r of q.rooms)
            if ($('layoutScope').value === 'all' || r.id === current.id) {
              r.direction = $('seatDirection').value;
              r.order = $('seatOrder').value;
            }
        }
        changed = true;
      }
      if (document.querySelector('#invigilate details.dirty')) {
        Object.assign(q.settings, {
          invigilators: Number($('invigilatorCount').value),
          avoid_subject: $('avoidSubject').checked,
          avoid_class: $('avoidClass').checked,
        });
        changed = true;
      }
      if (changed) {
        const headerDirty = $('planMenu').classList.contains('dirty');
        try {
          await save(q);
        } catch (e) {
          if (headerDirty) {
            $('planMenu').open = true;
            errorAt('planInfoError', e);
          }
          throw e;
        }
        if (headerDirty) {
          $('planMenu').open = false;
          $('planInfoError').classList.add('hidden');
        }
        document.querySelectorAll('.unsaved,.dirty').forEach(el => el.classList.remove('unsaved', 'dirty'));
      }
      return true;
    }
    function discardDrafts(refresh = true, scope = null) {
      const root = scope || document;
      root.querySelectorAll('dialog.dirty').forEach(el => el.close());
      root.querySelectorAll('.unsaved,.dirty').forEach(el => el.classList.remove('unsaved', 'dirty'));
      root.classList?.remove('dirty', 'unsaved');
      if (!scope || scope.contains($('seatAdjustPanel'))) {
        $('seatAdjustPanel').classList.add('hidden');
        document.querySelector('.seat-workspace').classList.remove('has-adjustment');
        editingSeat = null;
      }
      if (!scope || scope.contains($('teacherAdjustPanel'))) {
        $('teacherAdjustPanel').classList.add('hidden');
        editingDuty = null;
        candidateRequest++;
      }
      window.EditingUI?.forget(scope);
      if (refresh && view?.plan) page(activePage, true);
    }
    function captureDrafts() {
      return [
        ...document.querySelectorAll(
          '#schedule .unsaved input,#seatSettings.dirty input,#seatSettings.dirty select,#invigilate details.dirty input,#planMenu.dirty input,#numberDialog.dirty input,#numberDialog.dirty select,#printOptions.dirty input,#printOptions.dirty select,#solverSettings.dirty input'
        ),
      ]
        .map(el => ({
          id: el.id,
          key: el.dataset.draftKey,
          owner: el.closest('main>.page')?.id,
          value: el.value,
          checked: el.checked,
        }))
        .concat(
          $('seatSettings').classList.contains('dirty')
            ? [{ id: 'mixChoices', mixMode: $('mixChoices').dataset.mode, mixGroups: readCustomMix() }]
            : []
        )
        .concat(
          $('examGroupsPanel').classList.contains('dirty')
            ? [{ id: 'examGroupsPanel', examGroups: readExamGroups(false) }]
            : []
        );
    }
    function restoreDrafts(drafts) {
      for (const d of drafts) {
        const el = d.id ? $(d.id) : $(d.owner)?.querySelector(`[data-draft-key="${d.key}"]`);
        if (d.mixMode) {
          renderCustomMix(d.mixGroups || []);
          selectMixMode(d.mixMode);
          continue;
        }
        if (d.examGroups) {
          renderExamGroups(d.examGroups);
          $('examGroupsPanel').classList.add('dirty');
          continue;
        }
        if (el) {
          el.value = d.value;
          el.checked = d.checked;
          el.closest('tr,.slot-row')?.classList.add('unsaved');
          el.closest(
            '#seatSettings,#numberDialog,#printOptions,#solverSettings,#invigilate details,#planMenu'
          )?.classList.add('dirty');
        }
      }
      updateMixSummary();
    }
    function init() {
      document.querySelectorAll('dialog').forEach(dialog => {
        if (dialog.id === 'unsavedDialog') {
          dialog.addEventListener('cancel', e => e.preventDefault());
          return;
        }
        let backdropDown = false;
        const outside = e => {
          const r = dialog.getBoundingClientRect();
          return (
            e.target === dialog &&
            (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)
          );
        };
        dialog.addEventListener('pointerdown', e => (backdropDown = outside(e)));
        dialog.addEventListener('click', e => {
          if (backdropDown && outside(e)) {
            backdropDown = false;
            requestNavigation(() => {
              if (dialog.id === 'importDialog') $('importCancel').click();
              else dialog.close();
            });
          }
        });
      });
      for (const id of ['formDialog', 'roomDialog', 'roomBatchDialog', 'bulkDialog']) {
        $(id).addEventListener('input', e => {
          if (!e.target.matches('[data-grade-draft-select],#gradeDraftAll')) $(id).classList.add('dirty');
        });
        $(id).addEventListener('cancel', e => {
          if ($(id).classList.contains('dirty')) {
            e.preventDefault();
            requestNavigation(() => $(id).close());
          }
        });
      }
      Appearance.initControls();
      bind('backHome', () => page('home'));
      bind('headerCheckBtn', () => page(view.plan ? 'check' : 'home'));
      bind('previousStep', () => page(stages[Math.max(0, stages.indexOf(activePage) - 1)]));
      bind('nextStep', () => page(stages[Math.min(stages.length - 1, stages.indexOf(activePage) + 1)]));
      document.querySelectorAll('[data-kind]').forEach(b => (b.onclick = () => selectKind(b.dataset.kind)));
      bind('importEntityBtn', () => {
        currentKind = $('entityKind').value;
        if (!requireGrades(currentKind)) return;
        $('fileInput').value = '';
        $('fileInput').click();
      });
      bind('templateEntityBtn', async () => download(await api('template', { kind: $('entityKind').value })));
      bindSearch('entitySearch', () => {
        entityPage = 0;
        entities();
      });
      $('entityGrade').onchange = () => {
        entityPage = 0;
        updateClasses();
        entities();
      };
      $('entityClass').onchange = () => {
        entityPage = 0;
        entities();
      };
      document.querySelectorAll('[data-seat-tab]').forEach(
        b =>
          (b.onclick = () => {
            if (b.dataset.seatTab === 'numbering') requestNavigation(openNumberSettings);
            else requestNavigation(() => selectSeatTab('seating'));
          })
      );
      document
        .querySelectorAll('[data-seat-view]')
        .forEach(b => (b.onclick = () => selectSeatView(b.dataset.seatView)));
      $('mode').onchange = modeVisibility;
      $('seatDirection').onchange = route;
      $('seatOrder').onchange = route;
      $('seatSettings')
        .querySelectorAll('input,select')
        .forEach(el =>
          el.addEventListener('input', () => {
            if (el.closest('#solverSettings')) $('solverSettings').classList.add('dirty');
            else if (el.id !== 'mixPresetSelect') $('seatSettings').classList.add('dirty');
          })
        );
      $('seatScope').onchange = () => {
        const wanted = $('seatScope').value,
          old = memory.get(view.plan.id)?.data.seatScope || 'base';
        $('seatScope').value = old;
        requestNavigation(() => {
          $('seatScope').value = wanted;
          $('seatAdjustPanel').classList.add('hidden');
          editingSeat = null;
          document.querySelector('.seat-workspace').classList.remove('has-adjustment');
          seatPage = 0;
          $('seatSessionRow').classList.toggle('hidden', $('seatScope').value !== 'base');
          seatTable();
          room();
          remember();
        });
      };
      $('seatSession').onchange = () => {
        room();
        remember();
      };
      bindSearch('seatSearch', () => {
        seatPage = 0;
        seatTable();
      });
      $('seatUnassigned').onchange = () => {
        seatPage = 0;
        seatTable();
      };
      bind('seatAdjustClose', () =>
        requestNavigation(() => {
          $('seatAdjustPanel').classList.add('hidden');
          document.querySelector('.seat-workspace').classList.remove('has-adjustment');
          editingSeat = null;
          room();
        })
      );
      document
        .querySelectorAll('[data-duty-view]')
        .forEach(b => (b.onclick = () => selectDutyView(b.dataset.dutyView)));
      bindSearch('dutySearch', () => {
        ui.dutyPage = 0;
        ui.workloadPage = 0;
        dutyTables();
      });
      $('dutyDate').onchange = $('dutyMissing').onchange = () => {
        ui.dutyPage = 0;
        dutyTables();
      };
      document
        .querySelector('#invigilate details')
        .querySelectorAll('input')
        .forEach(el => (el.oninput = () => document.querySelector('#invigilate details').classList.add('dirty')));
      bind('teacherAdjustClose', () => requestNavigation(() => $('teacherAdjustPanel').classList.add('hidden')));
      bind('keepEditing', () => $('unsavedDialog').close());
      bind('discardChanges', () => {
        discardDrafts();
        $('unsavedDialog').close();
        const action = pendingNavigation;
        pendingNavigation = null;
        performNavigation(action);
      });
      bind('saveAndContinue', async () => {
        try {
          if (await saveDrafts()) {
            $('unsavedDialog').close();
            const action = pendingNavigation;
            pendingNavigation = null;
            performNavigation(action);
          }
        } catch (e) {
          errorAt('unsavedError', e);
        }
      });
      window.addEventListener('beforeunload', e => {
        if (dirty()) {
          e.preventDefault();
          e.returnValue = '';
        }
      });
      document.addEventListener('keydown', e => {
        if (e.isComposing) return;
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
          e.preventDefault();
          if (dirty())
            saveDrafts()
              .then(saved => {
                if (saved !== false) toast('修改已保存。');
              })
              .catch(err => toast(err.message, true));
          return;
        }
        if (e.key === 'Enter' && e.target.tagName === 'INPUT' && !e.metaKey && !e.ctrlKey) {
          const dialog = e.target.closest('dialog');
          const id = dialog
            ? { formDialog: 'formSave', roomDialog: 'roomApply', roomBatchDialog: 'batchPreviewBtn' }[dialog.id]
            : e.target.closest('#seatAdjustPanel')
              ? 'seatAdjustSave'
              : e.target.closest('#teacherAdjustPanel')
                ? 'teacherAdjustSave'
                : null;
          if (id) {
            e.preventDefault();
            $(id)?.click();
            return;
          }
        }
        if (e.key === 'Escape' && !document.querySelector('dialog[open]')) {
          if (!$('seatAdjustPanel').classList.contains('hidden') && activePage === 'seats')
            $('seatAdjustClose').click();
          else if (!$('teacherAdjustPanel').classList.contains('hidden') && activePage === 'invigilate')
            $('teacherAdjustClose').click();
        }
        if (
          e.target.matches('.section-tabs [role=tab]') &&
          ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)
        ) {
          e.preventDefault();
          const tabs = [...e.target.parentElement.querySelectorAll('[role=tab]')],
            i = tabs.indexOf(e.target),
            next =
              e.key === 'Home'
                ? 0
                : e.key === 'End'
                  ? tabs.length - 1
                  : (i + (e.key === 'ArrowLeft' ? -1 : 1) + tabs.length) % tabs.length;
          tabs[next].click();
          tabs[next].focus();
        }
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'f') {
          const id = { data: 'entitySearch', seats: 'seatSearch', invigilate: 'dutySearch' }[activePage];
          if (id) {
            e.preventDefault();
            if (activePage === 'seats') selectSeatView('table');
            $(id).focus();
          }
        }
      });
    }
    return {
      init,
      restoreScrolls,
      saveDrafts,
      dirty,
      activatePlan,
      remember,
      restore,
      header,
      overview,
      data,
      entities,
      seats,
      seatTable,
      room,
      seatEditor,
      duties,
      teacherEditor,
      checks,
      locateIssue,
      context,
      selectKind,
      selectSeatTab,
      route,
      requestNavigation,
      captureDrafts,
      restoreDrafts,
      discardDrafts,
    };
  })();
  Workspace.init();
}
