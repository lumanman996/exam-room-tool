'use strict';
let roomEditing = null,
  roomEditingRevision = null,
  roomLayoutRequest = 0,
  roomLayoutResult = null,
  roomDisabled = [],
  roomBatchPreview = null,
  roomBatchRequest = 0,
  roomChangeTicket = null,
  roomChangeRequest = 0,
  roomSession = 0;
function nextRoomCode() {
  const codes = new Set(view.plan.rooms.map(r => Number(r.code)));
  for (let n = 1; n <= 99; n++) if (!codes.has(n)) return String(n).padStart(2, '0');
  return '';
}
function openRoomSettings(id) {
  roomSession++;
  roomChangeRequest++;
  delete $('roomChangePreview').dataset.pending;
  roomEditing = clone(id ? view.plan.rooms.find(r => r.id === id) : view.defaults.rooms);
  roomEditingRevision = view.plan.revision;
  roomDisabled = [...(roomEditing.disabled || [])];
  if (!id) {
    roomEditing.code = nextRoomCode();
    roomEditing.name = '第' + roomEditing.code + '考场';
  }
  $('roomTitle').textContent = id ? '设置行列／布局 · ' + roomEditing.name : '添加考场';
  for (const k of ['code', 'name', 'location', 'rows', 'cols', 'per_desk', 'capacity', 'order', 'direction'])
    $('room-' + k).value = roomEditing[k];
  $('room-aisles').value = roomEditing.aisles.join('、');
  $('room-availability').value = entityValue(roomEditing, 'availability');
  $('room-invigilators').value = roomEditing.invigilators ?? '';
  $('roomResetLabels').checked = false;
  $('roomError').classList.add('hidden');
  $('roomDialog').classList.remove('dirty');
  invalidateRoomChange();
  $('roomDialog').showModal();
  updateRoomLayout();
  window.EditingUI?.watchDialog($('roomDialog'), () => openRoomSettings(id));
}
function roomInputs() {
  return {
    ...roomEditing,
    code: $('room-code').value,
    name: $('room-name').value,
    location: $('room-location').value,
    rows: $('room-rows').value,
    cols: $('room-cols').value,
    per_desk: $('room-per_desk').value,
    capacity: $('room-capacity').value,
    order: $('room-order').value,
    direction: $('room-direction').value,
    aisles: $('room-aisles').value,
    disabled: roomDisabled,
    seat_labels: $('roomResetLabels').checked ? {} : roomEditing.seat_labels || {},
  };
}
function invalidateRoomChange() {
  roomChangeRequest++;
  roomChangeTicket = null;
  $('roomApply').disabled = true;
  $('roomImpact').innerHTML = '';
  $('roomImpactConfirm').checked = false;
  $('roomImpactRow').classList.add('hidden');
}
async function updateRoomLayout() {
  const request = ++roomLayoutRequest;
  roomLayoutResult = null;
  invalidateRoomChange();
  $('roomError').classList.add('hidden');
  try {
    const raw = roomInputs(),
      physical = Number(raw.rows) * Number(raw.cols) * Number(raw.per_desk);
    if (Number.isInteger(physical) && physical >= 1 && physical <= 99)
      roomDisabled = roomDisabled.filter(s => s <= physical);
    raw.disabled = roomDisabled;
    const v = await api('room_layout_preview', { room: raw });
    if (request !== roomLayoutRequest) return;
    roomLayoutResult = v;
    $('room-capacity').value = v.capacity;
    $('roomLayoutStats').textContent =
      `布局共 ${v.physical} 位 · 启用 ${v.enabled} 位 · 本次使用 ${v.capacity} 位。点击位置可启用或停用；提交前须预览实际影响。`;
    $('roomLayout').innerHTML =
      '<div class="platform">讲台</div><div class="seat-grid" style="grid-template-columns:repeat(' +
      v.room.cols * v.room.per_desk +
      ',minmax(48px,1fr))">' +
      v.positions
        .map(
          s =>
            `<button type="button" data-toggle-seat="${s.seat}" class="seat-cell layout-toggle ${s.side === v.room.per_desk && v.room.aisles.includes(s.desk) ? 'aisle' : ''} ${s.disabled ? 'disabled' : !s.usable ? 'reserved' : ''}" aria-label="座位 ${s.seat}：${s.disabled ? '停用' : s.usable ? '使用' : '未使用'}"><b>${String(s.seat).padStart(2, '0')}</b><span>${s.disabled ? '停用' : s.usable ? '使用' : '未使用'}</span></button>`
        )
        .join('') +
      '</div>';
    document.querySelectorAll('[data-toggle-seat]').forEach(
      b =>
        (b.onclick = () => {
          const n = +b.dataset.toggleSeat;
          $('roomDialog').classList.add('dirty');
          roomDisabled = roomDisabled.includes(n) ? roomDisabled.filter(x => x !== n) : [...roomDisabled, n];
          window.EditingUI?.changed($('roomDialog'));
          updateRoomLayout();
        })
    );
  } catch (e) {
    if (request === roomLayoutRequest) {
      errorAt('roomError', e);
      $('roomLayout').innerHTML = '';
      $('roomLayoutStats').textContent = '修正布局参数后可继续预览。';
    }
  }
}
async function readRoom() {
  if (!roomLayoutResult) throw Error('先修正行列布局，再预览修改。');
  const prepared = await api('entity_prepare', {
    kind: 'rooms',
    row: { availability: $('room-availability').value, invigilators: $('room-invigilators').value },
    mapping: { availability: 'availability', invigilators: 'invigilators' },
  });
  return {
    room: {
      ...roomLayoutResult.room,
      code: $('room-code').value,
      name: $('room-name').value,
      location: $('room-location').value,
      availability: prepared.availability,
      invigilators: prepared.invigilators,
    },
    reset_labels: $('roomResetLabels').checked,
  };
}
function roomChangeSignature() {
  return JSON.stringify({
    room: roomInputs(),
    availability: $('room-availability').value,
    invigilators: $('room-invigilators').value,
    reset_labels: $('roomResetLabels').checked,
  });
}
async function previewRoomChange() {
  invalidateRoomChange();
  const request = ++roomChangeRequest,
    session = roomSession,
    planId = view.plan.id,
    signature = roomChangeSignature();
  const current = () =>
    request === roomChangeRequest &&
    session === roomSession &&
    planId === view.plan?.id &&
    $('roomDialog').open &&
    signature === roomChangeSignature();
  try {
    const body = await readRoom();
    if (!current()) return false;
    const v = await api('room_change_preview', body);
    if (!current()) return false;
    if (v.revision !== roomEditingRevision || v.revision !== view.plan.revision)
      throw Error('方案已改变，请恢复上次保存或重新打开设置。');
    roomChangeTicket = { ...Editing.previewTicket(body, v.revision), result: v };
    $('roomImpact').innerHTML = normalizedRowsHtml('rooms', [v.room]) + impactHtml(v.impact);
    $('roomImpactRow').classList.toggle('hidden', !v.requires_confirmation);
    $('roomImpactConfirm').checked = false;
    $('roomApply').disabled = !!v.requires_confirmation;
    $('roomError').classList.add('hidden');
    return true;
  } catch (e) {
    if (current()) errorAt('roomError', e);
    return false;
  }
}

