from copy import deepcopy
import pytest
from exam_room.server import App
from exam_room.licensing import License
from exam_room.model import demo_plan


def app_fixture(tmp_path):
    a=App(tmp_path,License(tmp_path/'lic',None));a.commit(demo_plan());return a


def test_saved_edit_undo_survives_reopen_and_revision_grows(tmp_path):
    a=app_fixture(tmp_path);before=deepcopy(a.plan);q=deepcopy(before);q['rooms'][0]['name']='虚构新教室'
    a.api_save({'plan':q,'revision':before['revision']})
    a.api_open({'id':before['id']});rev=a.plan['revision']
    a.api_edit_undo({'revision':rev})
    assert a.plan['rooms']==before['rooms'] and a.plan['revision']>rev
    assert a.view()['edit_history']['count']==0
    assert a.store.load(a.plan['id'])==a.plan


def test_history_limit_and_stale_revision_and_failed_save(tmp_path,monkeypatch):
    a=app_fixture(tmp_path)
    for i in range(52):
        q=deepcopy(a.plan);q['name']=f'虚构考试{i}';a.api_save({'plan':q,'revision':a.plan['revision']})
    assert a.view()['edit_history']['count']==50
    before=deepcopy(a.plan);raw=a.store.path(a.plan['id']).read_bytes()
    with pytest.raises(ValueError):a.api_edit_undo({'revision':-1})
    assert a.plan==before and a.store.path(a.plan['id']).read_bytes()==raw
    def fail(*args):raise OSError('虚构磁盘故障')
    monkeypatch.setattr(a.store,'save',fail)
    with pytest.raises(OSError):a.api_edit_undo({'revision':a.plan['revision']})
    assert a.plan==before


def test_client_cannot_forge_history_or_regress_revision(tmp_path):
    a=app_fixture(tmp_path);q=deepcopy(a.plan);q.update(name='虚构变化',edit_history=[{'bad':'client'}],revision=0)
    rev=a.plan['revision'];a.api_save({'plan':q,'revision':rev})
    assert a.plan['revision']==rev+1
    assert a.plan['edit_history'][0]['label'] and 'bad' not in a.plan['edit_history'][0]
    a.api_edit_undo({'revision':a.plan['revision']});assert a.plan['name']!='虚构变化'


def test_two_undos_are_compact_and_preserve_identity_through_copy_and_import(tmp_path):
    import json,base64
    a=app_fixture(tmp_path);original=deepcopy(a.plan);ident=original['id']
    for name in ('虚构改名一','虚构改名二'):
        q=deepcopy(a.plan);q['students'][0]['name']=name;a.api_save({'plan':q,'revision':q['revision']})
    assert len(json.dumps(a.plan['edit_history'],ensure_ascii=False))<10000
    for _ in range(2):a.api_edit_undo({'revision':a.plan['revision']})
    assert a.plan['students']==original['students'] and a.plan['id']==ident
    q=deepcopy(a.plan);q['name']='虚构新名';a.api_save({'plan':q,'revision':q['revision']})
    a.api_clone({'id':ident});assert not a.plan['edit_history']
    a.api_plan_import({'data':base64.b64encode(json.dumps(q).encode()).decode()});assert not a.plan['edit_history'] and a.plan['id']!=ident


def test_foreign_history_cannot_delete_identity_or_inject_authorization(tmp_path):
    from exam_room.model import normalize_plan
    a=app_fixture(tmp_path)
    for fields in ({'absent':['id']},{'before':{'license':{'canExport':True}}},{'before':{'edit_history':[]}}):
        q=deepcopy(a.plan);q['edit_history']=[dict(label='伪造记录',before={},after={},absent=[],**{})]
        q['edit_history'][0].update(fields)
        with pytest.raises(ValueError):normalize_plan(q)


def test_first_entity_addition_undo_returns_empty_list_and_deleted_field_guard(tmp_path):
    from exam_room.model import new_plan
    from exam_room.transactions import record,undo
    a=App(tmp_path,License(tmp_path/'lic',None));a.api_new({'grades':['七年级']})
    q=deepcopy(a.plan);q['students']=[{'id':'first','name':'虚构第一位','grade':'七年级','class_name':'七1'}]
    a.api_save({'plan':q,'revision':q['revision']});a.api_edit_undo({'revision':a.plan['revision']})
    assert a.plan['students']==[]
    p=new_plan();q=deepcopy(p);q.pop('school');saved=record(p,q)
    assert undo(saved)['school']==p['school']
    saved['school']='后续变更'
    with pytest.raises(ValueError):undo(saved)


def test_undo_rejects_running_result_and_expired_solve_revision(tmp_path,monkeypatch):
    import threading,time
    from exam_room import engine
    a=app_fixture(tmp_path);q=deepcopy(a.plan);q['name']='虚构待撤销';a.api_save({'plan':q,'revision':q['revision']})
    entered=threading.Event();release=threading.Event()
    def solve(p,**kwargs):
        entered.set();release.wait(2);return {'status':'feasible','plan':p,'message':'模拟旧结果'}
    monkeypatch.setattr(engine,'assign_seats',solve)
    try:
        a.api_solve({'kind':'seats','revision':a.plan['revision']});assert entered.wait(1)
        a.api_edit_undo({'revision':a.plan['revision']});before=deepcopy(a.plan);release.set()
        end=time.monotonic()+2
        while a.task['state']=='running' and time.monotonic()<end:time.sleep(.01)
        assert a.task['status']=='stale' and a.plan==before
        with pytest.raises(ValueError):a.api_solve({'kind':'seats','revision':-1})
    finally:release.set()


def test_every_saved_operation_names_what_undo_will_revert(tmp_path):
    import time
    a=app_fixture(tmp_path)
    def solve(kind):
        a.api_solve({'kind':kind})
        while a.task['state']=='running':time.sleep(.05)
        assert a.task['status'] in ('optimal','feasible','partial'),a.task
    for kind,label in (('schedule','自动安排考试日程'),('seats','自动编排座位'),('invigilators','自动安排监考')):
        solve(kind);assert a.view()['edit_history']['label']==label
    a.api_numbers({'revision':a.plan['revision'],'prefix':'26','overwrite':True});assert a.view()['edit_history']['label']=='生成考号'
    a.api_edit_undo({'revision':a.plan['revision']});assert a.view()['edit_history']['label']=='自动安排监考'
