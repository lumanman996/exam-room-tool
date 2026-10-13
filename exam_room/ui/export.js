'use strict';
const ExportCore = (() => {
  const defaults = {
    paper: 'A4',
    orientation: 'landscape',
    columns: 1,
    font_size: 11,
    line_height: 1.4,
    margins: { top: 13, right: 13, bottom: 13, left: 13 },
    color: 'mono',
    page_break: 'flow',
    repeat_headers: true,
  };
  function normalizeLayout(value = {}) {
    const x = {
      ...defaults,
      ...value,
      margins: { ...defaults.margins, ...value.margins },
      field_order: [...(value.field_order || [])],
      column_widths: { ...(value.column_widths || {}) },
    };
    if (!['A4', 'A3'].includes(x.paper) || !['portrait', 'landscape'].includes(x.orientation))
      throw Error('请选择有效纸张和方向。');
    if (!Number.isInteger(Number(x.columns)) || x.columns < 1 || x.columns > 3) throw Error('每行考场栏数须为 1～3。');
    x.columns = Number(x.columns);
    x.font_size = Number(x.font_size);
    x.line_height = Number(x.line_height);
    if (!Number.isFinite(x.font_size) || x.font_size < 9 || x.font_size > 18) throw Error('打印字号须为 9～18 pt。');
    if (!Number.isFinite(x.line_height) || x.line_height < 1.2 || x.line_height > 2) throw Error('行距须为 1.2～2。');
    for (const key of ['top', 'right', 'bottom', 'left']) {
      x.margins[key] = Number(x.margins[key]);
      if (!Number.isFinite(x.margins[key]) || x.margins[key] < 5 || x.margins[key] > 40)
        throw Error('页边距须为 5～40 mm。');
    }
    for (const [field, w] of Object.entries(x.column_widths)) {
      const n = Number(w);
      if (!Number.isFinite(n) || n <= 0) throw Error(field + '的列宽须大于 0。');
      x.column_widths[field] = n;
    }
    if (!['mono', 'color'].includes(x.color) || !['room', 'flow'].includes(x.page_break))
      throw Error('请选择有效打印样式。');
    return x;
  }
  function chooseSections(available, chosen) {
    return chosen === null ? Object.keys(available).slice(0, 6) : chosen.filter(k => Object.hasOwn(available, k));
  }
  function exportRequest(v, format, sections, draft, layouts = {}, scope = { mode: 'fixed' }) {
    const body = { format, sections, draft, revision: v.plan.revision };
    if (v.capabilities?.report_layouts) {
      body.layouts = Object.fromEntries(Object.entries(layouts).map(([k, x]) => [k, normalizeLayout(x)]));
      body.scope = scope;
    }
    return body;
  }
  function relevantErrors(v, chosen) {
    const mapping = v.export_stages;
    if (!mapping || !v.validation.stages || chosen.some(k => !mapping[k])) return v.validation.errors;
    const stages = new Set(chosen.flatMap(k => mapping[k]));
    return v.validation.errors.filter(x => stages.has(x.stage));
  }
  return { defaults, normalizeLayout, chooseSections, exportRequest, relevantErrors };
})();
if (typeof module !== 'undefined') module.exports = ExportCore;
if (typeof document !== 'undefined')
  window.ExportUI = (() => {
    const state = new Map();
    let activeJob = null,
      previewSerial = 0,
      previewData = null,
      previewIndex = 0;
    const groups = [
      ['教务汇总', ['room_students', 'student_details', 'schedule', 'students', 'rooms', 'invigilation', 'workload']],
      ['学生通知', ['classes', 'personal', 'tickets']],
      ['考场布置', ['rosters', 'seating', 'doors', 'labels', 'signins']],
      ['监考教师', ['teacher_personal']],
    ];
    function current() {
      const id = view.plan.id;
      if (!state.has(id))
        state.set(id, {
          chosen: null,
          layouts: { ...clone(view.report_layout_defaults || {}), ...clone(view.plan.report_layouts || {}) },
          draft: false,
          groupOpen: {},
          layoutKey: 'room_students',
          scope: { mode: 'fixed' },
        });
      return state.get(id);
    }
    function layoutCap() {
      return !!view.capabilities?.report_layouts;
    }
    function asyncCap() {
      return !!(view.capabilities?.async_export || view.capabilities?.export_async);
    }
    function render() {
      const st = current(),
        sections = view.sections;
      if (st.chosen === null)
        st.chosen = Object.hasOwn(sections, 'room_students')
          ? ['room_students', 'schedule', 'seating']
          : ExportCore.chooseSections(sections, null);
      st.chosen = ExportCore.chooseSections(sections, st.chosen);
      $('exportChecks').innerHTML = groups
        .map(([label, keys]) => {
          const available = keys.filter(k => Object.hasOwn(sections, k));
          return available.length
            ? `<details class="material-group" data-material-group="${label}" ${st.groupOpen[label] ? 'open' : ''}><summary>${label}<span data-group-count>已选 ${available.filter(k => st.chosen.includes(k)).length} 项</span></summary><fieldset><legend class="sr-only">${label}</legend>${available.map(k => `<label class="check"><input type="checkbox" data-export="${k}" ${st.chosen.includes(k) ? 'checked' : ''}>${esc(sections[k])}</label>`).join('')}</fieldset></details>`
            : '';
        })
        .join('');
      document
        .querySelectorAll('[data-material-group]')
        .forEach(g => (g.ontoggle = () => (st.groupOpen[g.dataset.materialGroup] = g.open)));
      $('draftExport').checked = st.draft;
      document.querySelectorAll('[data-export]').forEach(
        el =>
          (el.onchange = () => {
            st.chosen = selected();
            document
              .querySelectorAll('[data-material-group]')
              .forEach(
                g =>
                  (g.querySelector('[data-group-count]').textContent =
                    '已选 ' + g.querySelectorAll('input:checked').length + ' 项')
              );
            invalidate();
            gate();
          })
      );
      $('draftExport').onchange = () => {
        st.draft = $('draftExport').checked;
        invalidate();
        gate();
      };
      bind('exportSelectAll', () => {
        st.chosen = Object.keys(sections);
        render();
      });
      $('printOptions').classList.toggle('hidden', !layoutCap());
      if (layoutCap()) renderOptions();
      if (st.lastResult && st.lastResult.kind !== 'preview') {
        $('exportStatus').innerHTML =
          '<p class="muted">上次生成：' +
          esc(st.lastResult.name) +
          ' · 方案版本 ' +
          esc(st.lastResult.snapshot_revision ?? '—') +
          '</p><button class="secondary" id="lastExport">保存／打开上次文件</button>';
        bind('lastExport', () => download(st.lastResult));
      }
      gate();
    }
    function gate() {
      const st = current(),
        enabled = view.license.canExport,
        errors = ExportCore.relevantErrors(view, st.chosen);
      const allowed = enabled && st.chosen.length > 0 && (st.draft || !errors.length);
      for (const id of ['previewBtn', 'exportXlsx', 'exportPdf']) $(id).disabled = !allowed || !!activeJob;
      $('exportGate').innerHTML = !enabled
        ? '<div class="warning">试用已到期，编排和保存仍可使用。激活后可导出与打印。</div>'
        : !st.chosen.length
          ? '<div class="warning">请至少选择一种材料。</div>'
          : errors.length
            ? `<div class="warning">所选材料有 ${errors.length} 项必须处理的问题。${st.draft ? '将导出带“草稿”标识的材料。' : '处理后正式导出，或选择草稿。'} <button class="secondary" id="exportFix">去处理</button></div>`
            : '<div class="ok">所选材料的硬性检查通过，可以正式导出。核对提示请按学校要求确认。</div>';
      bind('exportFix', () => page('check'));
    }
    function renderOptions() {
      const st = current();
      if (!Object.hasOwn(view.sections, st.layoutKey)) st.layoutKey = Object.keys(view.sections)[0];
      const l = ExportCore.normalizeLayout(
        st.layouts[st.layoutKey] || view.report_layout_defaults?.[st.layoutKey] || {}
      );
      st.layouts[st.layoutKey] = l;
      $('printOptions').innerHTML =
        `<div class="section-head"><h2>调整版式</h2><button class="link-button" id="printReset">恢复本材料默认</button></div><label>材料<select id="printSection">${Object.entries(
          view.sections
        )
          .map(([k, v]) => option(k, v, k === st.layoutKey))
          .join(
            ''
          )}</select></label><label>纸张<select id="printPaper">${option('A4', 'A4', l.paper === 'A4')}${option('A3', 'A3（打印机需支持）', l.paper === 'A3')}</select></label><label>方向<select id="printOrientation">${option('landscape', '横向', l.orientation === 'landscape')}${option('portrait', '纵向', l.orientation === 'portrait')}</select></label><label>${st.layoutKey === 'room_students' ? '每行考场数' : '每行材料块数'}<select id="printColumns">${[1, 2, 3].map(n => option(n, n + ' 个', l.columns === n)).join('')}</select></label><label>打印字号（pt）<input id="printFont" type="number" min="9" max="18" value="${l.font_size}"></label><label>行距<input id="printLineHeight" type="number" min="1.2" max="2" step="0.1" value="${l.line_height}"></label><label>打印配色<select id="printColor">${option('mono', '黑白省墨', l.color === 'mono')}${option('color', '靛蓝彩色', l.color === 'color')}</select></label><label>考场分页<select id="printBreak">${option('flow', '连续分块', l.page_break === 'flow')}${option('room', '每个考场另起页', l.page_break === 'room')}</select></label><details><summary>页边距、字段和列宽</summary>${[
          ['top', '上'],
          ['right', '右'],
          ['bottom', '下'],
          ['left', '左'],
        ]
          .map(
            ([k, label]) =>
              `<label>${label}页边距（mm）<input id="print-margin-${k}" data-margin="${k}" type="number" min="5" max="40" value="${l.margins[k]}"></label>`
          )
          .join(
            ''
          )}${fieldControls(st.layoutKey, l)}</details><label>编排范围<select id="printScope"><option value="fixed" ${st.scope.mode === 'fixed' ? 'selected' : ''}>固定编排总览</option><option value="exam" ${st.scope.mode === 'exam' ? 'selected' : ''}>科目有效座位</option></select></label><label id="printExamRow" class="${st.scope.mode === 'exam' ? '' : 'hidden'}">科目<select id="printExam">${option('', '全部科目', !st.scope.exam_ids?.length)}${view.plan.exams.map(e => option(e.id, e.grade + ' ' + e.subject, st.scope.exam_ids?.[0] === e.id)).join('')}</select></label><label>考场范围<select id="printRoom">${option('', '全部考场', !st.scope.room_ids?.length)}${view.plan.rooms.map(r => option(r.id, r.code + ' · ' + r.name, st.scope.room_ids?.[0] === r.id)).join('')}</select></label><label>年级范围<select id="printGrade">${option('', '全部年级', !st.scope.grades?.length)}${formalGrades(
          view.plan
        )
          .map(g => option(g, g, st.scope.grades?.[0] === g))
          .join(
            ''
          )}</select></label><p class="muted">显示字号与打印字号分别设置。改变版式不会移动学生。</p><p id="printError" class="issue hidden"></p><button class="secondary" id="printSave">保存本方案版式</button>`;
      bindFieldControls();
      $('printSection').onchange = () => {
        try {
          readOptions();
          st.layoutKey = $('printSection').value;
          renderOptions();
          $('printOptions').classList.add('dirty');
          window.EditingUI?.changed(document.getElementById('export'));
        } catch (e) {
          errorAt('printError', e);
        }
      };
      bind('printReset', () => {
        st.layouts[st.layoutKey] = clone(view.report_layout_defaults?.[st.layoutKey] || ExportCore.defaults);
        renderOptions();
        $('printOptions').classList.add('dirty');
        window.EditingUI?.changed(document.getElementById('export'));
        invalidate();
      });
      $('printScope').onchange = () => {
        $('printExamRow').classList.toggle('hidden', $('printScope').value !== 'exam');
        invalidate();
      };
      $('printOptions')
        .querySelectorAll('input,select')
        .forEach(el => el.addEventListener('input', invalidate));
      bind('printSave', async () => {
        try {
          await saveLayouts();
        } catch (e) {
          errorAt('printError', e);
        }
      });
    }
    function fieldControls(key, l) {
      const available = view.report_layout_defaults?.[key]?.field_order || [],
        order = [...l.field_order, ...available.filter(k => !l.field_order.includes(k))];
      if (!available.length) return '<p class="muted">座次图按实际桌椅位置绘制。</p>';
      const required = available.includes('座号') && available.includes('考号') ? ['座号', '考号', '姓名'] : [];
      return `<div class="field-order"><p class="muted">勾选需要的字段，用箭头调整顺序。列宽留空表示自动分配。</p>${order.map((f, i) => `<div class="print-field-row" data-field="${esc(f)}"><label class="check"><input type="checkbox" id="print-field-${esc(f)}" data-print-field ${l.field_order.includes(f) ? 'checked' : ''} ${required.includes(f) ? 'disabled' : ''}>${esc(f)}</label><input type="number" id="print-width-${esc(f)}" data-print-width value="${l.column_widths[f] || ''}" min="1" max="400" placeholder="自动" aria-label="${esc(f)}列宽（毫米）"><button class="link-button" data-move-field="-1" ${i === 0 ? 'disabled' : ''} aria-label="上移${esc(f)}">↑</button><button class="link-button" data-move-field="1" ${i === order.length - 1 ? 'disabled' : ''} aria-label="下移${esc(f)}">↓</button></div>`).join('')}<small>列宽单位：毫米；学生材料须保留座号、考号、姓名。</small></div>`;
    }
    function bindFieldControls() {
      document.querySelectorAll('[data-move-field]').forEach(
        b =>
          (b.onclick = () => {
            const row = b.closest('[data-field]'),
              next = Number(b.dataset.moveField) < 0 ? row.previousElementSibling : row.nextElementSibling;
            if (!next?.dataset.field) return;
            if (Number(b.dataset.moveField) < 0) row.parentNode.insertBefore(row, next);
            else row.parentNode.insertBefore(next, row);
            document.querySelectorAll('[data-field]').forEach((r, i, rows) => {
              r.querySelector('[data-move-field="-1"]').disabled = i === 0;
              r.querySelector('[data-move-field="1"]').disabled = i === rows.length - 1;
            });
            $('printOptions').classList.add('dirty');
            window.EditingUI?.changed(document.getElementById('export'));
            invalidate();
          })
      );
    }
    function readOptions() {
      if (!layoutCap()) return;
      const st = current(),
        old = st.layouts[st.layoutKey] || {},
        widths = {},
        fields = [];
      document.querySelectorAll('[data-field]').forEach(row => {
        if (!row.querySelector('[data-print-field]').checked) return;
        fields.push(row.dataset.field);
        const input = row.querySelector('[data-print-width]');
        if (input.value) {
          const n = Number(input.value);
          if (!Number.isFinite(n) || n <= 0 || n > 400) throw Error(row.dataset.field + '的列宽须为 1～400 毫米。');
          widths[row.dataset.field] = n;
        }
      });
      if (view.report_layout_defaults?.[st.layoutKey]?.field_order.length && !fields.length)
        throw Error('请至少保留一个打印字段。');
      const layout = {
        ...old,
        paper: $('printPaper').value,
        orientation: $('printOrientation').value,
        columns: Number($('printColumns').value),
        font_size: Number($('printFont').value),
        line_height: Number($('printLineHeight').value),
        color: $('printColor').value,
        page_break: $('printBreak').value,
        margins: Object.fromEntries(
          [...document.querySelectorAll('[data-margin]')].map(el => [el.dataset.margin, Number(el.value)])
        ),
        field_order: fields,
        column_widths: widths,
      };
      st.layouts[st.layoutKey] = ExportCore.normalizeLayout(layout);
      st.scope = {
        mode: $('printScope').value,
        exam_ids: $('printExam').value ? [$('printExam').value] : [],
        room_ids: $('printRoom').value ? [$('printRoom').value] : [],
        grades: $('printGrade').value ? [$('printGrade').value] : [],
      };
    }
    function invalidate() {
      previewSerial++;
      previewData = null;
      $('printPreview').classList.add('hidden');
      $('previewEmpty').classList.remove('hidden');
      $('previewEmpty').textContent = '材料或版式已改变，请更新打印预览。';
      $('previewPager').innerHTML = '';
    }
    function showPreview(result) {
      const html = result.html;
      if (!html) throw Error('预览未返回页面内容，请重新生成。');
      const parsed = new DOMParser().parseFromString(html, 'text/html'),
        pages = [...parsed.querySelectorAll('section.page')];
      previewData = { html, head: parsed.head.innerHTML, pages: pages.map(p => p.outerHTML), meta: result };
      previewIndex = 0;
      renderPreviewPage();
    }
    function renderPreviewPage() {
      const data = previewData;
      if (!data) return;
      const total = data.pages.length || 1;
      $('previewEmpty').classList.add('hidden');
      $('printPreview').classList.remove('hidden');
      const pageHtml = data.pages.length
        ? `<!doctype html><html lang="zh-CN"><head>${data.head}<style>body{background:#fff}.page{margin:0 auto!important;box-shadow:none!important}</style></head><body>${data.pages[previewIndex]}</body></html>`
        : data.html;
      $('printPreview').onload = () => {
        const frame = $('printPreview'),
          doc = frame.contentDocument,
          pageEl = doc?.querySelector('section.page');
        if (pageEl) {
          const width = pageEl.getBoundingClientRect().width,
            scale = Math.min(1, (frame.clientWidth - 24) / width);
          doc.body.style.zoom = String(scale);
          frame.style.height = pageEl.getBoundingClientRect().height + 24 + 'px';
        }
      };
      $('printPreview').srcdoc = pageHtml;
      $('previewMeta').textContent =
        (data.meta.stale ? '基于先前保存版本 · ' : '') +
        (previewIndex + 1) +
        ' / ' +
        total +
        (data.meta.page_count ? ' 页' : ' 个材料页面');
      $('previewPager').innerHTML =
        `<button class="secondary" id="printPrev" ${previewIndex === 0 ? 'disabled' : ''}>上一页</button><span>第 ${previewIndex + 1} / ${total} ${data.meta.page_count ? '页' : '个材料页面'}</span><button class="secondary" id="printNext" ${previewIndex + 1 >= total ? 'disabled' : ''}>下一页</button>`;
      bind('printPrev', () => {
        previewIndex--;
        renderPreviewPage();
      });
      bind('printNext', () => {
        previewIndex++;
        renderPreviewPage();
      });
    }
    async function generate(format) {
      if (activeJob) return;
      const st = current();
      try {
        readOptions();
        const request = ExportCore.exportRequest(view, format, st.chosen, st.draft, st.layouts, st.scope);
        if (!st.chosen.length) throw Error('请至少选择一种材料。');
        const serial = ++previewSerial,
          planId = view.plan.id,
          revision = view.plan.revision,
          began = Date.now();
        activeJob = { format, id: null };
        gate();
        $('exportStatus').textContent = '正在生成材料，请稍候…';
        let result;
        if (asyncCap()) {
          const task = await api('export_start', request);
          activeJob.id = task.id;
          $('exportStatus').innerHTML =
            '<p id="exportProgress">正在后台生成材料…</p><button class="secondary" id="cancelExport">取消生成</button>';
          bind('cancelExport', async () => {
            await api('export_cancel', { id: task.id });
            $('exportStatus').textContent = '正在取消，请稍候…';
          });
          while (true) {
            await new Promise(resolve => setTimeout(resolve, 500));
            const x = await api('export_status', { id: task.id });
            if ($('exportProgress'))
              $('exportProgress').textContent =
                (x.message || '正在生成材料…') + ' · 已用时 ' + Math.floor((Date.now() - began) / 1000) + ' 秒';
            if (x.state === 'done') {
              result = x.result;
              break;
            }
            if (x.state === 'error' || x.state === 'cancelled')
              throw Error(
                x.message || x.error || (x.state === 'cancelled' ? '已取消生成，原方案保持不变。' : '材料生成失败。')
              );
          }
        } else result = await api('export', request);
        if (format !== 'preview') st.lastResult = result;
        if (view.plan?.id !== planId) {
          toast('先前考试的材料已生成。请回到该考试查看。');
          return;
        }
        if (format === 'preview') {
          if (serial !== previewSerial || view.plan.revision !== revision) {
            $('exportStatus').textContent = '生成期间材料或版式已改变，请重新预览。';
            return;
          }
          showPreview(result);
          $('exportStatus').textContent = '预览已更新，请核对考号、范围与版式。';
        } else {
          download(result);
          if (result.stale || view.plan.revision !== revision)
            toast('文件基于开始导出时的方案，期间有新修改，请核对版本。', true);
        }
      } catch (e) {
        $('exportStatus').innerHTML = '<div class="issue">' + esc(e.message) + '</div>';
      } finally {
        activeJob = null;
        if (activePage === 'export') gate();
      }
    }
    bind('previewBtn', () => generate('preview'));
    async function saveLayouts() {
      readOptions();
      const st = current(),
        result = await api('report_layout_save', { layouts: st.layouts, revision: view.plan.revision });
      $('printOptions').classList.remove('dirty');
      window.EditingUI?.committed($('printSave'));
      view = result;
      renderAll();
      toast('版式已保存。');
    }
    function restoreSaved() {
      if (!view?.plan) return;
      const st = current();
      st.layouts = { ...clone(view.report_layout_defaults || {}), ...clone(view.plan.report_layouts || {}) };
      if (activePage === 'export') renderOptions();
      invalidate();
    }
    function captureDraft() {
      const st = current();
      return { layouts: clone(st.layouts), layoutKey: st.layoutKey, scope: clone(st.scope) };
    }
    function restoreDraft(draft) {
      Object.assign(current(), clone(draft));
      renderOptions();
      invalidate();
    }
    return { render, generate, invalidate, saveLayouts, restoreSaved, captureDraft, restoreDraft };
  })();