async function saveRoomSettings() {
  $('roomApply').disabled = true;
  try {
    const body = await readRoom();
    if (!roomChangeTicket || !roomChangeTicket.valid(body, view.plan.revision))
      throw Error('输入或资料已变化，请重新预览实际修改。');
    const snapshot = roomChangeTicket;
    if (snapshot.result.requires_confirmation && !$('roomImpactConfirm').checked) throw Error('先确认受影响安排。');
    const result = await api('room_save', {
      room: snapshot.result.room,
      revision: snapshot.revision,
      reset_labels: body.reset_labels,
      confirm_impact: snapshot.result.requires_confirmation,
    });
    $('roomDialog').classList.remove('dirty');
    $('roomDialog').close();
    roomLayoutRequest++;
    acceptEdited(result, $('roomDialog'));
    toast('考场设置已保存，可撤销。');
    return true;
  } catch (e) {
    errorAt('roomError', e);
    $('roomApply').disabled = false;
    return false;
  }
}
bind('roomChangePreview', previewRoomChange);
bind('roomApply', saveRoomSettings);
bind('roomClose', () =>
  Workspace.requestNavigation(() => {
    $('roomDialog').close();
    roomLayoutRequest++;
  })
);
$('roomDialog').addEventListener('input', e => {
  if (e.target.id === 'roomImpactConfirm') return;
  invalidateRoomChange();
  if (
    [
      'room-rows',
      'room-cols',
      'room-per_desk',
      'room-capacity',
      'room-order',
      'room-direction',
      'room-aisles',
      'roomResetLabels',
    ].includes(e.target.id)
  )
    updateRoomLayout();
});
$('roomImpactConfirm').onchange = () => {
  $('roomApply').disabled =
    !roomChangeTicket || (roomChangeTicket.result.requires_confirmation && !$('roomImpactConfirm').checked);
};
bind('roomEnableAll', () => {
  roomDisabled = [];
  $('room-capacity').value = Math.min(
    99,
    Number($('room-rows').value) * Number($('room-cols').value) * Number($('room-per_desk').value)
  );
  $('roomDialog').classList.add('dirty');
  window.EditingUI?.changed($('roomDialog'));
  return updateRoomLayout();
});
async function batchOptions() {
  const options = {
    start: $('batchStart').value,
    count: $('batchCount').value,
    name_prefix: $('batchNamePrefix').value,
    name_suffix: $('batchNameSuffix').value,
  };
  if ($('batchTemplate').value) {
    options.template_id = $('batchTemplate').value;
    return options;
  }
  const keys = [
      'location',
      'rows',
      'cols',
      'per_desk',
      'capacity',
      'aisles',
      'disabled',
      'direction',
      'order',
      'availability',
      'invigilators',
    ],
    row = Object.fromEntries(keys.map(k => [k, $('batch-' + k).value]));
  const prepared = await api('entity_prepare', {
    kind: 'rooms',
    row,
    mapping: Object.fromEntries(keys.map(k => [k, k])),
  });
  options.template = Object.fromEntries(keys.map(k => [k, prepared[k]]));
  return options;
}
function resetBatchPreview() {
  roomBatchRequest++;
  roomBatchPreview = null;
  $('batchApply').disabled = true;
  $('batchPreview').innerHTML = '';
  $('batchError').classList.add('hidden');
}
function openRoomBatch(templateId = '') {
  $('batchStart').value = Number(nextRoomCode()) || 1;
  $('batchCount').value = templateId ? 1 : 5;
  $('batchNamePrefix').value = '第';
  $('batchNameSuffix').value = '考场';
  $('batchTemplate').innerHTML =
    option('', '直接填写下方布局与时段', !templateId) +
    view.plan.rooms.map(r => option(r.id, '复制 ' + r.name + ' 的布局与时段', r.id === templateId)).join('');
  for (const key of [
    'location',
    'rows',
    'cols',
    'per_desk',
    'capacity',
    'aisles',
    'disabled',
    'direction',
    'order',
    'availability',
    'invigilators',
  ])
    $('batch-' + key).value = entityValue(view.defaults.rooms, key);
  $('batchDirect').disabled = !!templateId;
  resetBatchPreview();
  $('roomBatchDialog').classList.remove('dirty');
  $('roomBatchDialog').showModal();
  window.EditingUI?.watchDialog($('roomBatchDialog'), () => openRoomBatch(templateId));
}
$('roomBatchDialog').addEventListener('input', () => {
  resetBatchPreview();
  $('batchDirect').disabled = !!$('batchTemplate').value;
});
bind('roomBatchBtn', () => openRoomBatch());
bind('batchClose', () =>
  Workspace.requestNavigation(() => {
    $('roomBatchDialog').close();
    roomBatchRequest++;
  })
);
bind('batchPreviewBtn', async () => {
  const request = ++roomBatchRequest;
  roomBatchPreview = null;
  $('batchApply').disabled = true;
  try {
    const options = await batchOptions(),
      v = await api('room_batch_preview', options);
    if (request !== roomBatchRequest) return;
    roomBatchPreview = Editing.previewTicket(options, v.revision);
    $('batchPreview').innerHTML = normalizedRowsHtml('rooms', v.rooms);
    $('batchApply').disabled = false;
  } catch (e) {
    if (request === roomBatchRequest) errorAt('batchError', e);
  }
});
async function saveRoomBatch() {
  try {
    const options = await batchOptions();
    if (!roomBatchPreview || !roomBatchPreview.valid(options, view.plan.revision))
      throw Error('先预览当前输入，再确认创建。');
    const result = await api('room_batch', { ...options, revision: roomBatchPreview.revision });
    $('roomBatchDialog').classList.remove('dirty');
    $('roomBatchDialog').close();
    roomBatchRequest++;
    $('entityKind').value = 'rooms';
    acceptEdited(result, $('roomBatchDialog'));
    toast('考场已整批创建，可撤销上一步。');
    return true;
  } catch (e) {
    errorAt('batchError', e);
    return false;
  }
}
bind('batchApply', saveRoomBatch);
