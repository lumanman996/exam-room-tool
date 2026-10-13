'use strict';
// Detached draft state and small pure helpers are shared by UI and behaviour tests.
const Editing = (() => {
  const copy = value => JSON.parse(JSON.stringify(value));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  function commitFieldSubset(previous, latest, ids) {
    // Side panels may add controls after the page's original snapshot.
    const selected = new Set(ids),
      key = f => f.id || f.key,
      fields = new Map(previous.map(f => [key(f), f]));
    for (const f of latest) if (selected.has(f.id)) fields.set(key(f), f);
    const order = new Map(latest.map((f, i) => [key(f), i]));
    return [...fields.values()].sort((a, b) => (order.get(key(a)) ?? Infinity) - (order.get(key(b)) ?? Infinity));
  }
  function start(initial) {
    let saved = copy(initial),
      value = copy(initial),
      history = [];
    return {
      get value() {
        return value;
      },
      get saved() {
        return copy(saved);
      },
      get dirty() {
        return !same(value, saved);
      },
      get canUndo() {
        return history.length > 0;
      },
      replace(next) {
        if (!same(value, next)) {
          history.push(copy(value));
          history = history.slice(-50);
          value = copy(next);
        }
        return value;
      },
      set(key, next) {
        return this.replace({ ...value, [key]: copy(next) });
      },
      undo() {
        if (history.length) value = history.pop();
        return value;
      },
      rebase(fn) {
        saved = copy(fn(copy(saved)));
        value = copy(fn(copy(value)));
        history = history.map(h => copy(fn(copy(h))));
        history = history.filter((h, i) => !i || !same(h, history[i - 1]));
        while (history.length && same(history.at(-1), value)) history.pop();
        return value;
      },
      restore(latest = saved) {
        saved = copy(latest);
        value = copy(latest);
        history = [];
        return value;
      },
      async submit(fn) {
        const result = await fn(copy(value));
        this.restore(value);
        return result;
      },
    };
  }
  function selection() {
    const chosen = new Set();
    return {
      get ids() {
        return [...chosen];
      },
      toggle(id, on) {
        on ? chosen.add(id) : chosen.delete(id);
      },
      all(ids, on) {
        ids.forEach(id => this.toggle(id, on));
      },
      prune(ids) {
        const valid = new Set(ids);
        for (const id of chosen) if (!valid.has(id)) chosen.delete(id);
      },
    };
  }
  function previewTicket(options, revision) {
    const request = copy(options);
    return {
      request,
      revision,
      valid(next, rev) {
        return rev === revision && same(request, next);
      },
    };
  }
  function examDuration(begin, end, planned) {
    const minutes = v => {
      const m = String(v)
        .trim()
        .replace(/：/g, ':')
        .match(/^(\d{1,2}):(\d{2})$/);
      if (!m || +m[1] > 23 || +m[2] > 59) throw Error('时间请填写为 08:30 这样的格式。');
      return +m[1] * 60 + +m[2];
    };
    if (begin && end) {
      const n = minutes(end) - minutes(begin);
      if (n <= 0) throw Error('结束时间须晚于开始时间。');
      return { minutes: n, readonly: true };
    }
    const n = Number(planned);
    if (!Number.isInteger(n) || n < 1 || n > 1440) throw Error('计划时长须为 1～1440 的整数分钟。');
    return { minutes: n, readonly: false };
  }
  function validateCatalog(rows) {
    const names = new Set();
    return rows.map(row => {
      const name = String(row.name || '').trim();
      if (!name || names.has(name)) throw Error('科目名称不能为空或重复。');
      names.add(name);
      return { name, duration: examDuration('', '', row.duration).minutes };
    });
  }
  function subjectDuration(catalog, name) {
    return catalog.find(row => row.name === name)?.duration || 90;
  }
  async function continueStep(save, next) {
    if ((await save()) !== false) await next();
  }
  function groupIssues(issues) {
    const groups = new Map();
    for (const item of issues) {
      const key = [item.code, item.entity || '', item.field || ''].join('|');
      if (!groups.has(key))
        groups.set(key, {
          key,
          code: item.code,
          entity: item.entity,
          field: item.field,
          message: item.message,
          items: [],
        });
      groups.get(key).items.push(item);
    }
    return [...groups.values()];
  }
  function stageReady(view, page) {
    const p = view?.plan;
    if (!p) return false;
    const clean = stage => !view.validation?.stages?.[stage]?.errors?.length;
    if (page === 'data')
      return !!(
        p.grades?.length &&
        ['students', 'rooms', 'teachers', 'exams'].every(k => p[k]?.length) &&
        clean('data')
      );
    if (page === 'schedule')
      return !!(p.exams?.length && p.exams.every(e => e.date && e.start && e.end) && clean('schedule'));
    if (page === 'seats')
      return !!(
        p.students?.length &&
        p.students.every(s => p.seats?.base?.[s.id] && s.number) &&
        clean('seats') &&
        clean('numbers')
      );
    if (page === 'invigilate')
      return !!(
        view.duties?.length &&
        view.duties.every(d => (p.invigilation?.[d.id] || []).filter(a => a.teacher_id).length >= d.required) &&
        clean('monitors')
      );
    if (page === 'check') return !view.validation?.errors?.length && !p.stale?.length && !p.stale_seats?.length;
    return false;
  }
  function gradeAssociations(plan, grade) {
    const students = plan.students.filter(s => s.grade === grade),
      exams = plan.exams.filter(e => e.grade === grade),
      groups = (plan.settings.mix_groups || []).filter(g => g.includes(grade)),
      presets = (plan.settings.mix_presets || []).filter(p => p.groups.some(g => g.includes(grade)));
    return { students, exams, groups, presets, counts: [students.length, exams.length, groups.length, presets.length] };
  }
  return {
    start,
    commitFieldSubset,
    selection,
    previewTicket,
    examDuration,
    subjectDuration,
    validateCatalog,
    continueStep,
    groupIssues,
    gradeAssociations,
    stageReady,
  };
})();
if (typeof module !== 'undefined') module.exports = Editing;

