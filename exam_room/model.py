"""方案规范化、稳定编号和虚构演示资料。"""
from copy import deepcopy
from datetime import datetime
import random
import re
from uuid import uuid4


def uid(): return uuid4().hex

def now(): return datetime.now().isoformat(timespec='seconds')

DEFAULTS = dict(mode='class', seed=42, mix_grades=False, mix_groups=[], invigilators=2,
                avoid_subject=True, avoid_class=True, number_prefix='', number_width=5,
                number_start=1, number_rule='seat', slots=[], time_limit=30, font_scale=1, score_field='',exam_groups=[],number_prefixes={},mix_presets=[])
ENTITY_DEFAULTS = {
    'students': dict(name='', grade='', class_name='', student_no='', number='', score=None, subjects=[], original={}),
    'rooms': dict(code='', name='', location='', rows=5, cols=6, per_desk=1, aisles=[], disabled=[], capacity=30,
                      order='straight', direction='horizontal', seat_labels={}, availability=[], invigilators=None),
    'teachers': dict(name='', subjects=[], classes=[], unavailable=[]),
    'exams': dict(grade='', subject='', duration=90, date='', start='', end='', locked=False, special_seating=False, invigilators=None),
}


def split_values(value):
    if isinstance(value, list): return value
    return [x.strip() for x in re.split(r'[,，、;；\n]+',str(value or '')) if x.strip()]


def grade_name(value):
    value=str(value or '').strip()
    for number,chinese,junior in ((7,'七','一'),(8,'八','二'),(9,'九','三')):
        if value in (str(number),f'{number}.0',chinese,f'{number}年级',chinese+'年级','初'+junior,'初'+str(number-6)):
            return chinese+'年级'
    return value


def normalize_grades(value):
    if not isinstance(value,list) or any(not isinstance(g,str) for g in value):raise ValueError('本次考试年级须为名称列表。')
    grades=[grade_name(g) for g in value]
    if any(not g for g in grades):raise ValueError('本次考试的年级名称不能为空。')
    if len(set(grades))!=len(grades):raise ValueError('本次考试的年级名称不能重复。')
    return grades


def plan_grades(plan):
    if 'grades' in plan:return normalize_grades(plan['grades'])
    return list(dict.fromkeys(grade_name(row.get('grade')) for kind in ('students','exams') for row in plan.get(kind,[]) if row.get('grade')))


def normalize_mix_groups(value,grades):
    if not isinstance(value,list):raise ValueError('混排组须为年级列表。')
    groups=[];seen=set()
    for group in value:
        names=normalize_grades(group)
        if len(names)<2:raise ValueError('每个混排组至少包含两个不同年级。')
        if any(g not in grades for g in names):raise ValueError('混排组只能使用本次考试已设置的年级。')
        if seen.intersection(names):raise ValueError('同一个年级不能出现在多个混排组中。')
        seen.update(names);groups.append(names)
    return groups


def normalize_mix_presets(value,grades):
    if not isinstance(value,list):raise ValueError('已保存的年级组须为方案列表。')
    presets=[];seen=set()
    for row in value:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not isinstance(row.get('name'),str):raise ValueError('年级组方案须包含稳定编号、名称和年级组。')
        ident=row['id'].strip();name=row['name'].strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',ident) or ident in seen or not name:raise ValueError('年级组方案的编号须唯一，名称不能为空。')
        groups=normalize_mix_groups(row.get('groups'),grades)
        if not groups:raise ValueError('具名混排方案至少设置一个混排组。')
        presets.append(dict(id=ident,name=name,groups=groups));seen.add(ident)
    return presets


def new_plan(name='未命名考试'):
    return dict(version=1,id=uid(),name=name,school='',created_at=now(),updated_at=now(),
                grades=[],grade_review_required=False,
                students=[],rooms=[],teachers=[],exams=[],settings=deepcopy(DEFAULTS),
                seats={'base':{}},invigilation={},edit_history=[],history=[],number_sources={},number_history=[],report_layouts={},history_epoch=0,change_log=[],revision=0)


