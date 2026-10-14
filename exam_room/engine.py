"""考试、座位与监考的本机编排。所有公开操作均返回副本。

求解状态来自 CP-SAT；座位顺序的班级分散使用确定性局部改进，故仅称可行。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
from itertools import combinations
import math
import random
import threading
import time

from ortools.sat.python import cp_model

from . import diagnosis


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _minute(value):
    try:
        h, m = str(value).split(':')
        h, m = int(h), int(m)
        return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None
    except (ValueError, TypeError):
        return None


def _score(plan,student):
    field=plan.get('settings',{}).get('score_field')
    value=student.get('original',{}).get(field) if field else student.get('score')
    try:
        score=float(value)
        return score if math.isfinite(score) else None
    except (TypeError,ValueError):return None


def _event(item):
    try:
        d = str(item.get('date', ''))
        date.fromisoformat(d)
    except (ValueError, TypeError):
        return None
    a, b = _minute(item.get('start')), _minute(item.get('end'))
    return (d, a, b) if a is not None and b is not None and a < b else None


def _overlap(a, b):
    return bool(a and b and a[0] == b[0] and a[1] < b[2] and b[1] < a[2])


def _available(room, event):
    windows = room.get('availability', [])
    return not windows or any(w and w[0] == event[0] and w[1] <= event[1] and w[2] >= event[2]
                              for w in map(_event, windows))


def _mix(plan, grade_a, grade_b):
    if grade_a == grade_b:
        return True
    s = plan.get('settings', {})
    return bool(s.get('mix_grades') and (not s.get('mix_groups') or any(
        grade_a in g and grade_b in g for g in s['mix_groups'])))


def _compatible(plan, grade_a, event_a, grade_b, event_b):
    return not _overlap(event_a, event_b) or (event_a == event_b and _mix(plan, grade_a, grade_b))


def seat_layout(room):
    from .seat_labels import layout
    return layout(room)


def participants(plan, exam):
    return [s for s in plan.get('students', []) if s.get('grade') == exam.get('grade')
            and (not s.get('subjects') or exam.get('subject') in s['subjects'])]


def _seat_key(exam):
    return exam['id'] if exam.get('special_seating') else 'base'


def _mapping(plan, exam):
    return plan.get('seats', {}).get(_seat_key(exam), {})


def number_rule(plan):
    """考号方式：'seat' 按考场座位（默认，旧方案缺字段也按此处理），'serial' 流水号。"""
    return 'serial' if plan.get('settings', {}).get('number_rule') == 'serial' else 'seat'


def fixed_seat_students(plan):
    """需要固定座位的学生。按考场座位编考号时人人都要（考号由固定座位生成）；
    流水号方式下，只参加单独排座科目的学生不占固定座位。"""
    students = plan.get('students', [])
    if number_rule(plan) == 'seat':
        return list(students)
    ids = {s['id'] for e in plan.get('exams', []) if _seat_key(e) == 'base' for s in participants(plan, e)}
    return [s for s in students if s['id'] in ids]


def seat_rule_mismatch(plan):
    """按考场座位编考号，但固定座位是按流水号方式排的（有人共用座位或没有固定座位）时，返回中文提示。"""
    base = plan.get('seats', {}).get('base', {})
    if number_rule(plan) != 'seat' or not base:
        return None
    ids = {s['id'] for s in plan.get('students', [])}
    taken = Counter((pos.get('room_id'), pos.get('seat')) for sid, pos in base.items() if sid in ids)
    shared = sum(n for n in taken.values() if n > 1)
    missing = sum(1 for sid in ids if sid not in base)
    if not shared and not missing:
        return None
    detail = '、'.join(x for x in (f'{shared} 人共用座位' if shared else '', f'{missing} 人没有固定座位' if missing else '') if x)
    return f'当前座位按流水号方式编排（{detail}），按考场座位生成考号会重复或缺号。请重新编排座位，或改用流水号。'


def duties(plan):
    rooms = {r['id']: r for r in plan.get('rooms', [])}
    grouped = {}
    for exam in plan.get('exams', []):
        if not _event(exam):
            continue
        for s in participants(plan, exam):
            pos = _mapping(plan, exam).get(s['id'], {})
            rid = pos.get('room_id')
            if rid not in rooms:
                continue
            ident = '|'.join([rid, exam['date'], exam['start'], exam['end']])
            if ident not in grouped:
                grouped[ident] = dict(id=ident, room_id=rid, date=exam['date'], start=exam['start'], end=exam['end'],
                                      exam_ids=set(), student_ids=set(), subjects=set(), classes=set(), required=0)
            duty = grouped[ident]
            duty['exam_ids'].add(exam['id']); duty['student_ids'].add(s['id'])
            duty['subjects'].add(exam['subject']); duty['classes'].add(s.get('class_name', ''))
            required = exam.get('invigilators')
            if required is None:
                required = rooms[rid].get('invigilators')
            if required is None:
                required = plan.get('settings', {}).get('invigilators', 2)
            duty['required'] = max(duty['required'], max(0, _int(required, 2)))
    result = []
    for duty in grouped.values():
        for k in ('exam_ids', 'student_ids', 'subjects', 'classes'):
            duty[k] = sorted(duty[k])
        result.append(duty)
    return sorted(result, key=lambda d: (d['date'], d['start'], d['end'], d['room_id']))


def workload(plan):
    counts, minutes = Counter(), Counter()
    for duty in duties(plan):
        e = _event(duty)
        for ident in {a.get('teacher_id') for a in plan.get('invigilation', {}).get(duty['id'], []) if a.get('teacher_id')}:
            counts[ident] += 1
            minutes[ident] += e[2]-e[1]
    return [dict(teacher_id=t['id'], name=t.get('name', ''), count=counts[t['id']], minutes=minutes[t['id']])
            for t in plan.get('teachers', [])]


def _teacher_issue(plan, teacher, duty):
    settings = plan.get('settings', {})
    if any(_overlap(_event(duty), _event(x)) for x in teacher.get('unavailable', [])):
        return 'teacher_unavailable', '教师在这个时段不可用'
    if settings.get('avoid_subject', True) and set(teacher.get('subjects', [])) & set(duty['subjects']):
        return 'subject_avoidance', '教师需要回避自己任教的学科'
    if settings.get('avoid_class', True) and set(teacher.get('classes', [])) & set(duty['classes']):
        return 'class_avoidance', '教师需要回避自己任教的班级'
    return None


def _neighbors(room):
    layout = seat_layout(room)
    aisles = {_int(x) for x in room.get('aisles', [])}
    pairs = []
    for a, b in combinations(layout, 2):
        if a['row'] == b['row'] and abs(a['col']-b['col']) == 1:
            left, right = sorted([a, b], key=lambda x: x['col'])
            if left['desk'] != right['desk'] and left['desk'] in aisles:
                continue
            pairs.append((a['seat'], b['seat'], 4 if a['desk'] == b['desk'] else 1))
        elif a['col'] == b['col'] and abs(a['row']-b['row']) == 1:
            pairs.append((a['seat'], b['seat'], 1))
    return pairs


def validate(plan,include_stale=True):
    from .numbering import source_issues
    from .validation import data_issues,schedule_issues,annotate
    errors, warnings = [], []
    def add(code, message, warning=False, **ids):
        (warnings if warning else errors).append(dict(code=code, message=message, **ids))
    students, rooms, teachers, exams = (plan.get(k, []) for k in ['students','rooms','teachers','exams'])
    for key, items in [('students',students),('rooms',rooms),('teachers',teachers),('exams',exams)]:
        if not items:
            add('data_missing', {'students':'请先添加学生','rooms':'请先添加考场','teachers':'请先添加监考教师','exams':'请先添加考试'}[key], entity=key)
        ids = Counter(x.get('id') for x in items)
        for ident, count in ids.items():
            if not ident or count > 1:
                add('id_duplicate' if ident else 'id_missing','资料编号缺失或重复', entity=key, entity_id=ident)
    errors.extend(source_issues(plan));errors.extend(data_issues(plan));errors.extend(schedule_issues(plan))
    smap, rmap, tmap = ({x.get('id'): x for x in xs} for xs in [students, rooms, teachers])
    layouts = {r['id']: {x['seat']: x for x in seat_layout(r)} for r in rooms}
    nums, school_nums = defaultdict(list), defaultdict(list)
    names=defaultdict(list)
    for s in students:
        if s.get('name'):names[s['name']].append(s['id'])
        for field in ('name','grade','class_name'):
            if not str(s.get(field, '')).strip(): add('student_data','学生的姓名、年级和班级不能为空',student_id=s['id'])
        if not s.get('number'): add('number_missing','学生还没有考号',student_id=s['id'])
        else: nums[s['number']].append(s['id'])
        if s.get('student_no'): school_nums[s['student_no']].append(s['id'])
        if _score(plan,s) is None:add('missing_score','学生没有所选排序成绩，成绩排序时放在最后',True,student_id=s['id'])
    for values in (nums, school_nums):
        for value, ids in values.items():
            if len(ids)>1: add('number_duplicate' if values is nums else 'student_no_duplicate','考号或学籍号重复',student_ids=ids, value=value)
    for name,ids in names.items():
        if len(ids)>1:add('same_name','有同名学生，已按独立编号保留，请核对学号和班级',True,student_ids=ids)
    for r in rooms:
        total=max(0,_int(r.get('rows'))*_int(r.get('cols'))*_int(r.get('per_desk'),1))
        if not layouts[r['id']] or _int(r.get('capacity')) > total - len({x for x in r.get('disabled',[]) if isinstance(x,int) and 1 <= x <= total}):
            add('room_capacity','考场容量与可用座位不一致',room_id=r['id'])
        if any(not _event(w) for w in r.get('availability', [])): add('availability_time','考场可用时间格式不正确',room_id=r['id'])
    for t in teachers:
        if not t.get('name'): add('teacher_data','教师姓名不能为空',teacher_id=t['id'])
        if any(not _event(w) for w in t.get('unavailable', [])): add('availability_time','教师不可用时间格式不正确',teacher_id=t['id'])
    valid_exams=[]; occupants=[]; room_exam=defaultdict(list); student_events=defaultdict(list)
    for ex in exams:
        event=_event(ex)
        if not ex.get('grade') or not ex.get('subject'): add('exam_data','考试的年级和科目不能为空',exam_id=ex['id'])
        if not event:
            add('exam_time','考试日期或起止时间未安排或不正确',exam_id=ex['id'])
        else:
            valid_exams.append(ex)
            if event[2]-event[1] != _int(ex.get('duration')): add('exam_duration','考试时长与起止时间不一致',exam_id=ex['id'])
        members=participants(plan,ex)
        if not members: add('participants_missing','这场考试没有对应学生',exam_id=ex['id'])
        by_room=defaultdict(list); occupied={}
        mapping=_mapping(plan,ex)
        for s in members:
            if event: student_events[s['id']].append(ex)
            pos=mapping.get(s['id'])
            if not pos:
                add('seat_missing','学生还没有安排座位',student_id=s['id'],exam_id=ex['id']);continue
            rid, seat=pos.get('room_id'),pos.get('seat')
            if rid not in rmap or seat not in layouts.get(rid,{}):
                add('seat_invalid','座位不存在、已停用或超出容量',student_id=s['id'],exam_id=ex['id'],room_id=rid);continue
            if (rid,seat) in occupied: add('seat_duplicate','同一场考试有学生坐在相同座位',exam_id=ex['id'],room_id=rid,student_ids=[s['id'],occupied[rid,seat]])
            occupied[rid,seat]=s['id'];by_room[rid].append(s['id'])
            if event: occupants.append((rid,seat,s['id'],ex))
        for rid, ids in by_room.items():
            if len(ids)>len(layouts[rid]): add('capacity','学生人数超过考场容量',room_id=rid,exam_id=ex['id'])
            if event:
                if not _available(rmap[rid],event): add('room_unavailable','考场在考试时间不可用',room_id=rid,exam_id=ex['id'])
                room_exam[rid].append(ex)
            for a,b,w in _neighbors(rmap[rid]):
                x,y=occupied.get((rid,a)),occupied.get((rid,b))
                if x and y and smap[x].get('class_name')==smap[y].get('class_name'):
                    add('same_class_desk' if w==4 else 'same_class_adjacent','同班学生座位相邻，可按需要调整',True,room_id=rid,exam_id=ex['id'],student_ids=[x,y])
    for a,b in combinations(valid_exams,2):
        if a.get('grade')==b.get('grade') and _overlap(_event(a),_event(b)): add('grade_overlap','同一年级的考试时间重叠',exam_ids=[a['id'],b['id']])
    for sid, entries in student_events.items():
        for a,b in combinations(entries,2):
            if _overlap(_event(a),_event(b)): add('student_overlap','学生的两场考试时间重叠',student_id=sid,exam_ids=[a['id'],b['id']])
    for rid,entries in room_exam.items():
        for a,b in combinations(entries,2):
            if not _compatible(plan,a['grade'],_event(a),b['grade'],_event(b)):
                add('mixed_grade' if _event(a)==_event(b) else 'room_overlap','考场同时安排了不能合场的考试',room_id=rid,exam_ids=[a['id'],b['id']])
    by_position=defaultdict(list)
    for rid,seat,sid,ex in occupants: by_position[rid,seat].append((sid,ex))
    for (rid,seat), entries in by_position.items():
        for (sid,a),(tid,b) in combinations(entries,2):
            if a['id']!=b['id'] and sid!=tid and _overlap(_event(a),_event(b)): add('seat_duplicate','同时考试的学生占用同一座位',room_id=rid,seat=seat,student_ids=[sid,tid],exam_ids=[a['id'],b['id']])
    for key,mapping in plan.get('seats',{}).items():
        for sid in mapping:
            if sid not in smap: add('seat_student_unknown','座位表中含有已不存在的学生',student_id=sid,exam_id=key)
    mismatch=seat_rule_mismatch(plan)
    if mismatch: add('number_rule_mismatch',mismatch)
    ds=duties(plan); teacher_duties=defaultdict(list)
    for d in ds:
        placed={}
        for ex in exams:
            if ex['id'] not in d['exam_ids']:continue
            members={s['id'] for s in participants(plan,ex)}
            for sid in set(d['student_ids'])&members:
                pos=_mapping(plan,ex).get(sid,{})
                if pos.get('room_id')==d['room_id'] and _int(pos.get('seat'))>0:placed[sid]=pos['seat']
        ordered=sorted(placed,key=lambda sid:(placed[sid],sid));grades={smap[sid]['grade'] for sid in ordered if sid in smap}
        if len(grades)>1 and all(_mix(plan,a,b) for a,b in combinations(grades,2)):
            pairs=[(placed[a],placed[b]) for a,b in zip(ordered,ordered[1:]) if placed[a]!=placed[b] and smap[a]['grade']==smap[b]['grade']]
            if pairs:add('grade_interleave_limited','同年级学生在连续座号出现，请核对参试人数、时段与锁定位置：'+'、'.join(f'{a:02}—{b:02}' for a,b in pairs),True,duty_id=d['id'],room_id=d['room_id'],seat_pairs=pairs)
        arr=plan.get('invigilation',{}).get(d['id'],[])
        ids=[a.get('teacher_id') for a in arr if a.get('teacher_id')]
        if len(set(ids))<d['required']: add('invigilator_missing','这场监考尚未安排足够教师',duty_id=d['id'])
        if len(ids)>d['required']: add('invigilator_extra','监考教师人数超过要求',duty_id=d['id'])
        if len(ids)!=len(set(ids)): add('invigilator_duplicate','同一场监考重复安排了教师',duty_id=d['id'])
        for tid in set(ids):
            if tid not in tmap: add('teacher_unknown','监考表中的教师不存在',teacher_id=tid,duty_id=d['id']);continue
            issue=_teacher_issue(plan,tmap[tid],d)
            if issue: add(*issue,teacher_id=tid,duty_id=d['id'])
            teacher_duties[tid].append(d)
    for tid,entries in teacher_duties.items():
        for a,b in combinations(entries,2):
            if _overlap(_event(a),_event(b)): add('teacher_overlap','教师的两场监考时间重叠',teacher_id=tid,duty_ids=[a['id'],b['id']])
    for conflict in plan.get('pending_monitor_locks',[]):add('monitor_lock_conflict',('监考人数减少后存在超出位置的锁定教师，请明确解除旧锁定。' if conflict.get('kind')=='excess_slot' else '场次合并后原锁定教师冲突，请手动确定该监考位置。'),duty_id=conflict['duty_id'],index=conflict['index'],teacher_ids=conflict['teacher_ids'])
    work=workload(plan)
    if work and max(x['minutes'] for x in work)-min(x['minutes'] for x in work)>max([_int(e.get('duration')) for e in exams] or [0]):
        add('workload_imbalance','教师监考总时长差异较大',True)
    if include_stale:
        for item in plan.get('stale',[]):
            add('stale',{'seats':'资料或日程已修改，请重新编排或复核学生座位。','invigilation':'相关资料已修改，请重新编排或复核监考安排。','schedule':'允许时段或混考规则已修改，请重新安排或复核考试日程。'}.get(item,'方案已修改，请重新复核编排。'),scope=item)
    return annotate(dict(errors=errors,warnings=warnings,summary=dict(students=len(students),rooms=len(rooms),teachers=len(teachers),exams=len(exams),duties=len(ds),errors=len(errors),warnings=len(warnings),assigned_seats=len(plan.get('seats',{}).get('base',{})))))


def _result(plan,status,message):
    return dict(status=status,message=message,plan=deepcopy(plan))


def _initial(plan,cancel,stages=None):
    if cancel is not None and cancel.is_set():return _result(plan,'cancelled','已取消编排')
    if stages:
        from .validation import data_issues
        issues=[i for i in data_issues(plan) if i['stage'] in stages or i['code'] in ('grade_settings','grade_unknown')]
        if issues:return _result(plan,'infeasible',issues[0]['message'])
    if cancel is not None and cancel.is_set(): return _result(plan,'cancelled','已取消编排')
    if float(plan.get('settings',{}).get('time_limit',30))<=0: return _result(plan,'timeout','编排时间已用完，尚未找到方案')
    return None


def _solve(model,plan,cancel=None,progress=None):
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=max(0,float(plan.get('settings',{}).get('time_limit',30)))
    solver.parameters.num_search_workers=1
    solver.parameters.random_seed=_int(plan.get('settings',{}).get('seed'),42)%2147483647
    if model.proto.solution_hint.vars:
        # Symmetry/dual presolve can remove a legal warm start. Preserve it so
        # a complete arrangement is available while fairness is optimized.
        solver.parameters.keep_all_feasible_solutions_in_presolve=True
    finished=threading.Event()
    def watch():
        while not finished.wait(.05):
            if cancel is not None and cancel.is_set(): solver.stop_search();return
    watcher=threading.Thread(target=watch,daemon=True) if cancel is not None else None
    if watcher: watcher.start()
    if progress: progress('正在检查约束并寻找可行方案…')
    try: status=solver.solve(model)
    finally:
        finished.set()
        if watcher: watcher.join(timeout=.1)
    if cancel is not None and cancel.is_set(): return solver,'cancelled'
    return solver,{cp_model.OPTIMAL:'optimal',cp_model.FEASIBLE:'feasible',cp_model.INFEASIBLE:'infeasible',cp_model.UNKNOWN:'timeout',cp_model.MODEL_INVALID:'invalid'}[status]


def _message(status):
    return {'optimal':'编排完成，已达到本次目标最优值','feasible':'已找到符合规则的可行方案','infeasible':'现有条件下无法完成编排，请检查时间、容量和锁定条件','timeout':'编排时间已用完，尚未找到可行方案','cancelled':'已取消编排','invalid':'求解模型未通过检查，请保存方案并联系软件提供者；这不代表已证明无解'}[status]


def schedule(plan,cancel=None,progress=None):
    initial=_initial(plan,cancel,{'data','schedule','seats'})
    if initial: return initial
    exams=plan.get('exams',[]);rooms=plan.get('rooms',[])
    if not exams or not rooms: return _result(plan,'infeasible','请先添加考试和考场')
    model=cp_model.CpModel();choices={}; selected={}; allocations={};used={}; demand={}
    settings=plan.get('settings',{})
    windows=[x for x in map(_event,settings.get('slots',[])) if x]
    durations=sorted({_int(e.get('duration')) for e in exams if _int(e.get('duration'))>0})
    # Candidate starts include the end of any preceding exam. This permits
    # several subjects inside a morning/afternoon window without rounding time.
    offsets={0}
    for minute in range(1441):
        if minute in offsets:
            offsets.update(minute+d for d in durations if minute+d<=1440)
    for ei,ex in enumerate(exams):
        if cancel is not None and cancel.is_set():return _result(plan,'cancelled','已取消编排')
        duration=_int(ex.get('duration'))
        if duration<=0: return _result(plan,'infeasible','考试时长必须大于零')
        if ex.get('locked'):
            fixed=_event(ex)
            candidates=[fixed] if fixed and fixed[2]-fixed[1]==duration and any(w[0]==fixed[0] and w[1]<=fixed[1] and fixed[2]<=w[2] for w in windows) else []
        else:
            candidates=[]
            for e in windows:
                starts={e[1]+offset for offset in offsets if e[1]+offset+duration<=e[2]}
                starts.update(fixed[2] for other in exams if other.get('locked') and (fixed:=_event(other)) and fixed[0]==e[0] and e[1]<=fixed[2] and fixed[2]+duration<=e[2])
                candidates.extend((e[0],start,start+duration) for start in starts)
        candidates=sorted(set(x for x in candidates if x))
        members=participants(plan,ex);demand[ei]=len(members)
        if not members: return _result(plan,'infeasible','有考试没有对应学生，请检查年级和选考科目')
        locked=Counter()
        locked_positions=[]
        for s in members:
            pos=_mapping(plan,ex).get(s['id'],{})
            if pos.get('locked'):
                locked[pos.get('room_id')]+=1;locked_positions.append((s['id'],pos.get('room_id'),pos.get('seat')))
        choices[ei]=[]
        for ci,event in enumerate(candidates):
            available=[ri for ri,r in enumerate(rooms) if _available(r,event) and seat_layout(r)]
            if sum(len(seat_layout(rooms[ri])) for ri in available)<len(members): continue
            if any(not any(rooms[ri]['id']==rid for ri in available) for rid in locked): continue
            key=(ei,ci);choices[ei].append((key,event));selected[key]=model.new_bool_var(f'ex_{ei}_{ci}')
            counts=[]
            for ri in available:
                cap=len(seat_layout(rooms[ri])); n=model.new_int_var(0,min(cap,len(members)),f'n_{ei}_{ci}_{ri}')
                u=model.new_bool_var(f'u_{ei}_{ci}_{ri}')
                model.add(n<=cap*u);model.add(n>=u);model.add(u<=selected[key])
                if locked[rooms[ri]['id']]: model.add(n>=locked[rooms[ri]['id']]*selected[key])
                allocations[key,ri]=n;used[key,ri]=u;counts.append(n)
            model.add(sum(counts)==len(members)*selected[key])
        if not choices[ei]: return _result(plan,'infeasible',diagnosis.schedule_slot(plan,ex,members,windows))
        model.add_exactly_one(selected[k] for k,e in choices[ei])
    flat=[(ei,k,e) for ei,opts in choices.items() for k,e in opts]
    for (ei,k,a),(ej,j,b) in combinations(flat,2):
        if ei==ej or not _overlap(a,b): continue
        if exams[ei]['grade']==exams[ej]['grade']:
            model.add(selected[k]+selected[j]<=1)
        if not _compatible(plan,exams[ei]['grade'],a,exams[ej]['grade'],b):
            for ri in range(len(rooms)):
                if (k,ri) in used and (j,ri) in used: model.add(used[k,ri]+used[j,ri]<=1)
        # Locked seats may never put two pupils on one physical position.
        ma=_mapping(plan,exams[ei]);mb=_mapping(plan,exams[ej])
        pa={(v.get('room_id'),v.get('seat')):sid for sid,v in ma.items() if v.get('locked') and sid in {s['id'] for s in participants(plan,exams[ei])}}
        pb={(v.get('room_id'),v.get('seat')):sid for sid,v in mb.items() if v.get('locked') and sid in {s['id'] for s in participants(plan,exams[ej])}}
        if any(pa[pos]!=pb[pos] for pos in pa.keys() & pb.keys()): model.add(selected[k]+selected[j]<=1)
    indices={e['id']:i for i,e in enumerate(exams)}
    for group in settings.get('exam_groups',[]):
        ids=group.get('exam_ids',[])
        if len(set(ids))<2 or any(x not in indices for x in ids):return _result(plan,'infeasible','同时混考组包含无效考试。')
        for ia,ib in combinations([indices[x] for x in ids],2):
            if exams[ia]['grade']==exams[ib]['grade'] or exams[ia]['duration']!=exams[ib]['duration']:return _result(plan,'infeasible','同时混考组须为不同年级且时长一致。')
            for ka,ea in choices[ia]:
                for kb,eb in choices[ib]:
                    if ea!=eb:model.add(selected[ka]+selected[kb]<=1)
    for ri,r in enumerate(rooms):
        for day,start in sorted({(e[0],e[1]) for _,_,e in flat}):
            terms=[allocations[k,ri] for _,k,e in flat if e[0]==day and e[1]<=start<e[2] and (k,ri) in allocations]
            if terms: model.add(sum(terms)<=len(seat_layout(r)))
    dates=sorted({e[0] for _,_,e in flat});penalties=[]
    for grade in sorted({x['grade'] for x in exams}):
        counts=[]
        for day in dates:
            count=model.new_int_var(0,len(exams),f'day_{grade}_{day}')
            model.add(count==sum(selected[k] for ei,k,e in flat if exams[ei]['grade']==grade and e[0]==day));counts.append(count)
        hi=model.new_int_var(0,len(exams),f'max_{grade}');lo=model.new_int_var(0,len(exams),f'min_{grade}')
        model.add_max_equality(hi,counts);model.add_min_equality(lo,counts);penalties.append(hi-lo)
    # Day balance dominates a mild preference for earlier slots.
    early=sum(i*selected[k] for i,(_,k,e) in enumerate(flat))
    model.minimize(sum(penalties)*(len(flat)*len(exams)+1)+early)
    solver,status=_solve(model,plan,cancel,progress)
    q=deepcopy(plan)
    if status in ('optimal','feasible'):
        for ei,opts in choices.items():
            for k,e in opts:
                if solver.value(selected[k]):
                    q['exams'][ei].update(date=e[0],start=f'{e[1]//60:02}:{e[1]%60:02}',end=f'{e[2]//60:02}:{e[2]%60:02}')
    return _result(q,status,diagnosis.schedule(plan,windows) if status=='infeasible' else _message(status))


def _cohort_conflict(a,b):
    # Unscheduled pupils still need distinct base seats.
    return not a or not b or any(_overlap(x,y) for x in a for y in b)


def assign_seats(plan,cancel=None,progress=None,exam_id=None):
    initial=_initial(plan,cancel,{'data','schedule','seats'})
    if initial: return initial
    key=exam_id or 'base';exams=plan.get('exams',[]);rooms=plan.get('rooms',[])
    target=next((e for e in exams if e['id']==key),None) if key!='base' else None
    if key!='base' and target is None: return _result(plan,'infeasible','没有找到这场考试')
    if not rooms or not plan.get('students'): return _result(plan,'infeasible','请先添加学生和考场')
    if any(not _event(e) for e in exams): return _result(plan,'infeasible','请先安排完整的考试时间，再编排座位')
    # 按考场座位编考号时，固定座位人人独占、不共用，考号必定不重复；流水号方式可共用，更省座位。
    exclusive=not target and number_rule(plan)=='seat'
    students=participants(plan,target) if target else fixed_seat_students(plan)
    if not students and not target:
        q=deepcopy(plan);q.setdefault('seats',{})['base']={}
        return _result(q,'feasible','流水号方式下没有学生需要固定座位；单独排座的科目请分别编排。')
    if not students: return _result(plan,'infeasible','这场考试没有对应学生')
    selected_ids={s['id'] for s in students}
    timelines=defaultdict(set)
    for e in exams:
        if (target and e['id']==key) or (not target and _seat_key(e)=='base'):
            for s in participants(plan,e):
                if s['id'] in selected_ids: timelines[s['id']].add(_event(e))
    grouped=defaultdict(list)
    for s in students: grouped[(s['grade'],tuple(sorted(timelines[s['id']])) )].append(s)
    groups=list(grouped.items());layouts={r['id']:seat_layout(r) for r in rooms}
    # 同一完整时段、年级不能混场时，人数除以最大单场容量给出必要场数。
    # 这是已证明的容量下界；不同时间可复用或允许混排时仍交给求解器。
    if key=='base' and groups and len({events for (grade,events),members in groups})==1:
        separate=all(not _mix(plan,a[0][0],b[0][0]) for a,b in combinations(groups,2))
        largest=max((len(layout) for layout in layouts.values()),default=0)
        if separate and largest:
            needed=sum((len(members)+largest-1)//largest for _,members in groups)
            if needed>len(rooms):
                return _result(plan,'infeasible',f'这些年级同时考试且不能混排，至少需要 {needed} 个考场，当前只有 {len(rooms)} 个。请增加考场，或调整考试时段、混排规则。')
    roommap={r['id']:r for r in rooms};order={r['id']:i for i,r in enumerate(rooms)}
    old=plan.get('seats',{}).get(key,{})
    # Occupied special-exam positions and other exams stay fixed during this operation.
    external=[]
    for e in exams:
        if (target and e['id']==key) or (not target and _seat_key(e)=='base'): continue
        for s in participants(plan,e):
            pos=_mapping(plan,e).get(s['id'])
            if pos: external.append((s,_event(e),pos))
    # 排固定座位时，把还没排的单独排座科目一并放进模型，只验证它们一定排得下，不替它们落座。
    # 这样固定座位不会占掉它们需要的考场或座位；单独编排这些科目时再实际安排。
    reserve=[]
    if not target:
        for e in exams:
            if not e.get('special_seating'):continue
            done=plan.get('seats',{}).get(e['id'],{})
            pending=defaultdict(list)
            for s in participants(plan,e):
                if s['id'] not in done:pending[(s['grade'],(_event(e),))].append(s)
            reserve+=[(cohort,members,e) for cohort,members in pending.items()]
    def build(reserved):
        model=cp_model.CpModel();variables={};used={};fixed={};position_groups=defaultdict(list)
        cohorts=groups+[(cohort,members) for cohort,members,_ in reserved];base_count=len(groups)
        for gi,((grade,events),members) in enumerate(cohorts):
            all_vars=[];locked_positions={}
            for s in (members if gi<base_count else ()):
                pos=old.get(s['id'],{})
                if pos.get('locked'):
                    p=(pos.get('room_id'),pos.get('seat'))
                    if p in locked_positions: return None,None,None,None,_result(plan,'infeasible','锁定座位重复，请先调整')
                    locked_positions[p]=s['id'];fixed[s['id']]=deepcopy(pos)
            for r in rooms:
                rid=r['id']
                if any(not _available(r,e) for e in events): continue
                incompatible=any(pos.get('room_id')==rid and any(not _compatible(plan,grade,e,s['grade'],other) for e in events) for s,other,pos in external)
                if incompatible: continue
                room_vars=[]
                for seat in layouts[rid]:
                    number=seat['seat']
                    if events and any(pos.get('room_id')==rid and pos.get('seat')==number and _cohort_conflict(events,(other,)) for s,other,pos in external): continue
                    v=model.new_bool_var(f'seat_{gi}_{rid}_{number}')
                    variables[gi,rid,number]=v;room_vars.append(v);all_vars.append(v);position_groups[rid,number].append((gi,v))
                    if (rid,number) in locked_positions: model.add(v==1)
                if room_vars:
                    u=model.new_bool_var(f'room_{gi}_{rid}');used[gi,rid]=u
                    model.add(sum(room_vars)>=u);model.add(sum(room_vars)<=len(room_vars)*u)
            for p,sid in locked_positions.items():
                if (gi,*p) not in variables: return None,None,None,None,_result(plan,'infeasible','锁定座位不可用，或与其他考试冲突')
            if len(all_vars)<len(members):
                if gi>=base_count:return None,None,None,None,'reserve'
                return None,None,None,None,_result(plan,'infeasible',diagnosis.seats(plan,target and key))
            model.add(sum(all_vars)==len(members))
        for (rid,seat),entries in position_groups.items():
            for (a,x),(b,y) in combinations(entries,2):
                ea,eb=cohorts[a][0][1],cohorts[b][0][1]
                if a<base_count and b<base_count:clash=exclusive or _cohort_conflict(ea,eb)
                # 预留给单独排座科目的位置，只和同一时间真有人坐的座位冲突；没有固定座位场次的学生不会在场内。
                else:clash=bool(ea and eb) and any(_overlap(x,y) for x in ea for y in eb)
                if clash: model.add(x+y<=1)
        for a,b in combinations(range(len(cohorts)),2):
            (ga,ea),_ = cohorts[a];(gb,eb),_=cohorts[b]
            # 固定座位下没有场次的学生只需不重复的座号来生成考号，不会在场内同时考试，可与任何组同场。
            incompatible=bool(ea and eb) and any(not _compatible(plan,ga,x,gb,y) for x in ea for y in eb)
            if incompatible:
                for r in rooms:
                    rid=r['id']
                    if (a,rid) in used and (b,rid) in used: model.add(used[a,rid]+used[b,rid]<=1)
        # Prefer earlier rooms and seats without claiming class separation is globally optimal.
        model.minimize(sum((order[rid]*1000+n)*v for (gi,rid,n),v in variables.items() if gi<base_count))
        solver,status=_solve(model,plan,cancel,progress)
        return solver,status,variables,fixed,None
    solver,status,variables,fixed,failed=build(reserve)
    notice=''
    if reserve and (failed=='reserve' or status in ('infeasible','timeout')):
        # 固定座位和单独排座的科目无法同时排下（或限时内找不到）：只排固定座位，并说明后面哪些科目可能排不下。
        names='、'.join(dict.fromkeys(e.get('subject') or e['id'] for _,_,e in reserve))
        notice=f'注意：单独排座的科目（{names}）在这些固定座位下可能排不下，可增加考场、调整这些科目的时间，或延长求解时间后重新编排。'
        solver,status,variables,fixed,failed=build([])
    if isinstance(failed,dict):return failed
    if status not in ('optimal','feasible'): return _result(plan,status,diagnosis.seats(plan,target and key) if status=='infeasible' else _message(status))
    q=deepcopy(plan);mapping={};rng=random.Random(_int(plan.get('settings',{}).get('seed'),42));mode=plan.get('settings',{}).get('mode','class')
    positions_by_group={gi:sorted([(rid,n) for (g,rid,n),v in variables.items() if g==gi and solver.value(v)],key=lambda p:(order[p[0]],p[1])) for gi in range(len(groups))}
    # Interleave compatible grades in ascending seat order. Cohorts with different
    # subject participation/times keep their solver allocation; locks stay fixed.
    remaining=set(range(len(groups)))
    for first in range(len(groups)):
        if first not in remaining:continue
        cluster=[first]; remaining.remove(first)
        for gi in sorted(remaining):
            if groups[gi][0][1] and all(groups[gi][0][1]==groups[j][0][1] and _mix(plan,groups[gi][0][0],groups[j][0][0]) for j in cluster):
                cluster.append(gi)
        remaining.difference_update(cluster)
        if len(cluster)<2:continue
        locked_by_group={gi:[(fixed[s['id']]['room_id'],fixed[s['id']]['seat']) for s in groups[gi][1] if s['id'] in fixed] for gi in cluster}
        locked={pos for ps in locked_by_group.values() for pos in ps}
        free=sorted({pos for gi in cluster for pos in positions_by_group[gi]}-locked,key=lambda p:(order[p[0]],p[1]))
        counts={gi:len(positions_by_group[gi])-len(locked_by_group[gi]) for gi in cluster}
        for gi in cluster:positions_by_group[gi]=list(locked_by_group[gi])
        cursor=0
        while cursor<len(free):
            for gi in cluster:
                if counts[gi]:
                    positions_by_group[gi].append(free[cursor]);cursor+=1;counts[gi]-=1
    for gi,(cohort,members) in enumerate(groups):
        positions=sorted(positions_by_group[gi],key=lambda p:(order[p[0]],p[1]))
        locks={(v['room_id'],v['seat']) for s in members if (v:=fixed.get(s['id']))}
        available=[p for p in positions if p not in locks]
        rest=[s for s in members if s['id'] not in fixed]
        if mode=='score':
            rest.sort(key=lambda s:(_score(plan,s) is None,-(_score(plan,s) or 0),s['id']))
        elif mode=='number':
            def number_key(s):
                text=str(s.get('number','')).strip()
                return (2,0,'',s['id']) if not text else (0,int(text),text,s['id']) if text.isascii() and text.isdigit() else (1,0,text,s['id'])
            rest.sort(key=number_key)
        elif mode=='random':
            rest.sort(key=lambda s:s['id']);rng.shuffle(rest)
        else:
            queues=defaultdict(list)
            for s in sorted(rest,key=lambda s:s['id']): queues[s.get('class_name','')].append(s)
            rest=[]
            while queues:
                for cl in sorted(queues,key=lambda cl:(-len(queues[cl]),cl)):
                    rest.append(queues[cl].pop(0))
                    if not queues[cl]: del queues[cl]
        for s,p in zip(rest,available): mapping[s['id']]=dict(room_id=p[0],seat=p[1],locked=False)
        mapping.update({s['id']:fixed[s['id']] for s in members if s['id'] in fixed})
        if mode in ('random','class'):
            _separate_classes(members,mapping,roommap,rng,cancel)
        if cancel is not None and cancel.is_set(): return _result(plan,'cancelled','已取消编排')
    q.setdefault('seats',{})[key]=mapping
    if target: next(e for e in q['exams'] if e['id']==key)['special_seating']=True
    done='座位编排完成；已保留锁定座位，并尽量分散同班学生'
    if reserve and not notice:done+='；已为单独排座的科目预留位置'
    return _result(q,'feasible',done+('。'+notice if notice else ''))


def _separate_classes(members,mapping,rooms,rng,cancel):
    by_id={s['id']:s for s in members}
    occupied={(mapping[s['id']]['room_id'],mapping[s['id']]['seat']):s['id'] for s in members}
    neighbors=defaultdict(list)
    for rid in {p[0] for p in occupied}:
        for a,b,w in _neighbors(rooms[rid]):
            neighbors[rid,a].append(((rid,b),w));neighbors[rid,b].append(((rid,a),w))
    movable=[s['id'] for s in members if not mapping[s['id']].get('locked')]
    def local_cost(a,b):
        edges={}
        for p in (a,b):
            for other,w in neighbors[p]:
                edges[tuple(sorted((p,other)))]=w
        total=0
        for (x,y),w in edges.items():
            sx,sy=occupied.get(x),occupied.get(y)
            if sx and sy and by_id[sx]['class_name']==by_id[sy]['class_name']: total+=w
        return total
    for _ in range(2):
        for sid in movable:
            if cancel is not None and cancel.is_set(): return
            a=(mapping[sid]['room_id'],mapping[sid]['seat'])
            if not any(occupied.get(p) and by_id[occupied[p]]['class_name']==by_id[sid]['class_name'] for p,w in neighbors[a]): continue
            candidates=rng.sample(movable,min(len(movable),24))
            for tid in candidates:
                if sid==tid or by_id[sid]['class_name']==by_id[tid]['class_name']: continue
                b=(mapping[tid]['room_id'],mapping[tid]['seat']);before=local_cost(a,b)
                occupied[a],occupied[b]=tid,sid
                after=local_cost(a,b)
                if after<before:
                    mapping[sid].update(room_id=b[0],seat=b[1]);mapping[tid].update(room_id=a[0],seat=a[1]);break
                occupied[a],occupied[b]=sid,tid


def _invigilator_hint(ds,teachers,eligible,locked,cancel=None):
    """Deterministic legal matching hint; CP-SAT still checks every hard rule.

    Exact-time groups use augmenting paths, so flexible teachers do not strand
    narrower choices. Other overlapping groups and all future locks stay busy.
    Incomplete matching is only a hint, never a proof of personnel shortage.
    """
    events=[_event(d) for d in ds];index={t['id']:ti for ti,t in enumerate(teachers)}
    chosen=set();busy=defaultdict(list);minutes=Counter();counts=Counter()
    groups=defaultdict(list);choices=defaultdict(list)
    for di,ti in sorted(eligible):choices[di].append(ti)
    for di,d in enumerate(ds):
        groups[events[di]].append(di)
        for tid in locked[di]:
            ti=index[tid]
            if any(_overlap(events[di],events[other]) for other in busy[ti]):return None
            chosen.add((di,ti));busy[ti].append(di)
            minutes[ti]+=events[di][2]-events[di][1];counts[ti]+=1
    for event,indices in sorted(groups.items()):
        if cancel is not None and cancel.is_set():return None
        candidates={di:sorted((ti for ti in choices[di]
            if not any(_overlap(event,events[other]) for other in busy[ti])),
            key=lambda ti:(minutes[ti],counts[ti],ti)) for di in indices}
        slots=[(di,position) for di in indices for position in range(ds[di]['required']-len(locked[di]))]
        matched={}
        def augment(slot,seen):
            if cancel is not None and cancel.is_set():return False
            for ti in candidates[slot[0]]:
                if ti in seen:continue
                seen.add(ti)
                if ti not in matched or augment(matched[ti],seen):
                    matched[ti]=slot;return True
            return False
        for slot in sorted(slots,key=lambda s:(len(candidates[s[0]]),s)):
            augment(slot,set())
        for ti,(di,position) in matched.items():
            chosen.add((di,ti));busy[ti].append(di)
            minutes[ti]+=event[2]-event[1];counts[ti]+=1
    return chosen


def assign_invigilators(plan,cancel=None,progress=None):
    initial=_initial(plan,cancel,{'data','schedule','seats','monitors'})
    if initial: return initial
    if plan.get('pending_monitor_locks'):return _result(plan,'infeasible','监考合并后存在锁定冲突，请先手动确定锁定教师。')
    ds=duties(plan);teachers=plan.get('teachers',[])
    if not ds: return _result(plan,'infeasible','请先安排考试时间和学生座位')
    if not teachers:
        q=deepcopy(plan);q['invigilation']={d['id']:[dict(teacher_id='',locked=False) for _ in range(d['required'])] for d in ds}
        result=_result(q,'partial','没有可用教师，已列出全部待补监考位置')
        result['unfilled']=[dict(duty_id=d['id'],missing=d['required'],reasons=['尚未添加教师资料']) for d in ds]
        return result
    model=cp_model.CpModel();variables={};locked={};vacancies=[];tmap={t['id']:t for t in teachers}
    for di,d in enumerate(ds):
        locks=[a for a in plan.get('invigilation',{}).get(d['id'],[]) if a.get('locked') and a.get('teacher_id')]
        ids=[a['teacher_id'] for a in locks]
        if len(ids)>d['required'] or len(ids)!=len(set(ids)): return _result(plan,'infeasible','锁定的监考教师重复或超过所需人数')
        locked[di]=ids
        if any(tid not in tmap or _teacher_issue(plan,tmap[tid],d) for tid in ids): return _result(plan,'infeasible','锁定教师与时间或回避规则冲突')
        eligible=[]
        for ti,t in enumerate(teachers):
            if not _teacher_issue(plan,t,d):
                v=model.new_bool_var(f'teacher_{di}_{ti}');variables[di,ti]=v;eligible.append(v)
                if t['id'] in ids: model.add(v==1)
        vacant=model.new_int_var(0,d['required'],f'vacancies_{di}');vacancies.append(vacant)
        model.add(sum(eligible)+vacant==d['required'])
    # Any overlapping pair is active at the later start. Enforce the whole
    # active group once, rather than constructing every teacher/duty pair.
    # Half-open intervals still allow a teacher to finish and start at one time.
    events=[_event(d) for d in ds]
    overlap_groups={tuple(di for di,e in enumerate(events) if e[0]==day and e[1]<=start<e[2])
                    for day,start in {(e[0],e[1]) for e in events}}
    for group in sorted(overlap_groups):
        for ti in range(len(teachers)):
            active=[variables[di,ti] for di in group if (di,ti) in variables]
            if len(active)>1:model.add_at_most_one(active)
    consecutive=[]
    for a,b in combinations(range(len(ds)),2):
        ea,eb=events[a],events[b]
        if _overlap(ea,eb):continue
        adjacent=ea[0]==eb[0] and (0<=eb[1]-ea[2]<=30 or 0<=ea[1]-eb[2]<=30)
        if adjacent:
            for ti in range(len(teachers)):
                if (a,ti) not in variables or (b,ti) not in variables: continue
                x,y=variables[a,ti],variables[b,ti]
                both=model.new_bool_var(f'consecutive_{a}_{b}_{ti}');model.add(both>=x+y-1);consecutive.append(both)
    max_minutes=sum(_event(d)[2]-_event(d)[1] for d in ds);minute_counts=[];duty_counts=[]
    for ti,t in enumerate(teachers):
        minutes=model.new_int_var(0,max_minutes,f'minutes_{ti}');count=model.new_int_var(0,len(ds),f'count_{ti}')
        model.add(minutes==sum((_event(ds[di])[2]-_event(ds[di])[1])*v for (di,tj),v in variables.items() if tj==ti))
        model.add(count==sum(v for (di,tj),v in variables.items() if tj==ti));minute_counts.append(minutes);duty_counts.append(count)
    hi=model.new_int_var(0,max_minutes,'most_minutes');lo=model.new_int_var(0,max_minutes,'least_minutes')
    hc=model.new_int_var(0,len(ds),'most_count');lc=model.new_int_var(0,len(ds),'least_count')
    model.add_max_equality(hi,minute_counts);model.add_min_equality(lo,minute_counts)
    model.add_max_equality(hc,duty_counts);model.add_min_equality(lc,duty_counts)
    consecutive_bound=len(consecutive)+1
    fairness=(hi-lo)*(len(ds)+1)*consecutive_bound+(hc-lc)*consecutive_bound+sum(consecutive)
    fairness_bound=(max_minutes*(len(ds)+1)+len(ds)+1)*consecutive_bound
    model.minimize(sum(vacancies)*fairness_bound+fairness)
    hint=_invigilator_hint(ds,teachers,variables,locked,cancel)
    if cancel is not None and cancel.is_set():return _result(plan,'cancelled','已取消编排')
    if hint is not None:
        for key,v in variables.items():model.add_hint(v,int(key in hint))
        assigned=Counter(di for di,ti in hint)
        for di,v in enumerate(vacancies):model.add_hint(v,ds[di]['required']-assigned[di])
        hint_minutes=[sum(events[di][2]-events[di][1] for di,tj in hint if tj==ti) for ti in range(len(teachers))]
        hint_counts=[sum(tj==ti for di,tj in hint) for ti in range(len(teachers))]
        for v,value in zip(minute_counts,hint_minutes):model.add_hint(v,value)
        for v,value in zip(duty_counts,hint_counts):model.add_hint(v,value)
        for v,value in ((hi,max(hint_minutes)),(lo,min(hint_minutes)),(hc,max(hint_counts)),(lc,min(hint_counts))):model.add_hint(v,value)
    solver,status=_solve(model,plan,cancel,progress)
    q=deepcopy(plan)
    if status in ('optimal','feasible'):
        q['invigilation']={}
        for di,d in enumerate(ds):
            picked=[t['id'] for ti,t in enumerate(teachers) if (di,ti) in variables and solver.value(variables[di,ti])]
            old=plan.get('invigilation',{}).get(d['id'],[])
            arr=[None]*d['required']
            for index,a in enumerate(old):
                if a.get('locked') and a.get('teacher_id'):
                    if index>=len(arr): return _result(plan,'infeasible','锁定的监考位置超出人数要求')
                    arr[index]=deepcopy(a);picked.remove(a['teacher_id'])
            remaining=iter(picked)
            q['invigilation'][d['id']]=[a if a is not None else dict(teacher_id=next(remaining,''),locked=False) for a in arr]
        unfilled=[]
        for d in ds:
            missing=sum(not a['teacher_id'] for a in q['invigilation'][d['id']])
            if not missing:continue
            reasons=[]
            for t in teachers:
                issue=_teacher_issue(plan,t,d)
                if issue:reasons.append(t['name']+'：'+issue[1])
                elif any(other['id']!=d['id'] and _overlap(_event(other),_event(d)) and any(a['teacher_id']==t['id'] for a in q['invigilation'][other['id']]) for other in ds):
                    reasons.append(t['name']+'：同一时间已有监考任务')
            unfilled.append(dict(duty_id=d['id'],missing=missing,reasons=reasons or ['符合条件的教师数量不足']))
        if unfilled:
            q['unfilled_invigilators']=unfilled
            result=_result(q,'partial',f'已安排可用教师，仍缺 {sum(d["missing"] for d in unfilled)} 个监考位置；回避规则保持生效')
            result.update(unfilled=unfilled,proved_minimum=status=='optimal');return result
        q.pop('unfilled_invigilators',None)
    return _result(q,status,_message(status))


def _history(plan,q,label):
    q['history']=(deepcopy(plan.get('history',[]))+[dict(label=label,epoch=plan.get('history_epoch',0),stale_seats=deepcopy(plan.get('stale_seats',[])),pending_monitor_locks=deepcopy(plan.get('pending_monitor_locks',[])),seats=deepcopy(plan.get('seats',{})),invigilation=deepcopy(plan.get('invigilation',{})),stale=deepcopy(plan.get('stale',[])),special_seating={e['id']:e.get('special_seating',False) for e in plan.get('exams',[])})])[-50:]


def _new_errors(before,after,codes):
    def fingerprint(issue): return repr(sorted(issue.items()))
    existing=Counter(fingerprint(i) for i in validate(before)['errors'] if i['code'] in codes)
    for issue in validate(after)['errors']:
        if issue['code'] not in codes: continue
        f=fingerprint(issue)
        if existing[f]: existing[f]-=1
        else: return issue
    return None


def adjust_seat(plan,student_id,room_id,seat,exam_id='base',swap=False,locked=None):
    students={s['id']:s for s in plan.get('students',[])};rooms={r['id']:r for r in plan.get('rooms',[])}
    if student_id not in students: raise ValueError('没有找到这名学生')
    if room_id not in rooms or seat not in {x['seat'] for x in seat_layout(rooms[room_id])}: raise ValueError('这个座位不存在、已停用或超出容量')
    exam_id=exam_id or 'base'
    if exam_id!='base':
        ex=next((e for e in plan.get('exams',[]) if e['id']==exam_id),None)
        if not ex or student_id not in {s['id'] for s in participants(plan,ex)}: raise ValueError('这名学生不参加这场考试')
    q=deepcopy(plan)
    if exam_id!='base' and exam_id not in q.get('seats',{}) and not ex.get('special_seating'):
        members={s['id'] for s in participants(plan,ex)}
        q.setdefault('seats',{})[exam_id]={sid:deepcopy(pos) for sid,pos in plan.get('seats',{}).get('base',{}).items() if sid in members}
    mapping=q.setdefault('seats',{}).setdefault(exam_id,{})
    previous=deepcopy(mapping.get(student_id))
    def timeline(sid):
        return [_event(e) for e in plan.get('exams',[]) if (_seat_key(e)==exam_id or (exam_id!='base' and e['id']==exam_id)) and sid in {s['id'] for s in participants(plan,e)}]
    myevents=timeline(student_id)
    others=[sid for sid,v in mapping.items() if sid!=student_id and v.get('room_id')==room_id and v.get('seat')==seat and _cohort_conflict(myevents,timeline(sid))]
    if others:
        if not swap or len(others)>1 or not previous: raise ValueError('座位已有人，请选择空位或交换座位')
        other=others[0]
        if mapping[other].get('locked'): raise ValueError('对方座位已锁定，请先解锁')
        mapping[other]=dict(previous,locked=False)
    mapping[student_id]=dict(room_id=room_id,seat=seat,locked=bool(previous and previous.get('locked')) if locked is None else bool(locked))
    if exam_id!='base': next(e for e in q['exams'] if e['id']==exam_id)['special_seating']=True
    hard={'seat_invalid','seat_duplicate','room_unavailable','room_overlap','mixed_grade','capacity','student_overlap'}
    issue=_new_errors(plan,q,hard)
    if issue: raise ValueError(issue['message'])
    # A room move changes which pupils a teacher supervises. Avoidance remains hard.
    issue=_new_errors(plan,q,{'subject_avoidance','class_avoidance','teacher_overlap','teacher_unavailable'})
    if issue: raise ValueError(issue['message'])
    _history(plan,q,'调整学生座位')
    return q


def adjust_invigilator(plan,duty_id,index,teacher_id,locked=False):
    ds={d['id']:d for d in duties(plan)};teachers={t['id']:t for t in plan.get('teachers',[])}
    if duty_id not in ds: raise ValueError('没有找到这场监考，请先安排时间和座位')
    duty=ds[duty_id]
    if not isinstance(index,int) or not 0<=index<duty['required']: raise ValueError('监考位置超出所需人数')
    if teacher_id:
        if teacher_id not in teachers: raise ValueError('没有找到这名教师')
        issue=_teacher_issue(plan,teachers[teacher_id],duty)
        if issue: raise ValueError(issue[1])
        for d in ds.values():
            for i,a in enumerate(plan.get('invigilation',{}).get(d['id'],[])):
                if d['id']==duty_id and i==index: continue
                if a.get('teacher_id')==teacher_id and _overlap(_event(d),_event(duty)): raise ValueError('这名教师在同一时间已有监考任务')
    q=deepcopy(plan);arr=q.setdefault('invigilation',{}).setdefault(duty_id,[])
    while len(arr)<=index: arr.append(dict(teacher_id='',locked=False))
    arr[index]=dict(teacher_id=teacher_id,locked=bool(locked) if teacher_id else False)
    _history(plan,q,'调整监考教师')
    return q
