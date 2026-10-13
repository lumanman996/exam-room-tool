from copy import deepcopy
import pytest
from exam_room.model import normalize_plan,new_plan


def module():
    from exam_room import rooms
    return rooms


def test_batch_creates_padded_codes_and_independent_copies():
    p=normalize_plan(new_plan())
    template=dict(name='模板',rows=3,cols=4,per_desk=2,capacity=22,disabled=[2],aisles=[2],order='snake',location='一楼')
    result=module().batch(p,start=3,count=2,template=template)
    assert [x['code'] for x in result]==['03','04']
    assert [x['name'] for x in result]==['第03考场','第04考场']
    assert len({x['id'] for x in result})==2
    result[0]['aisles'].append(1)
    assert result[1]['aisles']==template['aisles']==[2]
    assert not p['rooms']


@pytest.mark.parametrize('start,count',[(0,1),(99,2),(100,1),(1,0),(1,1.5)])
def test_batch_limits_are_validated(start,count):
    with pytest.raises(ValueError):module().batch(normalize_plan(new_plan()),start=start,count=count)


def test_duplicate_codes_are_canonical_and_batch_is_atomic():
    p=new_plan();p['rooms']=[dict(id='r',name='已有考场',code='3')];p=normalize_plan(p)
    old=deepcopy(p)
    with pytest.raises(ValueError):module().batch(p,start=2,count=3)
    assert p==old


def test_preview_matches_engine_and_distinguishes_disabled_from_capacity():
    from exam_room.engine import seat_layout
    room=dict(name='测试',code='01',rows=2,cols=3,per_desk=2,capacity=10,disabled=[2,8],aisles=[2],order='snake')
    v=module().layout_preview(room)
    assert v['physical']==12 and v['enabled']==10 and v['capacity']==10
    assert len(v['positions'])==12
    assert {x['seat'] for x in v['positions'] if x['usable']}=={x['seat'] for x in seat_layout(room)}
    assert next(x for x in v['positions'] if x['seat']==7)['col']==6
    room['capacity']=8
    v=module().layout_preview(room)
    assert sum(x['disabled'] for x in v['positions'])==2
    assert sum(not x['usable'] and not x['disabled'] for x in v['positions'])==2


def test_disabling_seat_reduces_capacity_and_invalid_aisles_fail():
    room=dict(rows=5,cols=6,per_desk=1,capacity=30,disabled=[2],aisles=[3],order='straight')
    prepared=module().prepare_layout(room)
    assert prepared['capacity']==29
    room['aisles']=[6]
    with pytest.raises(ValueError):module().prepare_layout(room)
    room['aisles']=[];room['rows']=20
    with pytest.raises(ValueError):module().prepare_layout(room)


@pytest.mark.parametrize('count',[0,-1,1.5,21])
def test_room_monitor_count_is_not_silently_ignored(count):
    with pytest.raises(ValueError):module().prepare_layout(dict(invigilators=count))


def test_batch_service_uses_revision_and_layout_save_marks_seats_stale(tmp_path):
    from exam_room.server import App
    from exam_room.licensing import License
    from exam_room.model import demo_plan
    from exam_room import engine
    app=App(root=tmp_path,license=License(tmp_path/'lic',None))
    app.commit(engine.assign_seats(demo_plan())['plan'])
    rev=app.plan['revision'];prev=app.api_room_batch_preview(dict(start=7,count=2))
    assert prev['revision']==rev
    view=app.api_room_batch(dict(start=7,count=2,revision=rev))
    assert len(view['plan']['rooms'])==8
    with pytest.raises(ValueError):app.api_room_batch(dict(start=9,count=1,revision=rev))
    r=deepcopy(app.plan['rooms'][0]);r['disabled']=[1]
    with pytest.raises(ValueError,match='确认'):app.api_room_save(dict(room=r,revision=app.plan['revision']))
    app.api_room_save(dict(room=r,revision=app.plan['revision'],confirm_impact=True))
    assert app.plan['rooms'][0]['capacity']==29 and 'seats' in app.plan['stale']