def normalize_plan(raw):
    if not isinstance(raw,dict) or raw.get('version',1)!=1:
        raise ValueError('这份方案的格式版本不受支持，请使用相应版本的软件打开。')
    p=new_plan(); p.update(deepcopy(raw))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',str(p['id'])): raise ValueError('方案编号不正确。')
    p['name']=str(p.get('name') or '未命名考试').strip()[:100]
    if not isinstance(p.get('settings',{}),dict):raise ValueError('方案设置须为字段对象。')
    p['settings']={**deepcopy(DEFAULTS),**p.get('settings',{})}
    for kind,defaults in ENTITY_DEFAULTS.items():
        if not isinstance(p[kind],list): raise ValueError('资料应为列表。')
        rows=[]; seen=set()
        for raw_row in p[kind]:
            if not isinstance(raw_row,dict):raise ValueError('每条资料须为字段对象。')
            row={**deepcopy(defaults),**raw_row}; row['id']=str(row.get('id') or uid())
            if row['id'] in seen: raise ValueError('资料中出现重复的内部编号，请检查重复行。')
            seen.add(row['id'])
            for k in ('name','grade','class_name','number','student_no','code','location','subject'):
                if k in row: row[k]=str(row[k] or '').strip()
            if 'grade' in row:row['grade']=grade_name(row['grade'])
            for k in ('subjects','classes','aisles','disabled'):
                if k in row: row[k]=split_values(row[k])
            for k in ('aisles','disabled'):
                if k in row: row[k]=[int(x) for x in row[k]]
            for k in ('rows','cols','per_desk','capacity'):
                if k in row: row[k]=int(row[k])
            for k in ('availability','unavailable'):
                if k in row and not isinstance(row[k],list): raise ValueError('时段格式不正确。')
            if kind=='rooms':
                from .seat_labels import validate_labels
                validate_labels(row)
            if kind=='exams':
                from .subjects import normalize_exam
                row=normalize_exam(row)
            if kind=='students':
                if not isinstance(row.get('original'),dict):raise ValueError('学生原始资料须为字段对象。')
                try: row['score']=float(row['score']) if row['score'] not in ('',None) else None
                except (ValueError,TypeError): row['score']=None
                if row['score'] is not None:
                    import math
                    if not math.isfinite(row['score']): row['score']=None
            rows.append(row)
        p[kind]=rows
    if 'grades' not in raw:
        p['grades']=list(dict.fromkeys(row['grade'] for kind in ('students','exams') for row in p[kind] if row['grade']))
        p['grade_review_required']=True
    p['grades']=normalize_grades(p['grades'])
    if not isinstance(p['grade_review_required'],bool):raise ValueError('年级核对提示须为是或否。')
    p['settings']['mix_groups']=normalize_mix_groups(p['settings']['mix_groups'],p['grades'])
    p['settings']['mix_presets']=normalize_mix_presets(p['settings']['mix_presets'],p['grades'])
    if not isinstance(p.get('seats'),dict) or not isinstance(p.get('invigilation'),dict):raise ValueError('座位与监考关联格式不正确。')
    for mapping in p['seats'].values():
        if not isinstance(mapping,dict):raise ValueError('座位方案须按学生编号关联。')
        for pos in mapping.values():
            if not isinstance(pos,dict) or isinstance(pos.get('seat'),bool) or not isinstance(pos.get('seat'),int):raise ValueError('座位号须为整数，座位关联须为字段对象。')
    for arr in p['invigilation'].values():
        if not isinstance(arr,list) or any(not isinstance(a,dict) for a in arr):raise ValueError('监考关联须为教师列表。')
    for key in ('slots','exam_groups','mix_groups'):
        if not isinstance(p['settings'][key],list):raise ValueError('时段、混考和混排设置须为列表。')
    if any(not isinstance(g,dict) or not isinstance(g.get('exam_ids',[]),list) for g in p['settings']['exam_groups']):raise ValueError('混考组须包含考试编号列表。')
    if not isinstance(p['settings']['number_prefixes'],dict):raise ValueError('年级考号前缀须为字段对象。')
    for key in ('revision','history_epoch'):
        value=p.get(key,0)
        if isinstance(value,bool) or not isinstance(value,int) or value<0:raise ValueError('方案版本编号须为非负整数。')
    for key in ('history','number_history','change_log','stale','stale_seats','pending_monitor_locks','edit_history'):
        if key not in p:p[key]=[]
        if not isinstance(p[key],list):raise ValueError('方案调整记录格式不正确。')
    for key in ('number_sources','report_layouts'):
        if not isinstance(p[key],dict):raise ValueError('考号来源或打印版式格式不正确。')
    for key in ('slots','mix_groups','exam_groups'):
        values=p['settings'][key]
        if key=='slots' and any(not isinstance(v,dict) for v in values):raise ValueError('考试允许时段须为日期、起止时间对象。')
        if key=='mix_groups' and any(not isinstance(v,list) or any(not isinstance(g,str) for g in v) for v in values):raise ValueError('混排组须为年级列表。')
        if key=='exam_groups' and any(any(not isinstance(x,str) for x in g.get('exam_ids',[])) for g in values):raise ValueError('混考组的考试编号须为文本。')
    for kind,key in (('rooms','availability'),('teachers','unavailable')):
        if any(any(not isinstance(v,dict) for v in row[key]) for row in p[kind]):raise ValueError('可用／不可用时段须为日期、起止时间对象。')
    from .subjects import catalog,BUILTIN
    p['subject_catalog']=catalog(p.get('subject_catalog',deepcopy(BUILTIN)))
    p['school']=str(p.get('school',''))
    p.setdefault('seats',{}).setdefault('base',{})
    p['edit_history']=p.get('edit_history',[])[-50:]
    from .transactions import valid_history
    valid_history(p['edit_history'])
    p['history']=p.get('history',[])[-50:]
    p['number_history']=p.get('number_history',[])[-10:]
    return p


