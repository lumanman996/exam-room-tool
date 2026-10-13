"""科目模板与实际考试分离；已确定的起止时间决定时长。"""
from copy import deepcopy
import re
from .model import uid,grade_name

BUILTIN=[dict(name=name,duration=minutes) for name,minutes in
         [('语文',120),('数学',120),('英语',120),('物理',90),('化学',60),('生物',60),('道德与法治',90),('历史',60),('地理',60),('体育',60)]]


def minute(value):
    m=re.fullmatch(r'(\d{1,2}):(\d{2})',str(value))
    if not m or int(m[1])>23 or int(m[2])>59:raise ValueError('考试时间请填写 HH:MM。')
    return int(m[1])*60+int(m[2])


def duration(value):
    if isinstance(value,bool) or not re.fullmatch(r'[0-9]+',str(value)) or not 1<=int(value)<=1440:raise ValueError('考试时长须为 1～1440 的整数分钟。')
    return int(value)


def normalize_exam(raw):
    e=deepcopy(raw)
    if e.get('start') and e.get('end'):
        a,b=minute(e['start']),minute(e['end'])
        if b<=a:raise ValueError('结束时间须晚于开始时间。')
        e['duration']=b-a
        e['start']=f'{a//60:02}:{a%60:02}';e['end']=f'{b//60:02}:{b%60:02}'
    else:
        e['duration']=duration(e.get('duration',90))
        for k in ('start','end'):
            if e.get(k):minute(e[k])
    return e


def catalog(value):
    if not isinstance(value,list):raise ValueError('科目预设须为列表。')
    result=[];seen=set()
    for r in value:
        if not isinstance(r,dict) or not isinstance(r.get('name'),str) or not r['name'].strip():raise ValueError('科目名称不能为空。')
        name=r['name'].strip()
        if name in seen:raise ValueError('科目预设名称不能重复。')
        seen.add(name);result.append(dict(name=name,duration=duration(r.get('duration',90))))
    return result


def batch(plan,body):
    grades=body.get('grades');selected=body.get('subjects')
    if not isinstance(grades,list) or not grades or not isinstance(selected,list) or not selected:raise ValueError('请选择年级和科目。')
    grades=[grade_name(g) for g in grades]
    if any(g not in plan['grades'] for g in grades):raise ValueError('请选择本次考试已设置的年级。')
    presets={r['name']:r['duration'] for r in plan['subject_catalog']};seen={(e['grade'],e['subject']) for e in plan['exams']}
    additions=[];duplicates=[]
    for g in grades:
        for raw in selected:
            if isinstance(raw,str):name=raw.strip();planned=presets.get(name,90)
            elif isinstance(raw,dict):name=str(raw.get('name','')).strip();planned=raw.get('duration',presets.get(name,90))
            else:raise ValueError('科目须为名称或名称与时长对象。')
            if not name:raise ValueError('科目名称不能为空。')
            e=normalize_exam(dict(id=uid(),grade=g,subject=name,duration=body.get('duration',planned),
                date=body.get('date',''),start=body.get('start',''),end=body.get('end','')))
            key=(g,name)
            if key in seen:duplicates.append(dict(grade=g,subject=name));continue
            additions.append(e);seen.add(key)
    return dict(exams=additions,duplicates=duplicates)
