"""考号预览、事务生成、来源校验与独立撤销。考号始终是文本。"""
from collections import defaultdict
from copy import deepcopy
import re


def two_digits(value, label):
    text=str(value).strip()
    if not re.fullmatch(r'[0-9]{1,2}',text) or not 1<=int(text)<=99:
        raise ValueError(label+'须为 01～99，不能超过两位。')
    return text.zfill(2)


def location(plan, student_id):
    from .engine import seat_layout
    pos=plan.get('seats',{}).get('base',{}).get(student_id)
    if not pos:raise ValueError('尚未安排固定座位，请先编排座位。')
    room=next((r for r in plan['rooms'] if r['id']==pos.get('room_id')),None)
    if not room:raise ValueError('考场不存在，请重新编排座位。')
    code=two_digits(room.get('code',''),'考场编号');seat=two_digits(pos.get('seat',''),'座位号')
    if int(seat) not in {s['seat'] for s in seat_layout(room)}:
        raise ValueError('座位已停用或超出考场容量，请先调整座位。')
    return room,code,seat


def source_issues(plan):
    issues=[]
    sources=plan.get('number_sources',{})
    for student in plan.get('students',[]):
        sid=student['id'];source=sources.get(sid)
        # Imported or explicitly edited numbers are not treated as generated ones.
        if not source or student.get('number')!=source.get('number'):continue
        try:
            room,code,seat=location(plan,sid)
            expected=source['prefix']+code+seat
            if expected==student['number'] and room['id']==source['room_id']:continue
            reason=f'当前考号 {student["number"]}，按固定座位应为 {expected}。'
        except ValueError as e:reason=str(e)
        issues.append(dict(code='number_seat_mismatch',student_id=sid,
                           message='考号与固定考场、座位不一致，请到「考号设置」预览并重新生成。'+reason))
    return issues


def preview(plan,prefix=None,overwrite=False,grade='',rule='seat',width=None,start=None,prefixes=None):
    from .model import grade_name,plan_grades
    grade=grade_name(grade)
    if grade and grade not in plan_grades(plan):raise ValueError('所选年级不在本次考试年级清单中。')
    options_prefix_explicit=prefix is not None
    settings=plan['settings'];prefix=str(settings.get('number_prefix','') if prefix is None else prefix).strip()
    configured={**settings.get('number_prefixes',{}),**(prefixes or {})}
    if any(not isinstance(v,str) for v in configured.values()):raise ValueError('年级前缀须以文本填写。')
    rows=[];errors=[];warnings=[];prospective={s['id']:s.get('number','') for s in plan['students']};changed={}
    def issue(code,message,sid=None):
        value=dict(code=code,message=message)
        if sid:value['student_id']=sid
        errors.append(value)
    if rule not in ('seat','serial'):raise ValueError('请选择考场座位编号或流水号格式。')
    if any(ord(c)<32 for c in prefix):issue('number_prefix','考号前缀不能包含换行或控制字符。')
    if rule=='seat' and not prefix and not configured:issue('number_prefix','请填写考号前缀，通常为 2～4 位，长度可自定。')
    chosen=[s for s in plan['students'] if not grade or s['grade']==grade]
    if not chosen:
        if grade:warnings.append(dict(code='number_students',message='该年级已设置，但当前没有学生，未生成考号。'))
        else:issue('number_students','当前范围没有学生。')
    selected={s['id'] for s in chosen}
    used={s.get('number') for s in plan['students'] if s.get('number') and (s['id'] not in selected or not overwrite)}
    if rule=='serial':
        try:
            width=int(settings['number_width'] if width is None else width)
            start=int(settings['number_start'] if start is None else start)
            if not 1<=width<=20 or start<0:raise ValueError()
        except (TypeError,ValueError):raise ValueError('起始流水号须非负，位数须为 1～20。')
        n=start
    for student in chosen:
        sid=student['id'];old=student.get('number','');keep=bool(old and not overwrite)
        student_prefix=str((prefixes or {}).get(student.get('grade'),prefix if options_prefix_explicit else configured.get(student.get('grade'),prefix))).strip()
        pos=plan.get('seats',{}).get('base',{}).get(sid,{})
        room=next((r for r in plan['rooms'] if r['id']==pos.get('room_id')),{})
        row=dict(student_id=sid,name=student['name'],grade=student['grade'],class_name=student['class_name'],
                 room=room.get('name','未安排'),room_code=room.get('code',''),seat=pos.get('seat',''),
                 old_number=old,new_number=old,status='保留已有考号' if keep else '待生成')
        if not keep:
            try:
                if rule=='seat':
                    room,code,seat=location(plan,sid)
                    if not student_prefix or any(ord(c)<32 for c in student_prefix):raise ValueError('请填写有效的考号前缀。')
                    new=student_prefix+code+seat
                    row.update(room_code=code,seat=seat)
                    source=dict(prefix=student_prefix,room_id=room['id'],number=new)
                else:
                    while student_prefix+str(n).zfill(width) in used:n+=1
                    new=student_prefix+str(n).zfill(width);n+=1;used.add(new);source=None
                prospective[sid]=new;row['new_number']=new
                row['status']='不变' if new==old else ('重新生成' if old else '补充考号')
                changed[sid]=source
            except ValueError as e:
                row['status']=str(e);issue('number_location',str(e),sid)
        rows.append(row)
    groups=defaultdict(list)
    for sid,value in prospective.items():
        if value:groups[value].append(sid)
    names={s['id']:s['name']+'（'+s['class_name']+'）' for s in plan['students']}
    for value,ids in groups.items():
        if len(ids)>1:
            issue('number_duplicate',f'考号 {value} 重复：'+ '、'.join(names[x] for x in ids)+'。可按年级分别设置不同前缀，或使用不同考场编号。')
    errors.extend(x for x in source_issues(plan) if x['student_id'] not in changed)
    return dict(rows=rows,errors=errors,warnings=warnings,changes=sum(r['new_number']!=r['old_number'] for r in rows),
                prefix=prefix,prefixes=configured,rule=rule,grade=grade,overwrite=bool(overwrite),width=width,start=start,
                sources=changed,prospective=prospective)