def generate_numbers(plan):
    p=deepcopy(plan); s=p['settings']; used=[x['number'] for x in p['students'] if x['number']]
    if len(used)!=len(set(used)): raise ValueError('已有考号重复，请先修改重复考号。')
    used=set(used); n=int(s['number_start']); width=int(s['number_width'])
    if n<0 or not 1<=width<=20: raise ValueError('起始流水号须非负，位数须为 1～20。')
    for student in p['students']:
        if student['number']: continue
        while True:
            number=str(s['number_prefix'])+str(n).zfill(width); n+=1
            if number not in used: break
        student['number']=number; used.add(number)
    return p


def demo_plan(large=False):
    p=new_plan('七八九年级期末考试 · 演示'); p['school']='示例中学（虚构）'
    p['grades']=['七年级','八年级','九年级']
    rng=random.Random(42); n=500 if large else 48
    for gi,g in enumerate(('七','八','九')):
        for i in range(n):
            p['students'].append(dict(id=f's{gi}-{i}',name=f'学生{g}{i+1:03}',grade=g+'年级',
                class_name=f'{g}{i//(50 if large else 16)+1}',number=f'{gi+7}{i+1:05}',score=rng.randint(150,600)))
        for si,sub in enumerate(('语文','数学','英语')):
            p['exams'].append(dict(id=f'e{gi}-{si}',grade=g+'年级',subject=sub,duration=90,
                date='2026-11-12' if si<2 else '2026-11-13',start='08:30' if si%2==0 else '14:00',
                end='10:00' if si%2==0 else '15:30'))
    for i in range(50 if large else 6):
        p['rooms'].append(dict(id=f'r{i}',code=f'{i+1:02}',name=f'第{i+1:02}考场',location=f'教学楼{i//10+1}层',
                              rows=5,cols=6,capacity=30))
    for i in range(120 if large else 18):
        p['teachers'].append(dict(id=f't{i}',name=f'教师{i+1:03}',subjects=[('物理','历史','体育')[i%3]],classes=[]))
    p['settings']['slots']=[dict(date=d,start=a,end=b) for d in ('2026-11-12','2026-11-13') for a,b in (('08:30','10:30'),('14:00','16:00'))]
    return normalize_plan(p)
