"""考场批量创建与布局编辑，座号及可用位置共用核心引擎。"""
from copy import deepcopy
import re
from .model import ENTITY_DEFAULTS,uid,split_values
from .numbering import two_digits


def integer(value,label,minimum,maximum):
    text=str(value).strip()
    if not re.fullmatch(r'[0-9]+',text) or not minimum<=int(text)<=maximum:
        raise ValueError(f'{label}须为 {minimum}～{maximum} 的整数。')
    return int(text)


def prepare_layout(raw):
    room={**deepcopy(ENTITY_DEFAULTS['rooms']),**deepcopy(raw)}
    room['rows']=integer(room['rows'],'桌行数',1,99)
    room['cols']=integer(room['cols'],'桌列数',1,99)
    room['per_desk']=integer(room['per_desk'],'每桌人数',1,4)
    total=room['rows']*room['cols']*room['per_desk']
    if total>99:raise ValueError('两位座位号最多支持 99 个座位，请减少桌行、桌列或每桌人数。')
    room['disabled']=sorted({integer(x,'停用座位号',1,total) for x in split_values(room['disabled'])})
    room['aisles']=sorted({integer(x,'过道前桌列',1,room['cols']-1) for x in split_values(room['aisles'])})
    if room['order'] not in ('straight','snake'):raise ValueError('请选择顺排或蛇形座号顺序。')
    if room['direction'] not in ('horizontal','vertical'):raise ValueError('请选择横排或竖排座号方向。')
    enabled=total-len(room['disabled'])
    if not enabled:raise ValueError('请至少保留一个启用座位。')
    room['capacity']=min(integer(room['capacity'],'使用容量',1,99),enabled)
    if room.get('invigilators') not in ('',None):
        room['invigilators']=integer(room['invigilators'],'每场监考人数',1,20)
    else:room['invigilators']=None
    from .seat_labels import validate_labels
    validate_labels(room)
    return room


def layout_preview(raw):
    from .engine import seat_layout
    room=prepare_layout(raw);total=room['rows']*room['cols']*room['per_desk']
    physical={**room,'disabled':[],'capacity':total}
    usable={x['seat'] for x in seat_layout(room)}
    positions=[dict(**x,disabled=x['seat'] in room['disabled'],usable=x['seat'] in usable) for x in seat_layout(physical)]
    positions.sort(key=lambda x:(x['row'],x['col']))
    return dict(room=room,physical=total,enabled=total-len(room['disabled']),capacity=room['capacity'],positions=positions)


def batch(plan,start=1,count=1,name_prefix='第',name_suffix='考场',template=None):
    start=integer(start,'起始考场编号',1,99);count=integer(count,'考场数量',1,99)
    if start+count-1>99:raise ValueError('考场编号不能超过 99，请减少数量或调整起始编号。')
    used={str(r.get('code','')).lstrip('0') for r in plan['rooms']}
    result=[];base=prepare_layout(template or ENTITY_DEFAULTS['rooms'])
    for n in range(start,start+count):
        if str(n) in used:raise ValueError(f'考场编号 {n:02} 已存在，请调整起始编号，避免重复。')
        r=deepcopy(base);r.update(id=uid(),code=f'{n:02}',name=str(name_prefix)+f'{n:02}'+str(name_suffix))
        result.append(r)
    return result


def prepare_room(plan,raw):
    room=prepare_layout(raw);room['code']=two_digits(room['code'],'考场编号')
    room['name']=str(room['name']).strip()
    if not room['name']:raise ValueError('请填写考场名称。')
    if any(r['id']!=room.get('id') and str(r.get('code','')).lstrip('0')==room['code'].lstrip('0') for r in plan['rooms']):
        raise ValueError('这个考场编号已存在，请使用不同编号。')
    room.setdefault('id',uid())
    return room
