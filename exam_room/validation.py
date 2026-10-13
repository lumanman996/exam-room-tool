"""统一的资料及阶段校验。允许保存缺项草稿，所有入口采用相同规则。"""
from collections import Counter,defaultdict
from datetime import date
import re

STAGES=('data','schedule','seats','numbers','monitors')


def grade_scope_issues(plan):
    from .model import grade_name,plan_grades,normalize_mix_groups,normalize_mix_presets
    issues=[]
    try:
        # 只有旧文件缺字段才兼容；明确空列表绝不按后续资料推导。
        grades=plan_grades(plan)
        normalize_mix_groups(plan.get('settings',{}).get('mix_groups',[]),grades)
        normalize_mix_presets(plan.get('settings',{}).get('mix_presets',[]),grades)
    except ValueError as exc:return [dict(code='grade_settings',message=str(exc),stage='data',field='grades',entity=None,entity_id=None)]
    for kind in ('students','exams'):
        for row in plan.get(kind,[]):
            if grade_name(row.get('grade')) not in grades:
                message=('请先设置本次考试年级，再导入学生和考试科目。' if not grades else f'年级“{row.get("grade","")}”不在本次考试年级清单中；请先修改清单或资料。')
                issues.append(dict(code='grade_unknown',message=message,stage='data',entity=kind,entity_id=row.get('id'),field='grade'))
    return issues

def event(value):
    try:
        day=str(value.get('date',''));date.fromisoformat(day)
        def minute(k):
            m=re.fullmatch(r'(\d{1,2}):(\d{2})',str(value.get(k,'')))
            if not m or int(m[1])>23 or int(m[2])>59:raise ValueError()
            return int(m[1])*60+int(m[2])
        start,end=minute('start'),minute('end')
        return (day,start,end) if start<end else None
    except (ValueError,TypeError,AttributeError):return None


def data_issues(plan):
    issues=grade_scope_issues(plan)
    def add(code,message,kind=None,row=None,field=None,**extra):
        ident=row.get('id') if row else None
        stage={'rooms':'seats','students':'seats','teachers':'monitors','exams':'schedule'}.get(kind,{'seat_mode':'seats','mix_group':'seats','monitor_count':'monitors'}.get(code,'data'))
        issues.append(dict(code=code,message=message,stage=stage,entity=kind,entity_id=ident,field=field,**extra))
    codes=defaultdict(list)
    for room in plan.get('rooms',[]):
        code=str(room.get('code','')).strip()
        if not re.fullmatch(r'[0-9]{1,2}',code) or not 1<=int(code)<=99:
            add('room_code','考场编号须为 01～99。','rooms',room,'code',room_id=room.get('id'))
        else:codes[int(code)].append(room.get('id'))
        try:
            from .rooms import prepare_layout
            prepare_layout(room)
        except (ValueError,TypeError,OverflowError) as e:add('room_layout',str(e),'rooms',room,'layout',room_id=room.get('id'))
        if not str(room.get('name','')).strip():add('room_name','请填写考场名称。','rooms',room,'name',room_id=room.get('id'))
    for code,ids in codes.items():
        if len(ids)>1:add('room_code_duplicate',f'考场编号 {code:02} 重复。','rooms',field='code',room_ids=ids)
    subjects=defaultdict(set)
    for ex in plan.get('exams',[]):subjects[ex.get('grade')].add(ex.get('subject'))
    for s in plan.get('students',[]):
        for field in ('name','grade','class_name'):
            if not str(s.get(field,'')).strip():add('student_data','学生的姓名、年级和班级不能为空。','students',s,field,student_id=s.get('id'))
        for sub in s.get('subjects',[]):
            if sub not in subjects.get(s.get('grade'),set()):
                add('subject_unknown',f'参试科目“{sub}”没有匹配本年级的考试日程。','students',s,'subjects',student_id=s.get('id'))
        if plan.get('exams') and s.get('grade') not in subjects:
            add('grade_no_exam','学生所属年级没有考试日程。','students',s,'grade',student_id=s.get('id'))
    for kind,key in [('rooms','availability'),('teachers','unavailable')]:
        for row in plan.get(kind,[]):
            for window in row.get(key,[]):
                if not event(window):add('availability_time','可用／不可用时段的日期、起止时间不正确。',kind,row,key)
    for teacher in plan.get('teachers',[]):
        if not str(teacher.get('name','')).strip():add('teacher_name','请填写教师姓名。','teachers',teacher,'name',teacher_id=teacher.get('id'))
    for ex in plan.get('exams',[]):
        for key in ('grade','subject'):
            if not str(ex.get(key,'')).strip():add('exam_data','请填写考试年级和科目。','exams',ex,key,exam_id=ex.get('id'))
        for key in ('duration','invigilators'):
            value=ex.get(key)
            if value is None and key=='invigilators':continue
            try:valid=not isinstance(value,bool) and int(value)==float(value) and 1<=int(value)<=(1440 if key=='duration' else 20)
            except (ValueError,TypeError,OverflowError):valid=False
            if not valid:add('exam_setting','考试时长须为 1～1440 分钟，监考人数须为 1～20。','exams',ex,key,exam_id=ex.get('id'))
    settings=plan.get('settings',{})
    if settings.get('mode','class') not in ('class','random','score','number'):add('seat_mode','请选择有效的编排方式。',field='mode')
    groups=settings.get('mix_groups',[])
    if not isinstance(groups,list) or any(not isinstance(g,list) or len(set(g))<2 for g in groups):add('mix_group','每个混排组至少包含两个不同年级。',field='mix_groups')
    try:
        n=settings.get('invigilators',2)
        if isinstance(n,bool) or int(n)!=float(n) or not 1<=int(n)<=20:raise ValueError()
    except (ValueError,TypeError,OverflowError):add('monitor_count','统一监考人数须为 1～20。',field='invigilators')
    return issues


