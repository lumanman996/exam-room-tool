"""座位物理坐标与可调整编号的共同布局；学生和锁定始终跟随物理位置。"""
from copy import deepcopy


def _int(value,default=0):
    try:return int(value)
    except (ValueError,TypeError,OverflowError):return default


def positions(room):
    rows,cols,per=(_int(room.get(k),d) for k,d in [('rows',5),('cols',6),('per_desk',1)])
    if min(rows,cols,per)<1 or rows*cols*per>100000:return []
    vertical=room.get('direction')=='vertical';outer,inner=(cols*per,rows) if vertical else (rows,cols*per)
    labels=room.get('seat_labels',{})
    result=[]
    for line in range(1,outer+1):
        for offset in range(inner):
            default=(line-1)*inner+offset+1
            step=inner-offset if room.get('order')=='snake' and line%2==0 else offset+1
            row,col=(step,line) if vertical else (line,step)
            result.append(dict(seat=labels.get(f'{row}:{col}',default),row=row,col=col,desk=(col-1)//per+1,side=(col-1)%per+1))
    return result


def validate_labels(room):
    labels=room.get('seat_labels',{})
    if not isinstance(labels,dict):raise ValueError('自定义座号须按物理行列对应。')
    if not labels:return
    total=room['rows']*room['cols']*room['per_desk']
    expected={f'{r}:{c}' for r in range(1,room['rows']+1) for c in range(1,room['cols']*room['per_desk']+1)}
    if set(labels)!=expected or any(isinstance(v,bool) or not isinstance(v,int) for v in labels.values()) or set(labels.values())!=set(range(1,total+1)):
        raise ValueError('自定义座号须完整、不重复且与当前行列一致；改变布局前请恢复默认座号。')


def layout(room):
    disabled={_int(x,-1) for x in room.get('disabled',[])}
    result=[p for p in positions(room) if p['seat'] not in disabled]
    cap=max(0,min(_int(room.get('capacity'),len(result)),len(result)))
    return sorted(result[:cap],key=lambda p:p['seat'])


def remap(plan,old_room,new_room):
    """Remap every subject and disabled label by the same physical coordinate."""
    old={p['seat']:(p['row'],p['col']) for p in positions(old_room)}
    new={(p['row'],p['col']):p['seat'] for p in positions(new_room)}
    for mapping in plan['seats'].values():
        for pos in mapping.values():
            if pos.get('room_id')==old_room['id'] and pos.get('seat') in old:
                if old[pos['seat']] not in new:raise ValueError('布局改变会移除已安排位置，请先预览并确认影响。')
                pos['seat']=new[old[pos['seat']]]


def prepare(plan,body):
    from .rooms import prepare_layout,integer
    old=next((r for r in plan['rooms'] if r['id']==body.get('room_id')),None)
    if not old:raise ValueError('考场已不存在。')
    prepare_layout(old);room=deepcopy(old)
    if body.get('action','swap')=='reset':room['seat_labels']={}
    elif body.get('action','swap')=='swap':
        first=integer(body.get('first'),'座位号',1,99);second=integer(body.get('second'),'座位号',1,99)
        usable={p['seat']:p for p in layout(room)}
        if first==second or first not in usable or second not in usable:raise ValueError('请选择当前考场两个不同的启用且容量内座位。')
        room['seat_labels']={f"{p['row']}:{p['col']}":p['seat'] for p in positions(room)}
        for value,target in [(first,second),(second,first)]:
            p=usable[value];room['seat_labels'][f"{p['row']}:{p['col']}"]=target
    else:raise ValueError('请选择交换座号或恢复默认座号。')
    # Reset can include formerly disabled labels: keep those physical places disabled.
    old_positions={p['seat']:(p['row'],p['col']) for p in positions(old)}
    new_positions={(p['row'],p['col']):p['seat'] for p in positions(room)}
    room['disabled']=[new_positions[old_positions[n]] for n in old['disabled']]
    q=deepcopy(plan);q['rooms']=[room if r['id']==room['id'] else r for r in q['rooms']];remap(q,old,room)
    q['history_epoch']=plan.get('history_epoch',0)+1
    changed=[dict(exam_id=key,student_id=sid,old_seat=pos['seat'],new_seat=q['seats'][key][sid]['seat'],locked=bool(pos.get('locked'))) for key,m in plan['seats'].items() for sid,pos in m.items() if pos.get('room_id')==room['id'] and pos['seat']!=q['seats'][key][sid]['seat']]
    from .numbering import source_issues
    return dict(plan=q,room=room,changes=changed,number_review=source_issues(q),positions=positions(room))
