"""批量变更的纯预检；不落盘、不移动到其他考场。"""
from copy import deepcopy
from .model import DEFAULTS,ENTITY_DEFAULTS,grade_name
from . import rooms

ROOM_FIELDS={'code','name','location','rows','cols','per_desk','capacity','aisles','disabled','direction','order','availability','invigilators','seat_labels'}


def align_layouts(old,new):
    """Keep unchanged disabled places physical when numbering or shape changes."""
    from .seat_labels import positions
    previous={r['id']:r for r in old['rooms']}
    for room in new['rooms']:
        prev=previous.get(room['id'])
        if not prev or room.get('disabled')!=prev.get('disabled'):continue
        if not any(room.get(k)!=prev.get(k) for k in ('rows','cols','per_desk','direction','order','seat_labels')):continue
        before={p['seat']:(p['row'],p['col']) for p in positions(prev)}
        after={(p['row'],p['col']):p['seat'] for p in positions(room)}
        room['disabled']=sorted(after[before[n]] for n in prev['disabled'] if n in before and before[n] in after)
    return new


def room_impact(old,new):
    from .engine import seat_layout,duties
    previous={r['id']:r for r in old['rooms']};current={r['id']:r for r in new['rooms']}
    affected=[];lost=[];locks=[];changed=set()
    for rid,r in previous.items():
        after=current.get(rid)
        if after is not None and not any(r.get(k)!=after.get(k) for k in ('rows','cols','per_desk','capacity','disabled','direction','order','seat_labels')):
            continue
        total=r['rows']*r['cols']*r['per_desk']
        old_coordinates={p['seat']:(p['row'],p['col']) for p in seat_layout({**r,'disabled':[],'capacity':total})}
        positions=seat_layout(after) if after else []
        usable={(p['row'],p['col']) for p in positions}
        shape=after is None or any(r.get(k)!=after.get(k) for k in ('rows','cols','per_desk'))
        for key,mapping in old['seats'].items():
            for sid,pos in mapping.items():
                if pos.get('room_id')!=rid:continue
                coordinate=old_coordinates.get(pos['seat'])
                invalid=coordinate not in usable
                if shape or invalid:
                    item=dict(exam_id=key,student_id=sid,room_id=rid,seat=pos['seat'],locked=bool(pos.get('locked')),removed=invalid)
                    affected.append(item);changed.add(rid)
                    if invalid:lost.append(item)
                    if pos.get('locked'):locks.append(item)
        if after is None:changed.add(rid)
    monitors=[]
    for d in duties(old):
        if d['room_id'] in changed:
            monitors.append(dict(duty_id=d['id'],room_id=d['room_id'],assignments=deepcopy(old['invigilation'].get(d['id'],[]))))
    return dict(seats=affected,removed_seats=lost,locked_seats=locks,monitors=monitors,
                requires_confirmation=bool(affected or any(d['assignments'] for d in monitors)))


def drop_affected(plan,impact):
    q=deepcopy(plan)
    for item in impact['removed_seats']:q['seats'][item['exam_id']].pop(item['student_id'],None)
    if impact['removed_seats']:
        q['stale']=sorted(set(q.get('stale',[]))|{'seats','invigilation'})
    return q


def prepare(plan,body):
    kind=body.get('kind');action=body.get('action');ids=body.get('ids')
    if kind not in ('grades','rooms','students','teachers','exams') or not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):raise ValueError('请选择不重复的资料编号。')
    q=deepcopy(plan);impact=dict(seats=[],removed_seats=[],locked_seats=[],monitors=[],requires_confirmation=False)
    if kind=='grades':
        if action!='delete':raise ValueError('年级批量操作仅支持删除。')
        selected=[grade_name(x) for x in ids]
        if len(set(selected))!=len(selected):raise ValueError('规范化后的年级不能重复选择。')
        if any(x not in q['grades'] for x in selected):raise ValueError('所选年级已不存在。')
        for g in selected:
            students=[s['id'] for s in q['students'] if s['grade']==g];exams=[e['id'] for e in q['exams'] if e['grade']==g]
            groups=[row for row in q['settings']['mix_groups'] if g in row]
            presets=[r['id'] for r in q['settings']['mix_presets'] if any(g in group for group in r['groups'])]
            if students or exams or groups or presets:raise ValueError(f'年级“{g}”仍有关联：{len(students)} 名学生、{len(exams)} 场考试、{len(groups)} 个混排组、{len(presets)} 个具名方案，请先处理关联。')
        q['grades']=[g for g in q['grades'] if g not in selected]
    else:
        selected=set(ids);found={r['id'] for r in q[kind]}
        if not selected<=found:raise ValueError('所选资料已不存在，请重新选择。')
        if action=='delete':q[kind]=[r for r in q[kind] if r['id'] not in selected]
        elif action=='update' and kind=='exams':
            fields=body.get('fields')
            if not isinstance(fields,dict) or not fields or set(fields)-{'date','start','end','duration','locked','invigilators','special_seating'}:raise ValueError('请选择有效的科目日程字段。')
            from .subjects import normalize_exam
            q['exams']=[normalize_exam({**r,**deepcopy(fields)}) if r['id'] in selected else r for r in q['exams']]
        elif action=='update' and kind=='rooms':
            fields=body.get('fields')
            if not isinstance(fields,dict) or not fields or set(fields)-ROOM_FIELDS:raise ValueError('请选择需要批量修改的考场字段。')
            q['rooms']=[{**r,**deepcopy(fields)} if r['id'] in selected else r for r in q['rooms']]
            if body.get('reset_labels') is True:
                for r in q['rooms']:
                    if r['id'] in selected:r['seat_labels']={}
            q=align_layouts(plan,q)
            q['rooms']=[rooms.prepare_room(q,r) for r in q['rooms']]
            from .validation import event
            if any(not event(w) for r in q['rooms'] for w in r['availability']):raise ValueError('考场可用时段的日期、起止时间不正确。')
        else:raise ValueError('不支持这项批量操作。')
        if kind=='rooms':
            impact=room_impact(plan,q)
            q=drop_affected(q,impact)
    rows=[r for r in (plan[kind] if action=='delete' else q[kind]) if (r in selected if kind=='grades' else r['id'] in selected)]
    return dict(plan=q,kind=kind,action=action,ids=list(selected) if kind=='grades' else ids,rows=deepcopy(rows),impact=impact,requires_confirmation=impact['requires_confirmation'])


def defaults(group):
    groups={'seating':('mode','seed','mix_grades','mix_groups','score_field'),
            'monitors':('invigilators','avoid_subject','avoid_class'),
            'numbering':('number_prefix','number_prefixes','number_rule','number_width','number_start'),
            'solver':('time_limit',)}
    if group in groups:return {k:deepcopy(DEFAULTS[k]) for k in groups[group]}
    if group=='room_layout':return {k:deepcopy(ENTITY_DEFAULTS['rooms'][k]) for k in ('rows','cols','per_desk','capacity','aisles','disabled','order','direction','availability','invigilators','seat_labels')}
    if group=='subjects':
        from .subjects import BUILTIN
        return deepcopy(BUILTIN)
    if group=='appearance':return dict(theme='system',fontScale=1,density='standard')
    if group=='report_layouts':
        from .printing import default_layouts
        return default_layouts()
    raise ValueError('这项资料没有系统默认值，请恢复上次保存内容。')
