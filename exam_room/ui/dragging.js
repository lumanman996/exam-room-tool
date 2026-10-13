'use strict';
const Dragging = (() => {
  function studentRequest(context, id, seat) {
    if (context.scope === 'base' && context.ambiguous && !context.session)
      throw Error('先选择明确的日期／时段，再拖动学生。');
    const source = context.mapping[id];
    if (!source) throw Error('这名学生尚未安排，请使用点选调整。');
    if (source.locked) throw Error('学生位置已锁定，请先通过点选调整解锁。');
    if (!context.usable.includes(seat)) throw Error('目标位置停用或不在本次使用容量内。');
    const others = (context.occupants[seat] || []).filter(s => s.id !== id);
    if (others.length > 1) throw Error('目标有多个时段的学生，请选择明确时段。');
    if (others.some(s => context.mapping[s.id]?.locked)) throw Error('目标学生已锁定，请先解锁。');
    if (source.room_id === context.roomId && source.seat === seat) throw Error('请选择另一个位置。');
    return {
      student_id: id,
      room_id: context.roomId,
      seat,
      exam_id: context.scope || 'base',
      swap: others.length === 1,
      locked: false,
    };
  }
  function labelRequest(context, first, second) {
    if (first === second || !context.usable.includes(first) || !context.usable.includes(second))
      throw Error('请选择两个不同的启用且容量内座位。');
    return { room_id: context.roomId, first, second, action: 'swap' };
  }
  function dragDistance(a, b) {
    return Math.hypot(a[0] - b[0], a[1] - b[1]);
  }
  function previewGate() {
    let epoch = 0;
    return {
      begin(signature) {
        const n = ++epoch;
        return {
          valid(current) {
            return n === epoch && current === signature;
          },
        };
      },
      invalidate() {
        epoch++;
      },
    };
  }
  return { studentRequest, labelRequest, dragDistance, previewGate };
})();
if (typeof module !== 'undefined') module.exports = Dragging;
if (typeof document !== 'undefined')
  window.DraggingUI = (() => {
    let mode = 'view',
      source = null,
      pointer = null,
      ghost = null,
      lastCell = null,
      suppressClick = false,
      previewGate = Dragging.previewGate(),
      pendingPreview = null;
    function context() {
      const p = view.plan,
        rid = $('previewRoom').value,
        x = WorkspaceCore.seatContext(p, $('seatScope').value || 'base'),
        events = new Set(p.exams.map(e => [e.date, e.start, e.end].join('|')));
      return {
        roomId: rid,
        scope: $('seatScope').value || 'base',
        session: $('seatSession').value,
        ambiguous: events.size > 1 || p.exams.some(e => !e.date || !e.start || !e.end),
        mapping: x.mapping,
        occupants: WorkspaceCore.occupants(p, $('seatScope').value || 'base', rid, $('seatSession').value),
        usable: (view.layouts[rid] || []).map(s => s.seat),
      };
    }
    function setMode(next) {
      cancel();
      mode = next;
      document
        .querySelectorAll('button[data-drag-mode]')
        .forEach(b => b.setAttribute('aria-pressed', String(b.dataset.dragMode === mode)));
      $('dragModeHint').textContent =
        mode === 'view'
          ? '点击学生可查看或输入目标座位。'
          : mode === 'students'
            ? '拖学生到目标；也可点选学生再点目标位置，Enter 同样有效。先选明确时段，锁定学生先解锁。'
            : '拖动或点选两个座号。学生保持原物理位置，锁定保留；考号需另行复核。';
      $('roomPreview').dataset.dragMode = mode;
      $('labelPointControls').classList.toggle('hidden', mode !== 'labels');
    }
    function render() {
      const layouts = view.layouts[$('previewRoom').value] || [];
      for (const id of ['labelFirst', 'labelSecond']) {
        const old = $(id).value;
        $(id).innerHTML = layouts
          .map((p, i) =>
            option(
              p.seat,
              String(p.seat).padStart(2, '0') + ' 号',
              old ? String(p.seat) === old : i === (id === 'labelFirst' ? 0 : 1)
            )
          )
          .join('');
      }
      $('labelReset').disabled = !layouts.length;
      setMode(mode);
    }
    function previewKey() {
      return JSON.stringify([
        view.plan?.id,
        view.plan?.revision,
        activePage,
        $('previewRoom').value,
        $('seatScope').value,
        $('seatSession').value,
        mode,
        $('labelFirst').value,
        $('labelSecond').value,
        $('adjustRoom')?.value,
        $('adjustSeat')?.value,
        $('swapSeat')?.checked,
        $('lockSeat')?.checked,
      ]);
    }
    async function requestPreview(name, body) {
      if (polling) throw Error('正在编排，请结束后再调整。');
      const ticket = previewGate.begin(previewKey());
      pendingPreview = ticket;
      $('dragPreviewCancel').classList.remove('hidden');
      $('dragWaitingText').textContent = '正在核对本次调整，可按 Esc 或点击取消。';
      try {
        const value = await api(name, body);
        return ticket.valid(previewKey()) ? value : null;
      } catch (e) {
        if (!ticket.valid(previewKey())) return null;
        throw e;
      } finally {
        if (pendingPreview === ticket) {
          pendingPreview = null;
          $('dragPreviewCancel').classList.add('hidden');
          $('dragWaitingText').textContent = '';
        }
      }
    }
    function numberReviewHtml(items) {
      return `<p class="${items?.length ? 'warning' : 'muted'}">${items?.length ? '有 ' + items.length + ' 项生成考号需要复核。' : '考号不在本次自动改写。'}保存后到“考号生成”预览再确认；人工考号保留。</p>`;
    }
    async function studentPreview(body, submittedScope = null) {
      const v = await requestPreview('adjust_seat_preview', body);
      if (!v) return false;
      if (v.revision !== view.plan.revision) throw Error('资料已改变，请恢复最新保存后再预览。');
      const mapping = v.seats[body.exam_id] || {},
        before = view.plan.seats[body.exam_id] || view.plan.seats.base || {},
        changes = [];
      for (const [id, a] of Object.entries(mapping)) {
        const old = before[id] || {};
        if (old.room_id !== a.room_id || old.seat !== a.seat || !!old.locked !== !!a.locked) {
          const s = view.plan.students.find(s => s.id === id);
          changes.push([
            s?.name || id,
            view.plan.rooms.find(r => r.id === old.room_id)?.name || '未安排',
            old.seat || '—',
            view.plan.rooms.find(r => r.id === a.room_id)?.name,
            a.seat,
            a.locked ? '锁定' : '不锁定',
          ]);
        }
      }
      form(
        body.swap ? '预览学生交换' : '预览学生移动',
        table(['学生', '原考场', '原座号', '新考场', '新座号', '保存后的锁定'], changes) +
          numberReviewHtml(v.number_review),
        async () => {
          const result = await api('adjust_seat', { ...body, revision: v.revision });
          acceptEdited(result, $('formDialog'), submittedScope);
          toast('学生座位已调整，可撤销上一步。');
        }
      );
      $('formSave').textContent = '确认调整并保存';
      return false;
    }
    async function labelPreview(body) {
      const v = await requestPreview('seat_labels_preview', body);
      if (!v) return;
      if (v.revision !== view.plan.revision) throw Error('资料已改变，请恢复最新保存后再预览。');
      form(
        body.action === 'reset' ? '预览恢复默认座号' : '预览交换座号',
        `<p>当前考场：${esc(v.room.name)}。只调整编号，学生及锁定保持原物理位置，作用于该考场全部固定／单科安排。</p>` +
          table(
            ['学生', '范围', '原座号', '新座号', '锁定'],
            v.changes.map(c => [
              view.plan.students.find(s => s.id === c.student_id)?.name || c.student_id,
              c.exam_id === 'base' ? '固定座位' : view.plan.exams.find(e => e.id === c.exam_id)?.subject,
              c.old_seat,
              c.new_seat,
              c.locked ? '保留锁定' : '',
            ])
          ) +
          table(
            ['物理行', '物理座位列', '新座号'],
            v.positions.map(p => [p.row, p.col, p.seat])
          ) +
          numberReviewHtml(v.number_review),
        async () => {
          acceptEdited(await api('seat_labels_apply', { ...body, revision: v.revision }), $('formDialog'));
          toast('座号排列已保存，学生物理位置不变。');
        }
      );
      $('formSave').textContent = '确认座号并保存';
    }
    async function drop(selected, cell) {
      if (polling) throw Error('正在编排，结束后才能调整。');
      const current = context(),
        seat = Number(cell.dataset.seat);
      if (selected.revision !== view.plan.revision) throw Error('资料已改变，请重新选择。');
      if (mode === 'students') await studentPreview(Dragging.studentRequest(current, selected.studentId, seat));
      else if (mode === 'labels') await labelPreview(Dragging.labelRequest(current, selected.seat, seat));
    }
    function cancel() {
      previewGate.invalidate();
      pendingPreview = null;
      if ($('dragPreviewCancel')) $('dragPreviewCancel').classList.add('hidden');
      if ($('dragWaitingText')) $('dragWaitingText').textContent = '';
      pointer = null;
      source = null;
      ghost?.remove();
      ghost = null;
      lastCell?.classList.remove('drop-target', 'drop-blocked');
      lastCell = null;
      document.querySelectorAll('.drag-source').forEach(el => el.classList.remove('drag-source'));
    }
    function choose(node) {
      const cell = node.closest('[data-seat]');
      if (!cell) return null;
      return {
        studentId: node.dataset.studentDrag,
        seat: Number(cell.dataset.seat),
        revision: view.plan.revision,
        element: node,
      };
    }
    function point(e) {
      if (mode === 'view' || e.target.closest('#labelPointControls')) return;
      const cell = e.target.closest('#roomPreview [data-seat]');
      if (!cell) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      if (suppressClick && e.type === 'click' && e.detail > 0) {
        suppressClick = false;
        return;
      }
      if (!source) {
        const node =
          mode === 'students' ? e.target.closest('[data-student-drag]') : cell.querySelector('[data-label-drag]');
        if (!node) {
          toast(mode === 'students' ? '先选择一名学生。' : '这个位置不可调整。', true);
          return;
        }
        source = choose(node);
        node.classList.add('drag-source');
        $('dragModeHint').textContent = '已选 ' + node.textContent + '，请选择目标位置。';
        return;
      }
      const selected = source;
      source = null;
      selected.element?.classList.remove('drag-source');
      drop(selected, cell).catch(err => toast(err.message, true));
    }
    function begin(e) {
      suppressClick = false;
      if (e.button !== 0 || mode === 'view' || polling) return;
      const node =
        mode === 'students'
          ? e.target.closest('#roomPreview [data-student-drag]')
          : e.target.closest('#roomPreview [data-label-drag]');
      if (!node || node.disabled) return;
      pointer = { ...choose(node), id: e.pointerId, start: [e.clientX, e.clientY], moved: false };
      node.setPointerCapture?.(e.pointerId);
    }
    function move(e) {
      if (!pointer || pointer.id !== e.pointerId) return;
      if (!pointer.moved && Dragging.dragDistance(pointer.start, [e.clientX, e.clientY]) < 8) return;
      pointer.moved = true;
      e.preventDefault();
      if (!ghost) {
        ghost = document.createElement('div');
        ghost.className = 'drag-ghost';
        ghost.textContent = (mode === 'students' ? '学生：' : '座号：') + pointer.element.textContent;
        document.body.append(ghost);
        pointer.element.classList.add('drag-source');
      }
      ghost.style.left = e.clientX + 14 + 'px';
      ghost.style.top = e.clientY + 12 + 'px';
      lastCell?.classList.remove('drop-target', 'drop-blocked');
      lastCell = document.elementFromPoint(e.clientX, e.clientY)?.closest('#roomPreview [data-seat]');
      if (lastCell) {
        const c = context();
        lastCell.classList.add(c.usable.includes(+lastCell.dataset.seat) ? 'drop-target' : 'drop-blocked');
      }
    }
    function end(e) {
      if (!pointer || pointer.id !== e.pointerId) return;
      const picked = pointer,
        cell = document.elementFromPoint(e.clientX, e.clientY)?.closest('#roomPreview [data-seat]');
      picked.element.releasePointerCapture?.(e.pointerId);
      const moved = picked.moved;
      cancel();
      if (moved) {
        e.preventDefault();
        suppressClick = true;
        if (cell) drop(picked, cell).catch(err => toast(err.message, true));
        else toast('未落到有效座位，方案没有改变。');
      }
    }
    function init() {
      bind('dragPreviewCancel', () => {
        cancel();
        toast('已取消预览，方案保持不变。');
      });
      document.querySelectorAll('button[data-drag-mode]').forEach(b => (b.onclick = () => setMode(b.dataset.dragMode)));
      document.addEventListener('pointerdown', begin);
      document.addEventListener('pointermove', move, { passive: false });
      document.addEventListener('pointerup', end);
      document.addEventListener('pointercancel', cancel);
      document.addEventListener('click', point, true);
      document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && (pointer || pendingPreview)) {
          e.preventDefault();
          cancel();
        }
        if (e.key === 'Enter' && e.target.matches('#roomPreview [data-seat]')) point(e);
      });
      bind('labelPointPreview', () =>
        labelPreview(Dragging.labelRequest(context(), +$('labelFirst').value, +$('labelSecond').value))
      );
      bind('labelReset', () => labelPreview({ room_id: $('previewRoom').value, action: 'reset' }));
      setMode('view');
    }
    return { init, render, studentPreview, labelPreview, cancel };
  })();
if (typeof document !== 'undefined') DraggingUI.init();