def schedule_issues(plan):
    issues=[];slots=plan.get('settings',{}).get('slots',[])
    windows=[event(w) for w in slots]
    for i,w in enumerate(windows):
        if not w:issues.append(dict(code='slot_time',stage='schedule',message=f'第 {i+1} 个允许时段未填写完整或格式不正确。',slot_index=i))
    for ex in plan.get('exams',[]):
        when=event(ex)
        if when and slots and not any(w and w[0]==when[0] and w[1]<=when[1] and when[2]<=w[2] for w in windows):
            issues.append(dict(code='exam_outside_window',stage='schedule',message='考试时间超出已设置的允许时段。',exam_id=ex['id']))
    by_id={e['id']:e for e in plan.get('exams',[])}
    for group in plan.get('settings',{}).get('exam_groups',[]):
        ids=group.get('exam_ids',[]) if isinstance(group,dict) else []
        if len(set(ids))<2 or any(x not in by_id for x in ids):
            issues.append(dict(code='exam_group',stage='schedule',message='同时混考组须选择至少两场存在的考试。',exam_ids=ids));continue
        exams=[by_id[x] for x in ids]
        if len({e['grade'] for e in exams})!=len(exams) or len({e['duration'] for e in exams})!=1:
            issues.append(dict(code='exam_group_duration',stage='schedule',message='同时混考组须来自不同年级，并且考试时长相同。',exam_ids=ids))
        if all(event(e) for e in exams) and len({event(e) for e in exams})!=1:
            issues.append(dict(code='exam_group_time',stage='schedule',message='指定同时混考的考试起止时间须一致。',exam_ids=ids))
    return issues


def stage_for(issue):
    if issue.get('stage'):return issue['stage']
    code=issue.get('code','')
    if code.startswith('id_'):return {'teachers':'monitors','exams':'schedule'}.get(issue.get('entity'),'seats')
    if code=='data_missing':return {'teachers':'monitors','exams':'schedule','students':'seats','rooms':'seats'}.get(issue.get('entity'),'data')
    if code=='stale':return {'invigilation':'monitors','schedule':'schedule'}.get(issue.get('scope'),'seats')
    if code.startswith(('teacher_','invigilator_')) or code in ('subject_avoidance','class_avoidance','workload_imbalance','monitor_lock_conflict'):return 'monitors'
    if code.startswith('number_'):return 'numbers'
    if code.startswith(('exam_','grade_overlap','student_overlap','slot_','availability_time')):return 'schedule'
    return 'seats'


def annotate(result):
    grouped={s:dict(errors=[],warnings=[]) for s in STAGES}
    for level in ('errors','warnings'):
        for issue in result[level]:
            issue.setdefault('stage',stage_for(issue));grouped[issue['stage']][level].append(issue)
    result['stages']=grouped
    return result