if (typeof document !== 'undefined') {
  window.EditingUI = (() => {
    const records = new Map(),
      loaders = new WeakMap();
    let order = 0,
      paused = false,
      planId = null;
    const excluded =
      '#entitySearch,#entityKind,#entityGrade,#entityClass,#seatScope,#seatSession,#previewRoom,#labelFirst,#labelSecond,#seatSearch,#seatUnassigned,#dutySearch,#dutyDate,#dutyMissing,#mixPresetSelect,[data-select-entity],[data-select-grade],[data-select-all],[data-grade-draft-select],#gradeDraftAll,[data-export],#draftExport,#printSection,input[type=file]';
    function owner(el) {
      return el?.closest('dialog:not(#unsavedDialog),#planMenu,main>.page');
    }
    function controls(root) {
      return [...root.querySelectorAll('input,select,textarea')].filter(el => !el.matches(excluded));
    }
    function snapshot(root) {
      const fields = controls(root).map((el, i) => {
        if (!el.id && !el.dataset.draftKey) el.dataset.draftKey = 'field-' + i;
        return { id: el.id, key: el.dataset.draftKey, value: el.value, checked: el.checked };
      });
      const data = { fields };
      if (root.id === 'formDialog') data.html = $('formContent').innerHTML;
      if (root.id === 'roomDialog') data.disabled = roomDisabled.slice();
      if (root.querySelector('#mixChoices')) {
        data.mixMode = $('mixChoices').dataset.mode;
        data.mixGroups = readCustomMix();
      }
      if (root.querySelector('#printOptions')) {
        data.printDraft = window.ExportUI?.captureDraft();
        data.printOrder = [...root.querySelectorAll('[data-field]')].map(el => el.dataset.field);
      }
      if (root.querySelector('#examGroupsList')) data.examGroups = readExamGroups(false);
      return data;
    }
    function watch(root, reset = false) {
      if (!root) return;
      if (reset || !records.has(root)) records.set(root, { draft: Editing.start(snapshot(root)), order: ++order });
    }
    function changed(root) {
      if (paused || !root) return;
      watch(root);
      const record = records.get(root);
      record.draft.replace(snapshot(root));
      if (!record.draft.dirty) {
        root.classList.remove('dirty');
        root.querySelectorAll('.dirty,.unsaved').forEach(el => el.classList.remove('dirty', 'unsaved'));
      }
      record.order = ++order;
      status();
    }
    function apply(root, value) {
      paused = true;
      try {
        if (value.printDraft) ExportUI.restoreDraft(value.printDraft);
        if (value.printOrder) {
          const nodes = [...root.querySelectorAll('[data-field]')];
          for (const name of value.printOrder) {
            const row = nodes.find(el => el.dataset.field === name);
            row?.parentElement.append(row);
          }
        }
        if (value.html !== undefined) {
          $('formContent').innerHTML = value.html;
          bindClocks($('formContent'));
        }
        if (value.mixMode) {
          renderCustomMix(value.mixGroups);
          selectMixMode(value.mixMode);
        }
        if (value.examGroups) renderExamGroups(value.examGroups);
        for (const f of value.fields) {
          const el = f.id ? $(f.id) : root.querySelector(`[data-draft-key="${f.key}"]`);
          if (el && root.contains(el)) {
            el.value = f.value;
            el.checked = f.checked;
          }
        }
        if (value.disabled) {
          roomDisabled = value.disabled.slice();
          updateRoomLayout();
        }
        if (root.id === 'formDialog') {
          SubjectUI.bindEntity();
          SubjectUI.updateDuration();
          SubjectUI.rebindBatch();
          HelpUI.rebindActivation();
        }
        if (root.id === 'roomBatchDialog') {
          resetBatchPreview();
          $('batchDirect').disabled = !!$('batchTemplate').value;
        }
        if (root.id === 'bulkDialog') BulkUI.invalidate();
        root.querySelectorAll('.dirty,.unsaved').forEach(el => el.classList.remove('dirty', 'unsaved'));
        const dirty = records.get(root)?.draft.dirty;
        root.classList.toggle('dirty', !!dirty && root.matches('dialog,#planMenu'));
        if (dirty && !root.matches('dialog,#planMenu'))
          for (const el of controls(root))
            el.closest(
              'tr,.slot-row,#seatSettings,#numberDialog,#printOptions,#solverSettings,#examGroupsPanel,#invigilate details,.adjust-panel'
            )?.classList.add('dirty');
        window.ExportUI?.invalidate();
      } finally {
        paused = false;
        status();
      }
    }
    function watchDialog(dialog, loader) {
      queueMicrotask(() => watch(dialog, true));
      if (loader) loaders.set(dialog, loader);
      else loaders.delete(dialog);
    }
    function committed(source) {
      const root = owner(source);
      if (!root) return;
      const scope =
        source.closest(
          'tr,.slot-row,#seatSettings,#numberDialog,#printOptions,#solverSettings,#examGroupsPanel,#invigilate details,.adjust-panel,dialog,#planMenu'
        ) || root;
      scope.classList.remove('dirty', 'unsaved');
      // Keep unrelated unfinished rows. Commit only fields belonging to this saved group.
      const rec = records.get(root);
      if (!rec) return;
      const latest = snapshot(root),
        ids = new Set(
          controls(scope)
            .map(el => el.id)
            .filter(Boolean)
        );
      if (scope === root) {
        rec.draft.restore(latest);
        return;
      }
      rec.draft.rebase(old => {
        const patch = { ...old, fields: Editing.commitFieldSubset(old.fields, latest.fields, [...ids]) };
        if (scope.id === 'seatSettings') {
          patch.mixMode = latest.mixMode;
          patch.mixGroups = latest.mixGroups;
        }
        if (scope.id === 'examGroupsPanel') patch.examGroups = latest.examGroups;
        if (scope.id === 'printOptions') {
          patch.printDraft = latest.printDraft;
          patch.printOrder = latest.printOrder;
        }
        return patch;
      });
    }

    function rendered() {
      if (planId !== view.plan?.id) {
        records.clear();
        planId = view.plan?.id || null;
      }
      const root = $('.page.active');
      watch(root, !records.get(root)?.draft.dirty);
      watch($('planMenu'), !records.get($('planMenu'))?.draft.dirty);
      status();
    }
    function $(selector) {
      return selector.startsWith('.') ? document.querySelector(selector) : document.getElementById(selector);
    }
    function status() {
      const dirty = window.Workspace?.dirty() || false;
      $('draftState').textContent = dirty ? '● 有未保存修改' : '已提交到本机';
      $('draftState').classList.toggle('has-draft', dirty);
      // 按钮文字写明这一下会撤销什么：先撤销未保存的输入，再撤销最近一笔已保存操作。
      const hasDraft = [...records.entries()].some(
        ([root, r]) => r.draft.canUndo && (!root.matches('dialog') || root.open)
      );
      const saved = view?.edit_history?.can_undo ? view.edit_history.label || '已保存的操作' : '';
      const undoButton = $('globalUndo');
      undoButton.disabled = polling || (!hasDraft && !saved);
      undoButton.textContent = hasDraft ? '撤销输入' : saved ? '撤销：' + saved : '撤销上一步';
      undoButton.title = hasDraft
        ? '撤销本页最近一次尚未保存的输入'
        : saved
          ? '撤销已保存的上一步：' + saved
          : '没有可以撤销的操作';
      document.querySelectorAll('#nav [data-page]').forEach(button => {
        const root = $(button.dataset.page);
        button.querySelector('.nav-status').textContent = root?.querySelector('.dirty,.unsaved')
          ? '● 未保存'
          : Editing.stageReady(view, button.dataset.page)
            ? '✓'
            : '';
      });
    }
    async function undo() {
      if (polling) throw Error('正在编排，请稍后撤销。');
      const draft = [...records.entries()]
        .filter(([root, r]) => r.draft.canUndo && root.isConnected && (!root.matches('dialog') || root.open))
        .sort((a, b) => b[1].order - a[1].order)[0];
      if (draft) {
        apply(draft[0], draft[1].draft.undo());
        toast('已撤销上一步输入。');
        return;
      }
      if (Workspace.dirty()) throw Error('当前有未保存修改，可使用“恢复上次保存”放弃本页草稿。');
      view = await api('edit_undo', { revision: view.plan.revision });
      records.clear();
      window.ExportUI?.restoreSaved();
      renderAll();
      toast('已撤销上一步已保存操作。');
    }
    async function restoreSaved() {
      if (polling) throw Error('正在编排，请稍后恢复。');
      const dialog = [...document.querySelectorAll('dialog[open]:not(#unsavedDialog)')].at(-1),
        active = $('.page.active'),
        header = $('planMenu');
      const headerLast =
          header.classList.contains('dirty') && (records.get(header)?.order || 0) > (records.get(active)?.order || 0),
        root = dialog || (headerLast ? header : active);
      const latest = await api('state');
      if (view?.plan?.id !== latest.plan?.id) throw Error('当前考试已改变，请重新打开。');
      view = latest;
      if (dialog) {
        const loader = loaders.get(dialog);
        if (loader) {
          dialog.classList.remove('dirty');
          loader();
        } else {
          const rec = records.get(dialog);
          if (rec) {
            apply(dialog, rec.draft.restore());
            dialog.classList.remove('dirty');
          }
        }
      } else {
        Workspace.discardDrafts(false, root);
        records.delete(root);
        if (activePage === 'export') ExportUI.restoreSaved();
        renderAll();
      }
      status();
      toast('已恢复本页上次保存，其他页面的保存保留。');
    }
    async function defaultGroup(group) {
      const { values } = await api('defaults', {
        group: ['layout_numbering', 'batch_layout'].includes(group) ? 'room_layout' : group,
      });
      if (group === 'appearance') {
        Appearance.reset();
        return;
      }
      if (group === 'seating') {
        for (const [key, id] of [
          ['mode', 'mode'],
          ['seed', 'seed'],
          ['score_field', 'scoreField'],
        ])
          $(id).value = key === 'score_field' ? values[key] || 'score' : values[key];
        renderCustomMix(values.mix_groups);
        selectMixMode(values.mix_grades ? 'all' : 'separate');
        $('seatSettings').classList.add('dirty');
      }
      if (group === 'monitors') {
        $('invigilatorCount').value = values.invigilators;
        $('avoidSubject').checked = values.avoid_subject;
        $('avoidClass').checked = values.avoid_class;
        document.querySelector('#invigilate details').classList.add('dirty');
      }
      if (group === 'numbering') {
        for (const [key, id] of [
          ['number_rule', 'numberRule'],
          ['number_prefix', 'numberPrefix'],
          ['number_width', 'numberWidth'],
          ['number_start', 'numberStart'],
        ])
          $(id).value = values[key];
        document.querySelectorAll('[data-number-grade]').forEach(el => (el.value = ''));
        resetNumberPreview();
        $('numberDialog').classList.add('dirty');
      }
      if (group === 'solver') {
        $('solverLimit').value = values.time_limit;
        $('solverSettings').classList.add('dirty');
      }
      if (group === 'layout_numbering') {
        $('seatDirection').value = values.direction;
        $('seatOrder').value = values.order;
        $('seatSettings').classList.add('dirty');
        Workspace.route();
      }
      if (group === 'batch_layout') {
        for (const key of Object.keys(values))
          if ($('batch-' + key)) $('batch-' + key).value = entityValue(values, key);
        $('batchTemplate').value = '';
        $('batchDirect').disabled = false;
        $('roomBatchDialog').classList.add('dirty');
        resetBatchPreview();
      }
      if (group === 'room_layout') {
        for (const key of ['rows', 'cols', 'per_desk', 'capacity', 'order', 'direction'])
          $('room-' + key).value = values[key];
        $('room-aisles').value = '';
        $('room-availability').value = '';
        $('room-invigilators').value = '';
        roomDisabled = [];
        $('roomResetLabels').checked = true;
        $('roomDialog').classList.add('dirty');
        await updateRoomLayout();
      }
      changed(owner(document.querySelector(`[data-default-group="${group}"]`)));
      status();
      toast('本项默认参数已填入，保存后生效。');
    }
    function init() {
      document.addEventListener('focusin', e => {
        if (e.target.matches('input,select,textarea') && !e.target.matches(excluded))
          watch(
            owner(e.target),
            !records.get(owner(e.target))?.draft.dirty &&
              !owner(e.target)?.classList.contains('dirty') &&
              !owner(e.target)?.querySelector('.dirty,.unsaved')
          );
      });
      document.addEventListener('input', e => {
        if (e.target.matches(excluded) || !e.target.matches('input,select,textarea')) return;
        e.target.closest('#numberDialog,#printOptions,#solverSettings')?.classList.add('dirty');
        queueMicrotask(() => changed(owner(e.target)));
      });
      document.addEventListener('click', e => {
        const local = e.target.closest('[data-local-undo],[data-local-restore]');
        if (local) {
          if (local.hasAttribute('data-local-restore')) restoreSaved().catch(err => toast(err.message, true));
          else {
            const r = records.get(owner(local));
            if (r?.draft.canUndo) apply(owner(local), r.draft.undo());
            else toast('当前没有可撤销的输入。');
          }
        }
        const b = e.target.closest('[data-default-group]');
        if (b) defaultGroup(b.dataset.defaultGroup).catch(err => toast(err.message, true));
        const root = owner(e.target);
        if (root && e.target.closest('[data-draft-action]')) setTimeout(() => changed(root), 0);
        setTimeout(status, 0);
      });
      bind('globalUndo', undo);
      bind('restoreSaved', restoreSaved);
      bind('numberUndo', undo);
      bind('nextStep', async () => {
        await Editing.continueStep(
          () => Workspace.saveDrafts(),
          async () => {
            const step = WorkspaceCore.nextStep(view);
            if (activePage === 'data' && (step.kind || step.grades)) {
              if (step.grades) GradeEditor.open();
              else Workspace.selectKind(step.kind);
              throw Error(step.message);
            }
            const target = step.page === activePage ? null : step.page;
            if (target === 'data' && activePage !== 'overview') throw Error(step.message);
            const sequence = ['overview', 'data', 'schedule', 'seats', 'invigilate', 'check', 'export'],
              index = sequence.indexOf(activePage);
            const stage = { data: 'data', schedule: 'schedule', seats: 'seats', invigilate: 'monitors', check: null }[
              activePage
            ];
            const issues =
              activePage === 'seats'
                ? [
                    ...(view.validation?.stages?.seats?.errors || []),
                    ...(view.validation?.stages?.numbers?.errors || []),
                  ]
                : stage
                  ? view.validation?.stages?.[stage]?.errors || []
                  : activePage === 'check'
                    ? view.validation.errors
                    : [];
            if (issues.length) {
              IssueUI.locate(issues[0]);
              throw Error('本步还有 ' + issues.length + ' 项需处理，已定位第一项。');
            }
            page(sequence[Math.min(index + 1, sequence.length - 1)], true);
          }
        );
      });
      bind('solverSave', async () => {
        const limit = Number($('solverLimit').value);
        if (!Number.isInteger(limit) || limit < 1 || limit > 300) throw Error('求解时间须为 1～300 秒。');
        const q = clone(view.plan);
        q.settings.time_limit = limit;
        await save(q);
        $('solverSettings').classList.remove('dirty');
      });
    }
    function forget(scope) {
      if (!scope) records.clear();
      else records.delete(scope);
    }
    return { forget, init, watchDialog, committed, rendered, changed, status, undo, restoreSaved, defaultGroup };
  })();
  // Shared preview panels always display server-normalized rows and real impacts.
  function impactHtml(impact = {}) {
    const seats = impact.seats || [],
      lost = impact.removed_seats || [],
      locks = impact.locked_seats || [],
      duties = impact.monitors || [];
    const names = seats.map(x => {
      const s = view.plan.students.find(s => s.id === x.student_id);
      return [
        s?.name || x.student_id,
        x.exam_id === 'base' ? '固定座位' : view.plan.exams.find(e => e.id === x.exam_id)?.subject || x.exam_id,
        x.seat,
        x.locked ? '锁定' : '',
        x.removed ? '将移除原座位' : '布局变化',
      ];
    });
    return `<p class="${impact.requires_confirmation ? 'warning' : 'muted'}">影响 ${seats.length} 个座位关联（移除 ${lost.length}、锁定 ${locks.length}）及 ${duties.length} 场监考。学生资料保留；不自动安排到其他教室。</p>${names.length ? table(['学生', '范围', '原座号', '锁定', '影响'], names) : ''}${
      duties.length
        ? table(
            ['考场', '场次', '已安排监考'],
            duties.map(d => [
              view.plan.rooms.find(r => r.id === d.room_id)?.name,
              d.duty_id,
              d.assignments.map(a => view.plan.teachers.find(t => t.id === a.teacher_id)?.name || '待安排').join('、'),
            ])
          )
        : ''
    }`;
  }
  function normalizedRowsHtml(kind, rows) {
    if (kind === 'grades')
      return table(
        ['将删除的年级'],
        rows.map(g => [g])
      );
    const keys =
      kind === 'rooms'
        ? [
            'code',
            'name',
            'location',
            'rows',
            'cols',
            'per_desk',
            'capacity',
            'direction',
            'order',
            'availability',
            'invigilators',
          ]
        : kind === 'exams'
          ? ['grade', 'subject', 'date', 'start', 'end', 'duration']
          : ['name', 'grade', 'class_name'];
    return table(
      keys.map(k => view.fields[kind][k] || k),
      rows.map(r => keys.map(k => entityValue(r, k)))
    );
  }
  function acceptEdited(result, source = document.activeElement, submittedScope = null) {
    EditingUI.committed(source);
    submittedScope?.classList.remove('dirty');
    view = result;
    renderAll();
    // Use the refreshed values (including reset swap/normalized lock) as the saved baseline.
    if (submittedScope) EditingUI.committed(submittedScope);
    EditingUI.status();
  }
  const BulkUI = (() => {
    let spec = null,
      ticket = null,
      request = 0,
      onDone = null;
    const names = { grades: '年级', rooms: '考场', students: '学生', teachers: '教师', exams: '科目' };
    const roomFields = [
      ['code', '考场编号'],
      ['name', '考场名称'],
      ['location', '教室位置'],
      ['rows', '桌行数'],
      ['cols', '桌列数'],
      ['per_desk', '每桌人数'],
      ['capacity', '使用容量'],
      ['aisles', '过道'],
      ['disabled', '停用座号'],
      ['direction', '座号方向'],
      ['order', '顺排／S 型'],
      ['availability', '可用时段'],
      ['invigilators', '监考人数'],
    ];
    const examFields = [
      ['date', '日期'],
      ['start', '开始时间'],
      ['end', '结束时间'],
      ['duration', '计划分钟'],
      ['locked', '锁定日程'],
      ['special_seating', '单科座位'],
      ['invigilators', '监考人数'],
    ];
    function invalidate() {
      request++;
      ticket = null;
      $('bulkApply').disabled = true;
      $('bulkResult').innerHTML = '';
      $('bulkImpactConfirm').checked = false;
    }
    function fieldHtml(key, label, sample) {
      let input;
      if (['direction', 'order', 'locked', 'special_seating'].includes(key)) {
        const opts =
          key === 'direction'
            ? [
                ['horizontal', '横排'],
                ['vertical', '竖排'],
              ]
            : key === 'order'
              ? [
                  ['straight', '顺排'],
                  ['snake', 'S 型'],
                ]
              : [
                  ['否', '否'],
                  ['是', '是'],
                ];
        input = `<select data-bulk-value="${key}">${opts.map(([v, n]) => option(v, n, entityValue(sample, key) === v || sample[key] === v)).join('')}</select>`;
      } else
        input = `<input data-bulk-value="${key}" type="${key === 'date' ? 'date' : ['rows', 'cols', 'per_desk', 'capacity', 'duration', 'invigilators'].includes(key) ? 'number' : 'text'}" value="${esc(entityValue(sample, key))}">`;
      return `<label class="bulk-field"><span><input type="checkbox" data-bulk-field="${key}">${label}</span>${input}</label>`;
    }
    async function options() {
      const options = { ...spec };
      if (spec.action === 'update') {
        const fields = {};
        for (const el of document.querySelectorAll('[data-bulk-field]:checked')) {
          const key = el.dataset.bulkField;
          fields[key] = document.querySelector(`[data-bulk-value="${key}"]`).value;
        }
        if (!Object.keys(fields).length) throw Error('先勾选本次要统一修改的字段。');
        const prepared = await api('entity_prepare', {
          kind: spec.kind,
          row: fields,
          mapping: Object.fromEntries(Object.keys(fields).map(k => [k, k])),
        });
        options.fields = Object.fromEntries(Object.keys(fields).map(k => [k, prepared[k]]));
        if (spec.kind === 'rooms') options.reset_labels = $('bulkResetLabels').checked;
      }
      return options;
    }
    async function preview() {
      const token = ++request;
      ticket = null;
      $('bulkApply').disabled = true;
      try {
        const body = await options(),
          result = await api('bulk_preview', body);
        if (token !== request) return;
        ticket = { ...Editing.previewTicket(body, result.revision), result };
        $('bulkResult').innerHTML = normalizedRowsHtml(spec.kind, result.rows) + impactHtml(result.impact);
        $('bulkImpactRow').classList.toggle('hidden', !result.requires_confirmation);
        $('bulkImpactConfirm').checked = false;
        $('bulkApply').disabled = !!result.requires_confirmation;
        $('bulkError').classList.add('hidden');
      } catch (e) {
        if (token === request) errorAt('bulkError', e);
      }
    }
    async function apply() {
      if (!ticket) throw Error('请先预览本次操作。');
      const body = await options();
      if (!ticket.valid(body, view.plan.revision)) {
        invalidate();
        throw Error('资料或输入已变化，请重新预览。');
      }
      const snapshot = ticket;
      if (snapshot.result.requires_confirmation && !$('bulkImpactConfirm').checked)
        throw Error('请勾选确认受影响的安排。');
      const result = await api('bulk_apply', {
        ...body,
        revision: snapshot.revision,
        confirm_impact: snapshot.result.requires_confirmation,
      });
      $('bulkDialog').classList.remove('dirty');
      $('bulkDialog').close();
      acceptEdited(result, $('bulkDialog'));
      ticket = null;
      onDone?.();
      toast('批量操作已保存，可撤销上一步。');
    }
    function open(kind, action, ids, done) {
      if (!ids.length) throw Error('请先勾选要处理的' + names[kind] + '。');
      spec = { kind, action, ids: [...ids] };
      onDone = done;
      invalidate();
      $('bulkTitle').textContent =
        (action === 'delete' ? '删除所选' : '批量修改') + names[kind] + ' · ' + ids.length + ' 项';
      const sample = view.plan[kind]?.find?.(r => ids.includes(r.id)) || {};
      $('bulkFields').innerHTML =
        action === 'update'
          ? `<p class="muted">只修改勾选字段，其他资料保留。预览显示规范化后的实际值。</p><div class="form-grid">${(kind === 'rooms' ? roomFields : examFields).map(([k, label]) => fieldHtml(k, label, sample)).join('')}</div>${kind === 'rooms' ? '<label class="check"><input id="bulkResetLabels" type="checkbox">本笔同时恢复默认座号后调整行列（不先保存另一笔）</label>' : ''}`
          : '<p>预览确认后整批删除；有关联影响的安排会明确列出。</p>';
      $('bulkError').classList.add('hidden');
      $('bulkImpactRow').classList.add('hidden');
      $('bulkDialog').classList.remove('dirty');
      $('bulkDialog').showModal();
      EditingUI.watchDialog($('bulkDialog'));
      if (action === 'delete') preview();
    }
    function init() {
      bind('bulkPreview', preview);
      bind('bulkApply', async () => {
        try {
          await apply();
        } catch (e) {
          errorAt('bulkError', e);
        }
      });
      bind('bulkClose', () => Workspace.requestNavigation(() => $('bulkDialog').close()));
      $('bulkFields').addEventListener('input', () => {
        $('bulkDialog').classList.add('dirty');
        invalidate();
      });
      $('bulkImpactConfirm').onchange = () => {
        $('bulkApply').disabled = !ticket || (ticket.result.requires_confirmation && !$('bulkImpactConfirm').checked);
      };
    }
    return { open, init, preview, invalidate, apply };
  })();
  const DataSelection = (() => {
    const cache = new Map();
    let visible = [];
    function current(kind = $('entityKind').value) {
      const key = view.plan.id + '|' + kind;
      if (!cache.has(key)) cache.set(key, Editing.selection());
      const s = cache.get(key);
      s.prune(view.plan[kind].map(r => r.id));
      return s;
    }
    function render(rows, kind) {
      visible = rows.map(r => r.id);
      const selection = current(kind);
      $('selectionCount').textContent = `已选 ${selection.ids.length} 项 · 当前筛选 ${rows.length} 项`;
      document
        .querySelectorAll('[data-select-entity]')
        .forEach(el => (el.checked = selection.ids.includes(el.dataset.selectEntity)));
      const all = $('entitySelectAll');
      if (all) {
        all.checked = visible.length > 0 && visible.every(id => selection.ids.includes(id));
        all.disabled = !visible.length;
        all.indeterminate = !all.checked && visible.some(id => selection.ids.includes(id));
      }
      $('bulkEditSelected').classList.toggle('hidden', !['rooms', 'exams'].includes(kind));
      $('subjectBatchBtn').classList.toggle('hidden', kind !== 'exams');
      $('subjectCatalogBtn').classList.toggle('hidden', kind !== 'exams');
    }
    function init() {
      document.addEventListener('change', e => {
        const el = e.target;
        if (el.matches('[data-select-entity]')) current().toggle(el.dataset.selectEntity, el.checked);
        if (el.id === 'entitySelectAll') current().all(visible, el.checked);
        if (el.matches('[data-select-entity],#entitySelectAll'))
          render(
            view.plan[$('entityKind').value].filter(r => visible.includes(r.id)),
            $('entityKind').value
          );
      });
      bind('deleteSelected', () =>
        BulkUI.open($('entityKind').value, 'delete', current().ids, () => current().all(current().ids, false))
      );
      bind('bulkEditSelected', () => BulkUI.open($('entityKind').value, 'update', current().ids));
    }
    return { render, init, current };
  })();
  const GradeEditor = (() => {
    let original = [],
      creating = false;
    const selected = new Set();
    function rows(names) {
      $('gradeEditorRows').innerHTML = names
        .map(
          (name, i) =>
            `<div class="grade-edit-row"><label class="check"><input type="checkbox" data-grade-draft-select="${i}" aria-label="选择第${i + 1}个年级"></label><label>第 ${i + 1} 个年级<input data-grade-name="${i}" id="grade-name-${i}" value="${esc(name)}" placeholder="填写年级名称"></label><button class="link-button" data-grade-links="${esc(name)}" type="button">关联资料</button></div>`
        )
        .join('');
      $('gradeCount').value = names.length;
      selected.clear();
    }
    function values() {
      return [...document.querySelectorAll('#gradeEditorRows [data-grade-name]')].map(el => el.value);
    }
    function open(isNew = false) {
      creating = isNew;
      original = isNew ? [] : formalGrades(view.plan);
      const initial = isNew ? ['七年级', '八年级', '九年级'] : original;
      form(
        isNew ? '新建考试 · 设置年级' : '本次考试年级',
        (isNew ? field('newName', '考试名称', '期末考试') : '') +
          `<div class="toolbar"><label>年级数量<input id="gradeCount" type="number" readonly></label><button class="secondary" type="button" data-grade-add data-draft-action>添加年级</button><label class="check"><input id="gradeDraftAll" type="checkbox">全选</label><button class="secondary" type="button" data-grade-draft-delete data-draft-action>删除所选</button></div><div id="gradeEditorRows"></div><p class="muted">空白草稿可直接删除。已保存年级删除前检查关联；不会隐式删除学生。</p><div id="gradeLinks"></div>`,
        async () => {
          const grades = normalizeGrades(values());
          if (isNew) {
            view = await api('new', { name: $('newName').value, grades });
            activePage = 'overview';
            renderAll();
          } else {
            const q = clone(view.plan);
            q.grades = grades;
            q.grade_review_required = false;
            await save(q);
          }
        }
      );
      rows(initial);
      EditingUI.watchDialog($('formDialog'), () => open(isNew));
      $('formSave').textContent = isNew ? '创建考试' : '保存年级';
    }
    function links(grade) {
      if (!grade || creating) return;
      const assoc = Editing.gradeAssociations(view.plan, grade);
      $('gradeLinks').innerHTML =
        `<div class="card"><h3>${esc(grade)}的关联</h3><p>${assoc.counts.join(' / ')}（学生 / 科目 / 活动混排组 / 具名方案）</p>${assoc.students.length ? '<button class="secondary" data-grade-go="students" data-grade="' + esc(grade) + '">定位学生资料</button>' : ''} ${assoc.exams.length ? '<button class="secondary" data-grade-go="exams" data-grade="' + esc(grade) + '">定位科目资料</button>' : ''} ${assoc.groups.length || assoc.presets.length ? '<button class="secondary" data-grade-go="mix" data-grade="' + esc(grade) + '">定位混排设置</button>' : ''}<p class="muted">先迁移学生年级或处理关联科目和混排组，再删除年级。</p></div>`;
    }
    async function removeDraft() {
      const inputs = [...document.querySelectorAll('#gradeEditorRows [data-grade-name]')],
        chosen = [...document.querySelectorAll('[data-grade-draft-select]:checked')].map(
          el => +el.dataset.gradeDraftSelect
        );
      if (!chosen.length) throw Error('请先勾选年级。');
      const saved = chosen.map(i => inputs[i].value).filter(g => original.includes(g));
      if (!creating && saved.length) {
        if (JSON.stringify(values()) !== JSON.stringify(original))
          throw Error('先保存新增或修改的年级，或恢复上次保存，再删除已保存年级。');
        BulkUI.open('grades', 'delete', saved, () => {
          original = formalGrades(view.plan);
          rows(original);
          $('formDialog').classList.remove('dirty');
          EditingUI.watchDialog($('formDialog'), () => open(false));
        });
        return;
      }
      rows(inputs.filter((_, i) => !chosen.includes(i)).map(el => el.value));
      $('formDialog').classList.add('dirty');
      EditingUI.changed($('formDialog'));
    }
    function summary() {
      const p = view.plan,
        grades = formalGrades(p);
      $('gradeTotal').textContent = grades.length + ' 个年级';
      $('gradeReview').classList.toggle('hidden', !p.grade_review_required);
      $('gradeSummary').innerHTML =
        grades
          .map(g => {
            const a = Editing.gradeAssociations(p, g);
            return `<label class="grade-chip"><input type="checkbox" data-select-grade="${esc(g)}"><b>${esc(g)}</b><span>${a.students.length} 人 · ${a.exams.length} 科目</span><button type="button" class="link-button" data-open-grade-links="${esc(g)}">关联</button></label>`;
          })
          .join('') || '<p class="muted">先添加本次考试年级，再准备学生和科目。</p>';
      bind('gradeSelectAll', () => {
        const boxes = [...document.querySelectorAll('[data-select-grade]')],
          all = boxes.every(el => el.checked);
        boxes.forEach(el => (el.checked = !all));
      });
      bind('gradeDeleteSelected', () =>
        BulkUI.open(
          'grades',
          'delete',
          [...document.querySelectorAll('[data-select-grade]:checked')].map(el => el.dataset.selectGrade)
        )
      );
      bind('editGrades', () => Workspace.requestNavigation(() => open(false)));
    }
    function init() {
      document.addEventListener('click', e => {
        const b = e.target.closest('button');
        if (!b) return;
        try {
          if (b.hasAttribute('data-grade-add')) {
            rows([...values(), '']);
            $('formDialog').classList.add('dirty');
            EditingUI.changed($('formDialog'));
          }
          if (b.hasAttribute('data-grade-draft-delete')) removeDraft().catch(err => errorAt('formError', err));
          if (b.dataset.gradeLinks !== undefined) links(b.dataset.gradeLinks);
          if (b.dataset.openGradeLinks !== undefined) {
            open();
            links(b.dataset.openGradeLinks);
          }
          if (b.dataset.gradeGo) {
            const grade = b.dataset.grade;
            Workspace.requestNavigation(() => {
              $('formDialog').close();
              page(b.dataset.gradeGo === 'mix' ? 'seats' : 'data', true);
              if (b.dataset.gradeGo !== 'mix') {
                Workspace.selectKind(b.dataset.gradeGo);
                $('entityGrade').value = grade;
                Workspace.entities();
              } else $('seatSettings').open = true;
            });
          }
        } catch (err) {
          errorAt('formError', err);
        }
      });
      document.addEventListener('change', e => {
        if (e.target.id === 'gradeDraftAll')
          document.querySelectorAll('[data-grade-draft-select]').forEach(el => (el.checked = e.target.checked));
      });
    }
    return { open, summary, init };
  })();
  const SubjectUI = (() => {
    let batchTicket = null,
      batchRequest = 0,
      batchSession = 0;
    function setupEntity() {
      const name = $('edit-subject');
      if (!name) return;
      name.setAttribute('list', 'subjectNames');
      name.insertAdjacentHTML(
        'beforebegin',
        `<select id="editSubjectPreset" aria-label="从预设选择科目">${option('', '选择预设，也可手写')}${view.subject_catalog.map(s => option(s.name, s.name + ' · ' + s.duration + ' 分')).join('')}</select><datalist id="subjectNames">${view.subject_catalog.map(s => option(s.name, s.name)).join('')}</datalist>`
      );
      bindEntity();
      $('edit-duration').insertAdjacentHTML('afterend', '<small id="durationHint" class="muted"></small>');
      updateDuration();
    }
    function bindEntity() {
      if ($('editSubjectPreset'))
        $('editSubjectPreset').onchange = () => {
          const name = $('edit-subject');
          name.value = $('editSubjectPreset').value;
          if (!($('edit-start').value && $('edit-end').value))
            $('edit-duration').value = Editing.subjectDuration(view.subject_catalog, name.value);
          name.dispatchEvent(new Event('input', { bubbles: true }));
          updateDuration();
        };
    }
    function updateDuration() {
      if (!$('edit-duration') || !$('edit-start')) return;
      try {
        const d = Editing.examDuration($('edit-start').value, $('edit-end').value, $('edit-duration').value);
        $('edit-duration').value = d.minutes;
        $('edit-duration').readOnly = d.readonly;
        $('durationHint').textContent = d.readonly
          ? '实际时长：结束－开始，自动计算'
          : '计划时长：未定时间时供自动排程使用';
        $('durationHint').className = 'muted';
      } catch (e) {
        $('durationHint').textContent = e.message;
        $('durationHint').className = 'issue';
        $('edit-duration').readOnly = !!($('edit-start').value && $('edit-end').value);
      }
    }
    function catalogRows(rows) {
      $('catalogRows').innerHTML = rows
        .map(
          (s, i) =>
            `<div class="catalog-row"><label>科目名称<input id="catalog-name-${i}" data-catalog-name value="${esc(s.name)}"></label><label>默认分钟<input id="catalog-duration-${i}" data-catalog-duration type="number" min="1" max="1440" value="${s.duration}"></label><button type="button" class="link-button" data-catalog-remove="${i}" data-draft-action>删除模板</button></div>`
        )
        .join('');
    }
    function readCatalog() {
      return Editing.validateCatalog(
        [...document.querySelectorAll('[data-catalog-name]')].map((el, i) => ({
          name: el.value,
          duration: document.querySelectorAll('[data-catalog-duration]')[i].value,
        }))
      );
    }
    function openCatalog() {
      batchRequest++;
      batchTicket = null;
      form(
        '科目预设目录',
        '<p class="muted">这些是可复用的名称和计划分钟。修改目录不会追溯改变已有考试日程。</p><div id="catalogRows"></div><div class="toolbar"><button type="button" class="secondary" data-catalog-add data-draft-action>添加科目模板</button><button type="button" class="secondary" data-catalog-default data-draft-action>恢复内置目录</button></div>',
        async () => {
          acceptEdited(
            await api('subject_catalog_save', { catalog: readCatalog(), revision: view.plan.revision }),
            $('formDialog')
          );
        }
      );
      catalogRows(view.subject_catalog);
      EditingUI.watchDialog($('formDialog'), openCatalog);
    }
    function readBatch() {
      const grades = [...document.querySelectorAll('[data-subject-grade]:checked')].map(el => el.dataset.subjectGrade),
        subjects = [...document.querySelectorAll('[data-subject-name]:checked')].map(el => el.dataset.subjectName);
      const custom = $('subjectCustomNames')
        .value.split(/[;；]/)
        .map(x => x.trim())
        .filter(Boolean);
      subjects.push(...custom.map(name => ({ name, duration: Number($('subjectCustomDuration').value) })));
      const body = { grades, subjects };
      for (const k of ['date', 'start', 'end'])
        if ($('subjectBatch-' + k).value)
          body[k] = k === 'date' ? $('subjectBatch-' + k).value : parseClock($('subjectBatch-' + k).value);
      if ($('subjectBatchOverride').checked)
        body.duration = Editing.examDuration(
          body.start || '',
          body.end || '',
          $('subjectBatch-duration').value
        ).minutes;
      return body;
    }
    function invalidateBatch() {
      batchRequest++;
      batchTicket = null;
      $('formSave').disabled = true;
      $('subjectBatchResult').innerHTML = '';
      const start = $('subjectBatch-start').value,
        end = $('subjectBatch-end').value;
      try {
        const d = Editing.examDuration(start, end, $('subjectBatch-duration').value);
        $('subjectBatch-duration').readOnly = d.readonly;
        if (d.readonly) {
          $('subjectBatch-duration').value = d.minutes;
          $('subjectBatchOverride').checked = true;
        }
      } catch (e) {
        errorAt('formError', e);
      }
    }
    async function previewBatch() {
      const n = ++batchRequest,
        session = batchSession,
        planId = view.plan.id;
      let body;
      const active = () =>
        n === batchRequest &&
        session === batchSession &&
        planId === view.plan?.id &&
        $('formDialog').open &&
        !!$('subjectBatchResult');
      try {
        body = readBatch();
        const v = await api('subject_batch_preview', body);
        if (!active() || JSON.stringify(readBatch()) !== JSON.stringify(body)) return;
        if (v.revision !== view.plan.revision) throw Error('方案已改变，请重新预览。');
        batchTicket = Editing.previewTicket(body, v.revision);
        $('subjectBatchResult').innerHTML =
          `<p>将新增 ${v.exams.length} 场考试；已有或重复 ${v.duplicates.length} 项，保留已有内容。</p>` +
          normalizedRowsHtml('exams', v.exams) +
          (v.duplicates.length
            ? table(
                ['重复年级', '科目（不覆盖）'],
                v.duplicates.map(e => [e.grade, e.subject])
              )
            : '');
        $('formSave').disabled = !v.exams.length;
        $('formError').classList.add('hidden');
      } catch (e) {
        if (active()) errorAt('formError', e);
      }
    }
    function openBatch() {
      batchRequest++;
      batchSession++;
      if (!requireGrades('exams')) return;
      batchTicket = null;
      const p = view.plan;
      form(
        '按年级批量添加科目',
        `<h3>选择年级 <button type="button" class="link-button" data-check-group="subject-grade">全选／取消</button></h3><div class="form-grid">${p.grades.map((g, i) => `<label class="check"><input id="subject-grade-${i}" data-subject-grade="${esc(g)}" type="checkbox">${esc(g)}</label>`).join('')}</div><h3>选择科目 <button type="button" class="link-button" data-check-group="subject-name">全选／取消</button></h3><div class="form-grid">${view.subject_catalog.map((s, i) => `<label class="check"><input id="subject-name-${i}" data-subject-name="${esc(s.name)}" type="checkbox">${esc(s.name)} · ${s.duration} 分</label>`).join('')}</div><div class="form-grid">${field('subjectCustomNames', '手写新科目（多个用分号分隔）')}${field('subjectCustomDuration', '新科目计划分钟', 90, 'number')}${field('subjectBatch-date', '统一日期（可留空）', '', 'date')}<label>统一开始${clockControl('subjectBatch-start', '', '批量科目开始')}</label><label>统一结束${clockControl('subjectBatch-end', '', '批量科目结束')}</label><label>统一计划分钟<input id="subjectBatch-duration" type="number" value="90" min="1" max="1440"></label></div><label class="check"><input id="subjectBatchOverride" type="checkbox">覆盖所选模板的计划分钟（起止完整时自动按差值计算）</label><button type="button" class="secondary" id="subjectBatchPreview">预览新增与重复</button><div id="subjectBatchResult"></div>`,
        async () => {
          const body = readBatch();
          if (!batchTicket || !batchTicket.valid(body, view.plan.revision))
            throw Error('输入或资料已变化，请重新预览。');
          acceptEdited(await api('subject_batch', { ...body, revision: batchTicket.revision }), $('formDialog'));
        }
      );
      $('formSave').disabled = true;
      bind('subjectBatchPreview', previewBatch);
      bindClocks($('formContent'));
      EditingUI.watchDialog($('formDialog'), openBatch);
    }
    function rebindBatch() {
      if ($('subjectBatchPreview')) {
        batchTicket = null;
        bind('subjectBatchPreview', previewBatch);
        invalidateBatch();
      }
    }
    function init() {
      bind('subjectCatalogBtn', openCatalog);
      bind('subjectBatchBtn', openBatch);
      $('formContent').addEventListener('input', () => {
        updateDuration();
        if ($('subjectBatchResult')) invalidateBatch();
      });
      document.addEventListener('click', e => {
        const b = e.target.closest('button');
        if (!b) return;
        if (b.hasAttribute('data-catalog-add')) {
          const rows = [...document.querySelectorAll('[data-catalog-name]')].map((el, i) => ({
            name: el.value,
            duration: document.querySelectorAll('[data-catalog-duration]')[i].value,
          }));
          catalogRows([...rows, { name: '', duration: 90 }]);
          $('formDialog').classList.add('dirty');
          EditingUI.changed($('formDialog'));
        }
        if (b.hasAttribute('data-catalog-remove')) {
          b.closest('.catalog-row').remove();
          $('formDialog').classList.add('dirty');
          EditingUI.changed($('formDialog'));
        }
        if (b.hasAttribute('data-catalog-default'))
          api('defaults', { group: 'subjects' })
            .then(v => {
              catalogRows(v.values);
              $('formDialog').classList.add('dirty');
              EditingUI.changed($('formDialog'));
            })
            .catch(err => errorAt('formError', err));
        if (b.dataset.checkGroup) {
          const boxes = [...document.querySelectorAll(`[data-${b.dataset.checkGroup}]`)];
          const on = !boxes.every(el => el.checked);
          boxes.forEach(el => (el.checked = on));
          $('formDialog').classList.add('dirty');
          invalidateBatch();
          EditingUI.changed($('formDialog'));
        }
      });
    }
    return { bindEntity, setupEntity, updateDuration, openCatalog, openBatch, rebindBatch, init };
  })();
  const IssueUI = (() => {
    let context = null;
    function render() {
      const v = view.validation,
        stageNames = {
          data: '资料完整性',
          schedule: '考试日程',
          seats: '座位编排',
          numbers: '考号',
          monitors: '监考安排',
        };
      const opened = context?.opened || [];
      $('checkResult').innerHTML =
        `<div class="${v.errors.length ? 'warning' : 'ok'}">${v.errors.length} 项必须处理 · ${v.warnings.length} 项核对提示</div>` +
        Object.entries(v.stages || { data: v })
          .map(
            ([stage, checks]) =>
              `<details class="check-stage" data-stage="${stage}" ${checks.errors.length || opened.includes(stage) ? 'open' : ''}><summary>${stageNames[stage] || stage} · ${checks.errors.length} 项必须处理 / ${checks.warnings.length} 项提示</summary>${[
                'errors',
                'warnings',
              ]
                .map(type =>
                  Editing.groupIssues(checks[type])
                    .map(
                      (g, i) =>
                        `<div class="${type === 'errors' ? 'issue' : 'warning'} issue-group"><div class="section-head"><span>${esc(g.message)}${g.items.length > 1 ? ' · 影响 ' + g.items.length + ' 项' : ''}</span>${g.items.length > 1 && g.entity && g.field && !['id', 'code', 'student_no', 'number'].includes(g.field) ? `<button class="secondary" data-issue-batch="${stage}|${type}|${i}">批量处理</button>` : ''}</div><details ${g.items.length === 1 ? 'open' : ''}><summary>查看对象与处理入口</summary>${g.items.map((x, j) => `<div class="issue-action"><span>${esc(issueText(x))}</span><button class="secondary" data-issue-locate="${stage}|${type}|${i}|${j}">去处理${x.field ? ' · ' + esc(view.fields[x.entity]?.[x.field] || x.field) : ''}</button></div>`).join('')}</details></div>`
                    )
                    .join('')
                )
                .join('')}</details>`
          )
          .join('');
      document
        .querySelectorAll('[data-issue-locate]')
        .forEach(b => (b.onclick = () => locate(item(b.dataset.issueLocate))));
      document
        .querySelectorAll('[data-issue-batch]')
        .forEach(b => (b.onclick = () => batch(group(b.dataset.issueBatch))));
    }
    function group(key) {
      const [stage, type, index] = key.split('|');
      return Editing.groupIssues((view.validation.stages || { data: view.validation })[stage][type])[+index];
    }
    function item(key) {
      return group(key).items[+key.split('|')[3]];
    }
    function remember() {
      context = {
        opened: [...document.querySelectorAll('.check-stage[open]')].map(el => el.dataset.stage),
        scroll: window.scrollY,
      };
      $('returnCheck').classList.remove('hidden');
    }
    function locate(x) {
      remember();
      if (/number/.test(x.code || '')) {
        openNumberSettings();
        $('numberPreviewBtn').focus();
        $('issueContext').textContent = '先预览新旧考号；已有考号需要更新时须明确勾选重新生成，人工号不会自动覆盖。';
        return;
      }
      const entity = x.entity || (x.student_id ? 'students' : x.teacher_id ? 'teachers' : null),
        id = x.entity_id || x.student_id || x.teacher_id;
      if (entity && id && view.plan[entity]?.some(row => row.id === id)) {
        page('data', true);
        Workspace.selectKind(entity);
        editEntity(entity, id);
        setTimeout(() => {
          const el = $('edit-' + x.field) || $('room-' + x.field);
          if (el) {
            el.focus();
            el.setAttribute('aria-invalid', 'true');
            el.scrollIntoView({ block: 'center' });
          }
        }, 0);
        return;
      }
      if (/grade/.test(x.code) && !entity) {
        page('data', true);
        GradeEditor.open();
        return;
      }
      Workspace.locateIssue(x);
      $('issueContext').textContent = '处理后点击“返回检查”，重新核对当前已保存方案。';
    }
    function batch(g) {
      remember();
      const ids = [
        ...new Set(
          g.items.map(x => x.entity_id || x.student_id || x.teacher_id || x.exam_id || x.room_id).filter(Boolean)
        ),
      ];
      if (!ids.length) {
        locate(g.items[0]);
        return;
      }
      page('data', true);
      Workspace.selectKind(g.entity);
      const supported =
        g.entity === 'rooms' ||
        (g.entity === 'exams' &&
          ['date', 'start', 'end', 'duration', 'locked', 'invigilators', 'special_seating'].includes(g.field));
      if (supported) {
        BulkUI.open(g.entity, 'update', ids);
        const checkbox = document.querySelector(`[data-bulk-field="${g.field}"]`);
        if (checkbox) checkbox.checked = true;
        return;
      }
      const label = view.fields[g.entity]?.[g.field] || g.field;
      const input =
        g.field === 'grade'
          ? `<label>${esc(label)}<select id="issueBatchValue">${view.plan.grades.map(grade => option(grade, grade)).join('')}</select></label>`
          : field('issueBatchValue', '统一填写 ' + label);
      const revision = view.plan.revision;
      form(
        '批量处理同类问题 · ' + ids.length + ' 项',
        input + '<p class="muted">只修改所选对象的这个字段，其他资料保留；保存时统一检查。</p>',
        async () => {
          if (view.plan.revision !== revision) throw Error('方案已改变，请返回检查重新定位。');
          const prepared = await api('entity_prepare', {
            kind: g.entity,
            row: { [g.field]: $('issueBatchValue').value },
            mapping: { [g.field]: g.field },
          });
          const q = clone(view.plan);
          q[g.entity].forEach(row => {
            if (ids.includes(row.id)) row[g.field] = prepared[g.field];
          });
          await save(q);
        }
      );
    }
    async function back() {
      await Editing.continueStep(
        () => Workspace.saveDrafts(),
        async () => {
          view = await api('state');
          page('check', true);
          render();
          if (context) window.scrollTo(0, context.scroll);
          $('returnCheck').classList.add('hidden');
          $('issueContext').textContent = '已按最新保存内容重新检查。';
          context = null;
        }
      );
    }
    function init() {
      bind('returnCheck', async () => {
        try {
          await back();
        } catch (e) {
          toast(e.message, true);
        }
      });
    }
    return { render, locate, init };
  })();
  const HelpUI = (() => {
    const sections = {
      start: [
        '按流程上手',
        '新建考试并设置参试年级 → 预检资料 → 日程 → 座位与考号 → 监考 → 检查 → 导出。普通编辑保存后留在本页，阶段末用“保存并继续”。',
      ],
      templates: [
        '资料与模板',
        '基础资料可以下载对应模板。导入先核对列对应、再预检；年级使用本次考试清单，不自动增加。起止完整时分钟自动计算，原表时长矛盾会阻止导入。',
      ],
      terms: [
        '名词解释',
        '固定座位：整次考试的基础安排。单科座位：个别场次的独立安排。物理位置：教室里的行和列。座号排列：这些位置使用的编号；调整座号不会搬动学生。待复核：资料或规则改变后，须重新检查有关安排。',
      ],
      recovery: [
        '撤销与批量',
        '顶栏的撤销按钮会写明这一下撤销什么：有未保存输入时显示“撤销输入”；没有草稿时显示“撤销：”加最近一笔已保存操作的名称，最多50笔随考试保存。恢复上次保存只放弃当前页或弹窗草稿。批量操作先预览规范化值和关联影响，确认后整批保存，失败保留输入。',
      ],
      drag: [
        '两种拖动',
        '先选“拖动学生”或“拖动座号”，不可混用。学生到空位移动、到有人位置预览交换；固定总览有复用时先选具体时段。锁定学生先通过点选调整处理。座号只交换启用且容量内的两个位置，学生保持原物理位置，考号另行复核。也可以点选源与目标，或用键盘 Tab、Enter。',
      ],
      faq: [
        '常见问题',
        '保存失败时输入仍保留，重试前不要关闭。考场缩小先预览被移除的座位和监考影响；学生不会自动转到其他教室。只改主题或字号不改变考试。真实系统打印与Windows实机测试按交付另验。',
      ],
      contact: ['联系与版本', ''],
    };
    async function copy(text) {
      try {
        await navigator.clipboard.writeText(text);
        toast('已复制。');
      } catch (e) {
        toast('未能复制，请选中文字后手动复制。', true);
      }
    }
    function content(key) {
      const [title, text] = sections[key];
      $('helpContent').innerHTML = `<h3>${title}</h3><p>${text}</p>`;
      if (key === 'contact')
        $('helpContent').innerHTML +=
          `<p>版本 ${esc(view.version)} · 产品 考场编排</p><p>联系作者：<span id="helpContact">${esc(view.license.contact || '请联系软件提供者')}</span> <button class="secondary" id="helpCopyContact">复制联系方式</button></p><p>本机数据目录：<code id="helpRoot">${esc(view.root)}</code> <button class="secondary" id="helpCopyRoot">复制路径</button></p><button class="secondary" id="helpOpenOutput">打开导出文件夹</button> <button class="secondary" id="helpUpdate">检查更新</button>`;
      bind('helpCopyContact', () => copy(view.license.contact || ''));
      bind('helpCopyRoot', () => copy(view.root));
      bind('helpOpenOutput', () => api('open_folder'));
      bind('helpUpdate', () => {
        $('helpDialog').close();
        $('updateBtn').click();
      });
      document
        .querySelectorAll('[data-help-section]')
        .forEach(b => b.setAttribute('aria-pressed', String(b.dataset.helpSection === key)));
    }
    function open() {
      content('start');
      $('helpDialog').showModal();
    }
    function activation() {
      const l = view.license;
      form(
        '激活这台电脑',
        `<div class="${l.broken ? 'issue' : 'ok'}" id="activationStatus">${esc(l.message || '当前状态：' + (l.state === 'open' ? '源码开发' : l.state === 'active' ? '已激活' : l.state === 'trial' ? '试用剩 ' + l.daysLeft + ' 天' : '试用已结束'))}</div><p>试用 3 天。到期仍可查看、编排和保存，导出与打印需激活。机器码和激活码仅用于本产品。</p><div class="activation-step"><b>1</b><div><h3>复制机器码，联系作者</h3><input readonly id="activationMachine" value="${esc(l.machine)}" aria-label="本机机器码"><button class="secondary" type="button" id="copyMachine">复制机器码</button><p id="activationContact">${esc(l.contact || '请联系软件提供者获取激活码')}</p><button class="link-button" type="button" id="copyActivationContact">复制联系方式</button></div></div><div class="activation-step"><b>2</b><div><h3>粘贴本机激活码</h3><textarea id="activationCode" rows="4" placeholder="在这里粘贴激活码"></textarea><p class="muted">激活与资料处理在本机完成。</p></div></div>`,
        async () => {
          if (!$('activationCode').value.trim()) throw Error('请先粘贴激活码。');
          view = await api('activate', { code: $('activationCode').value });
          renderAll();
          toast('本机激活成功。');
        }
      );
      $('formSave').textContent = '激活本机';
      bind('copyMachine', () => copy(l.machine));
      bind('copyActivationContact', () => copy(l.contact || ''));
      EditingUI.watchDialog($('formDialog'), activation);
    }
    function rebindActivation() {
      if ($('copyMachine')) {
        bind('copyMachine', () => copy(view.license.machine));
        bind('copyActivationContact', () => copy(view.license.contact || ''));
      }
    }
    function init() {
      bind('helpBtn', open);
      bind('licenceBtn', activation);
      document.querySelectorAll('[data-help-section]').forEach(b => (b.onclick = () => content(b.dataset.helpSection)));
      bind('helpClose', () => $('helpDialog').close());
      bind('explainClose', () => $('explainDialog').close());
      document.addEventListener('click', e => {
        const b = e.target.closest('[data-explain]');
        if (b) {
          $('explainTitle').textContent = b.textContent.replace('？', '');
          $('explainText').textContent = b.dataset.explain;
          $('explainDialog').showModal();
        }
      });
    }
    return { init, open, activation, copy, rebindActivation };
  })();
  // Late binding preserves the existing controller style without an extra framework.
  window.openNewExam = () => GradeEditor.open(true);
  window.openGradeSettings = () => GradeEditor.open(false);
  window.renderGradeSummary = GradeEditor.summary;
  Object.assign(window, {
    GradeEditor,
    DataSelection,
    SubjectUI,
    BulkUI,
    IssueUI,
    HelpUI,
    acceptEdited,
    impactHtml,
    normalizedRowsHtml,
  });
  bind('newBtn', () => GradeEditor.open(true));
  EditingUI.init();
  BulkUI.init();
  DataSelection.init();
  GradeEditor.init();
  SubjectUI.init();
  IssueUI.init();
  HelpUI.init();
}
