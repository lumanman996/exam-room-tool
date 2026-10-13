"""资料变更的关联迁移、失效范围与撤销边界。"""
from copy import deepcopy
from .model import now

SEAT_SETTINGS=('mode','seed','mix_grades','mix_groups','score_field')
MONITOR_SETTINGS=('invigilators','avoid_subject','avoid_class')


def reconcile(old,new,reset_labels=False):
    from .engine import duties,seat_layout
    q=deepcopy(new);stale=set(old.get('stale',[]));details=deepcopy(old.get('stale_seats',[]))
    if 'seats' in stale and not details:details=list(old.get('seats',{'base':{}}))
    changed=[k for k in ('students','rooms','exams','teachers','grades') if q.get(k)!=old.get(k)]
    settings_changed=[k for k in (*SEAT_SETTINGS,*MONITOR_SETTINGS,'slots','exam_groups') if q['settings'].get(k)!=old['settings'].get(k)]
    assignments_changed=any(q.get(k)!=old.get(k) for k in ('seats','invigilation'))
    if assignments_changed and not changed and not settings_changed:
        q['history_epoch']=old.get('history_epoch',0)+1
        if q['seats']!=old['seats']:
            details=sorted(set(details)|{k for k,v in q['seats'].items() if v})
            if details:stale.add('seats')
        if q['invigilation']!=old['invigilation'] or old.get('invigilation'):stale.add('invigilation')
    if not changed and not settings_changed:
        q['stale']=sorted(stale);q['stale_seats']=details;return q
    q['history_epoch']=old.get('history_epoch',0)+1
    student_ids={x['id'] for x in q['students']};exam_ids={x['id'] for x in q['exams']}
    for key in list(q.get('seats',{})):
        if key!='base' and key not in exam_ids:del q['seats'][key];continue
        q['seats'][key]={sid:p for sid,p in q['seats'][key].items() if sid in student_ids}
    q['number_sources']={sid:v for sid,v in q.get('number_sources',{}).items() if sid in student_ids}
    # Changing the numbering route keeps students at the same physical desk.
    old_rooms={r['id']:r for r in old['rooms']}
    for room in q['rooms']:
        prev=old_rooms.get(room['id'])
        if not prev:continue
        layout_changed=any(room.get(k)!=prev.get(k) for k in ('direction','order','rows','cols','per_desk','seat_labels'))
        shape_changed=any(room.get(k)!=prev.get(k) for k in ('rows','cols','per_desk'))
        if shape_changed and (room.get('seat_labels') or (prev.get('seat_labels') and not reset_labels)):
            raise ValueError('改变行列前请先恢复默认座号排列，再预览布局影响。')
        if layout_changed:
            from .seat_labels import remap
            remap(q,prev,room)
    if set(changed)&{'students','rooms','exams','grades'} or set(settings_changed)&set(SEAT_SETTINGS):
        details=sorted(set(details)|{key for key,mapping in q['seats'].items() if mapping})
        if details:stale.add('seats')
        if old.get('invigilation'):stale.add('invigilation')
    if 'teachers' in changed or set(settings_changed)&set(MONITOR_SETTINGS):
        if old.get('invigilation'):stale.add('invigilation')
    if set(settings_changed)&{'slots','exam_groups'} and q['exams']:stale.add('schedule')
    if 'grades' in changed and q['exams']:stale.add('schedule')
    q['stale_seats']=[key for key in details if key in q['seats'] and q['seats'][key]]
    if not q['stale_seats']:stale.discard('seats')
    q['stale']=sorted(stale)
    # Duty IDs include dates/times; migrate assignments by room and exam identity.
    old_duties=duties(old);new_duties=duties(q);old_assign=old.get('invigilation',{})
    teachers={t['id'] for t in q['teachers']};assign={};pending=[]
    for duty in new_duties:
        sources=[d for d in old_duties if d['room_id']==duty['room_id'] and set(d['exam_ids'])&set(duty['exam_ids'])]
        if duty['id'] in old_assign and all(d['id']==duty['id'] for d in sources):
            arr=deepcopy(q.get('invigilation',{}).get(duty['id'],old_assign[duty['id']]))
        elif len(sources)==1:arr=deepcopy(old_assign.get(sources[0]['id'],[]))
        else:
            arr=[]
            for index in range(duty['required']):
                locked={a['teacher_id'] for d in sources for i,a in enumerate(old_assign.get(d['id'],[])) if i==index and a.get('locked') and a.get('teacher_id') in teachers}
                if len(locked)>1:pending.append(dict(duty_id=duty['id'],index=index,teacher_ids=sorted(locked)))
                arr.append(dict(teacher_id=next(iter(locked)) if len(locked)==1 else '',locked=len(locked)==1))
        for index,a in enumerate(arr):
            if a.get('teacher_id') not in teachers:a.update(teacher_id='',locked=False)
            if index>=duty['required'] and a.get('locked'):pending.append(dict(duty_id=duty['id'],index=index,teacher_ids=[a['teacher_id']],kind='excess_slot'))
        assign[duty['id']]=arr
    q['invigilation']=assign
    live={d['id'] for d in new_duties}
    pending.extend(c for c in old.get('pending_monitor_locks',[]) if c['duty_id'] in live and c not in pending)
    q['pending_monitor_locks']=pending
    q['change_log']=(old.get('change_log',[])+[dict(at=now(),kind='data_or_rules',entities=changed,settings=settings_changed,stale=q['stale'],revision=old['revision']+1)])[-100:]
    return q


def finish_seating(plan,key):
    q=deepcopy(plan);remaining=q.get('stale_seats',[])
    if not remaining and 'seats' in q.get('stale',[]):remaining=list(q['seats'])
    q['stale_seats']=[x for x in remaining if x!=key]
    if not q['stale_seats']:q['stale']=[s for s in q.get('stale',[]) if s!='seats']
    return q