def apply(plan,**options):
    result=preview(plan,**options)
    if result['errors']:raise ValueError(result['errors'][0]['message'])
    q=deepcopy(plan);sources=q.setdefault('number_sources',{})
    before={s['id']:s.get('number','') for s in q['students']}
    snapshot=dict(epoch=plan.get('history_epoch',0),before=before,after=result['prospective'],sources=deepcopy(sources),
                  settings={k:q['settings'].get(k) for k in ('number_prefix','number_rule','number_width','number_start','number_prefixes')})
    for student in q['students']:
        sid=student['id'];student['number']=result['prospective'][sid]
        if sid in result['sources']:
            if result['sources'][sid] is None:sources.pop(sid,None)
            else:sources[sid]=result['sources'][sid]
    q['settings'].update(number_prefix=result['prefix'],number_rule=result['rule'],number_prefixes=result['prefixes'])
    if result['grade']:q['settings']['number_prefixes'][result['grade']]=(options.get('prefixes') or {}).get(result['grade'],result['prefix'] if options.get('prefix') is not None else result['prefixes'].get(result['grade'],result['prefix']))
    if result['rule']=='serial':q['settings'].update(number_width=result['width'],number_start=result['start'])
    q.setdefault('number_history',[]).append(snapshot);q['number_history']=q['number_history'][-10:]
    return q


def undo(plan):
    q=deepcopy(plan)
    if not q.get('number_history'):raise ValueError('没有可以撤销的考号生成。')
    previous=q['number_history'][-1]
    if previous.get('epoch',0)!=q.get('history_epoch',0):raise ValueError('资料或规则已经改变，请重新核对考号；本次撤销不会覆盖后续修改。')
    if any(s.get('number','')!=previous['after'][s['id']] for s in q['students'] if s['id'] in previous['after']):
        raise ValueError('生成后有考号被人工修改，请先核对；本次撤销未覆盖这些修改。')
    q['number_history'].pop()
    for s in q['students']:
        if s['id'] in previous['before']:s['number']=previous['before'][s['id']]
    q['number_sources']=previous['sources'];q['settings'].update(previous['settings'])
    return q
