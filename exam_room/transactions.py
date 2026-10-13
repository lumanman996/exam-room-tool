"""方案级持久反向补丁；实体只存变动行，版本、许可及临时任务不回退。"""
from copy import deepcopy
import hashlib
import json
from .model import now

FIELDS={'name','school','grades','grade_review_required','students','rooms','teachers','exams','settings',
        'seats','invigilation','number_sources','report_layouts','history_epoch','change_log','stale','stale_seats',
        'pending_monitor_locks','subject_catalog'}
ENTITIES={'students','rooms','teachers','exams'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def valid_history(items):
    if not isinstance(items,list):raise ValueError('已保存撤销记录格式不正确。')
    for h in items:
        if (not isinstance(h,dict) or not isinstance(h.get('label'),str) or not isinstance(h.get('before'),dict)
            or not isinstance(h.get('after'),dict) or not isinstance(h.get('absent'),list)):
            raise ValueError('已保存撤销记录格式不正确。')
        if (set(h['before'])|set(h['after'])|set(h['absent'])|set(h.get('entities',{})))-FIELDS:
            raise ValueError('撤销记录不能回退方案编号、版本、许可或临时任务。')
        if any(not isinstance(v,str) or len(v)!=64 for v in h['after'].values() if v is not None):raise ValueError('撤销内容指纹格式不正确。')
        entities=h.get('entities',{})
        if not isinstance(entities,dict) or set(entities)-ENTITIES:raise ValueError('撤销实体补丁格式不正确。')
        for delta in entities.values():
            if not isinstance(delta,dict) or not isinstance(delta.get('rows'),dict) or not isinstance(delta.get('added'),list) or not (delta.get('order') is None or isinstance(delta.get('order'),list)):
                raise ValueError('撤销实体补丁格式不正确。')


def record(old,new,label='保存修改',kind='edit'):
    q=deepcopy(new);history=deepcopy(old.get('edit_history',[]));keys=[k for k in FIELDS if old.get(k)!=q.get(k)]
    if keys:
        before={};entities={}
        for k in keys:
            if k in ENTITIES:
                previous={r['id']:r for r in old[k]};current={r['id']:r for r in q[k]}
                order=[r['id'] for r in old[k]];new_order=[r['id'] for r in q[k]]
                entities[k]=dict(rows={ident:deepcopy(row) for ident,row in previous.items() if current.get(ident)!=row},
                                 added=sorted(set(current)-set(previous)),order=order if order!=new_order else None)
            elif k in old:before[k]=deepcopy(old[k])
        after={k:digest(q[k]) if k in q else None for k in keys}
        history.append(dict(label=label,kind=kind,at=now(),before=before,entities=entities,after=after,
                            absent=[k for k in keys if k not in old],revision=old['revision']+1))
    q['edit_history']=history[-50:];return q


def summary(plan):
    items=plan.get('edit_history',[]) if plan else []
    return dict(count=len(items),can_undo=bool(items),label=items[-1]['label'] if items else '',revision=plan['revision'] if plan else None)


def undo(plan):
    history=deepcopy(plan.get('edit_history',[]));valid_history(history)
    if not history:raise ValueError('没有可以撤销的已保存修改。')
    item=history.pop()
    if any((k in plan if v is None else k not in plan or digest(plan[k])!=v) for k,v in item['after'].items()):
        raise ValueError('方案内容已变化，不能用旧撤销记录覆盖后续修改。')
    q=deepcopy(plan)
    for k in item['absent']:q.pop(k,None)
    q.update(deepcopy(item['before']))
    for k,delta in item.get('entities',{}).items():
        rows={r['id']:deepcopy(r) for r in q[k] if r['id'] not in delta['added']};rows.update(deepcopy(delta['rows']))
        order=delta['order'] if delta['order'] is not None else [r['id'] for r in q[k]]
        if set(order)!=set(rows):raise ValueError('撤销资料关联不完整。')
        q[k]=[rows[ident] for ident in order]
    # Old partial snapshots must not jump over the unified transaction history.
    q['history']=[];q['number_history']=[];q['edit_history']=history
    return q
