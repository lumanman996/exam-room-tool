from copy import deepcopy
import pytest
from test_edit_history import app_fixture
from exam_room import engine


def test_grade_deletion_references_and_unused_batch(tmp_path):
    a=app_fixture(tmp_path);before=deepcopy(a.plan)
    with pytest.raises(ValueError,match='关联'):a.api_bulk_preview({'kind':'grades','action':'delete','ids':['七年级']})
    assert a.plan==before
    q=deepcopy(a.plan);q['grades']+=['十年级','十一年级'];a.api_save({'plan':q,'revision':q['revision']})
    pre=a.api_bulk_preview({'kind':'grades','action':'delete','ids':['十年级','十一年级']})
    a.api_bulk_apply({'kind':'grades','action':'delete','ids':['十年级','十一年级'],'revision':pre['revision']})
    assert '十年级' not in a.plan['grades']
    a.api_edit_undo({'revision':a.plan['revision']});assert '十年级' in a.plan['grades']


def test_room_batch_direct_template_and_atomic_invalid(tmp_path):
    a=app_fixture(tmp_path);body={'start':10,'count':2,'template':{'rows':2,'cols':2,'per_desk':2,'capacity':8,'location':'虚构楼'}}
    pre=a.api_room_batch_preview(body);assert len(pre['rooms'])==2 and pre['rooms'][0]['rows']==2
    a.api_room_batch({**body,'revision':pre['revision']})
    before=deepcopy(a.plan);raw=a.store.path(a.plan['id']).read_bytes()
    with pytest.raises(ValueError):a.api_bulk_apply({'kind':'rooms','action':'update','ids':['r0','r1'],'fields':{'cols':100},'revision':a.plan['revision']})
    assert a.plan==before and raw==a.store.path(a.plan['id']).read_bytes()
    with pytest.raises(ValueError):a.api_room_batch_preview(body)


def test_used_room_delete_and_shrink_require_explicit_impact_confirmation(tmp_path):
    a=app_fixture(tmp_path);a.commit(engine.assign_seats(a.plan)['plan']);q=deepcopy(a.plan)
    sid=next(iter(q['seats']['base']));rid=q['seats']['base'][sid]['room_id'];q['seats']['base'][sid]['locked']=True;a.commit(q)
    request={'kind':'rooms','action':'delete','ids':[rid]};pre=a.api_bulk_preview(request)
    assert pre['impact']['seats'] and pre['impact']['locked_seats']
    before=deepcopy(a.plan)
    with pytest.raises(ValueError,match='确认'):a.api_bulk_apply({**request,'revision':pre['revision']})
    assert a.plan==before
    a.api_bulk_apply({**request,'revision':pre['revision'],'confirm_impact':True})
    assert all(pos['room_id']!=rid for m in a.plan['seats'].values() for pos in m.values())
    a.api_edit_undo({'revision':a.plan['revision']});assert a.plan['seats']==before['seats']
    pre=a.api_bulk_preview({'kind':'rooms','action':'update','ids':[rid],'fields':{'rows':1,'cols':1,'capacity':1}})
    assert pre['requires_confirmation']


def test_preview_revision_and_default_scope(tmp_path):
    a=app_fixture(tmp_path);pre=a.api_bulk_preview({'kind':'rooms','action':'update','ids':['r0'],'fields':{'location':'新楼'}})
    q=deepcopy(a.plan);q['name']='新名';a.api_save({'plan':q,'revision':q['revision']})
    with pytest.raises(ValueError):a.api_bulk_apply({'kind':'rooms','action':'update','ids':['r0'],'fields':{'location':'新楼'},'revision':pre['revision']})
    d=a.api_defaults({'group':'monitors'});assert d['values']['invigilators']==2 and 'number_prefix' not in d['values']


def test_grade_aliases_are_not_counted_twice(tmp_path):
    a=app_fixture(tmp_path);q=deepcopy(a.plan);q['grades'].append('十年级');a.api_save({'plan':q,'revision':q['revision']})
    with pytest.raises(ValueError,match='重复'):a.api_bulk_preview({'kind':'grades','action':'delete','ids':['十年级','十年级 ']})


def test_room_availability_batch_is_atomic_and_route_preserves_disabled_place(tmp_path):
    from exam_room import engine
    a=app_fixture(tmp_path);q=deepcopy(a.plan);q['rooms'][0]['disabled']=[2];a.api_save({'plan':q,'revision':q['revision']})
    oldroom=deepcopy(a.plan['rooms'][0]);before={p['seat']:(p['row'],p['col']) for p in engine.seat_layout({**oldroom,'disabled':[],'capacity':30})}
    body={'kind':'rooms','action':'update','ids':['r0'],'fields':{'direction':'vertical'}}
    pre=a.api_bulk_preview(body);a.api_bulk_apply({**body,'revision':pre['revision']})
    room=a.plan['rooms'][0];after={p['seat']:(p['row'],p['col']) for p in engine.seat_layout({**room,'disabled':[],'capacity':30})}
    assert before[2]==after[room['disabled'][0]]
    before=deepcopy(a.plan)
    with pytest.raises(ValueError):a.api_bulk_preview({'kind':'rooms','action':'update','ids':['r0','r1'],'fields':{'availability':[{'date':'invalid','start':'10:00','end':'09:00'}]}})
    assert a.plan==before


def test_single_room_defaults_share_preview_confirmation_and_one_undo(tmp_path):
    a=app_fixture(tmp_path);a.commit(engine.assign_seats(a.plan)['plan'])
    a.api_seat_labels_apply({'room_id':'r0','first':1,'second':2,'revision':a.plan['revision']})
    before=deepcopy(a.plan);raw=deepcopy(a.plan['rooms'][0]);raw.update(a.api_defaults({'group':'room_layout'})['values']);raw.update(rows=6,cols=5)
    pre=a.api_room_change_preview({'room':raw,'reset_labels':True})
    assert pre['impact']['seats'] and pre['room']['rows']==6
    with pytest.raises(ValueError):a.api_room_save({'room':raw,'revision':pre['revision'],'reset_labels':True})
    assert a.plan==before
    a.api_room_save({'room':raw,'revision':pre['revision'],'reset_labels':True,'confirm_impact':True})
    a.api_edit_undo({'revision':a.plan['revision']});assert a.plan['rooms']==before['rooms']


def test_unrelated_edit_keeps_existing_seat_problem_for_checking(tmp_path):
    a=app_fixture(tmp_path);q=deepcopy(a.plan);sid=q['students'][0]['id'];q['seats']['base'][sid]={'room_id':'r0','seat':99,'locked':True};a.commit(q)
    before=deepcopy(a.plan['seats']);q=deepcopy(a.plan);q['teachers'][0]['name']='虚构新教师名'
    a.api_save({'plan':q,'revision':q['revision']})
    assert a.plan['seats']==before
    pre=a.api_bulk_preview({'kind':'rooms','action':'update','ids':['r1'],'fields':{'location':'虚构新楼'}})
    assert not pre['requires_confirmation'] and not pre['impact']['removed_seats']
    assert a.plan['seats']==before
