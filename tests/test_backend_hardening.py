from copy import deepcopy
from pathlib import Path
import json
import pytest
from exam_room import engine, importer, report
from exam_room.model import normalize_plan
from exam_room.server import App
from exam_room.licensing import License
from exam_room.storage import Store
from test_engine import fixture_plan, good


def ready():
    p=normalize_plan(fixture_plan());p['school']='虚构测试中学'
    p=good(engine.assign_seats(p));return good(engine.assign_invigilators(p))


@pytest.mark.parametrize('change,code',[
    (lambda p:p['rooms'][0].update(code='100'),'room_code'),
    (lambda p:p['rooms'][0].update(cols=100,rows=1,capacity=100),'room_layout'),
    (lambda p:p['rooms'].append(dict(p['rooms'][0],id='r2')),'room_code_duplicate'),
    (lambda p:p['students'][0].update(subjects=['不存在的科目']),'subject_unknown'),
    (lambda p:p['exams'][0].update(start='12:00',end='13:30'),'exam_outside_window'),
])
def test_rules_apply_to_imported_and_loaded_plans(change,code):
    p=ready();change(p)
    assert code in {e['code'] for e in engine.validate(p)['errors']}


def test_import_preflight_reports_source_rows_and_rejects_partial_commit(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));app.api_new({'name':'虚构导入','grades':['七年级']})
    body=dict(kind='students',rows=[{'姓名':'甲','年级':'七','班级':'七1','学号':'001'}, {'姓名':'','年级':'七','班级':'七1','学号':'002'}],mapping={'name':'姓名','grade':'年级','class_name':'班级','student_no':'学号'},mode='append',revision=app.plan['revision'])
    pre=app.api_import_preflight(body)
    assert any(e['row']==2 and e['field']=='name' for e in pre['errors'])
    before=deepcopy(app.plan)
    with pytest.raises(ValueError):app.api_import(body)
    assert app.plan==before


def test_score_column_and_slots_invalidate_existing_results(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));app.commit(ready())
    p=deepcopy(app.plan);p['settings']['score_field']='另外成绩'
    assert 'seats' in app.api_save({'plan':p,'revision':p['revision']})['plan']['stale']
    p=deepcopy(app.plan);p['settings']['slots'][0]['end']='12:00'
    assert 'schedule' in app.api_save({'plan':p,'revision':p['revision']})['plan']['stale']


def test_schedule_change_preserves_locked_monitor_assignments(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));p=ready();d=engine.duties(p)[0]
    p['invigilation'][d['id']][0]['locked']=True;locked=p['invigilation'][d['id']][0]['teacher_id'];app.commit(p)
    q=deepcopy(app.plan);q['exams'][0].update(start='08:05',end='09:35')
    app.api_save({'plan':q,'revision':q['revision']})
    new=engine.duties(app.plan)[0]
    assert app.plan['invigilation'][new['id']][0]=={'teacher_id':locked,'locked':True}
    assert good(engine.assign_invigilators(app.plan))['invigilation'][new['id']][0]['teacher_id']==locked


def test_reimport_update_and_replace_keep_student_ids_and_prune_removed_refs(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));app.commit(ready());p=deepcopy(app.plan);sid=p['students'][0]['id'];student_no=p['students'][0]['student_no']
    body=dict(kind='students',mode='update',rows=[{'学号':student_no,'总分':42}],mapping={'student_no':'学号','score':'总分'},revision=app.plan['revision'])
    app.api_import(body)
    assert app.plan['students'][0]['id']==sid and app.plan['students'][0]['score']==42
    assert app.plan['students'][0]['name']==p['students'][0]['name']
    body.update(mode='replace',rows=[{'学号':student_no,'总分':43,'姓名':'虚构甲','年级':'七','班级':'七1'}],mapping={'student_no':'学号','score':'总分','name':'姓名','grade':'年级','class_name':'班级'},revision=app.plan['revision'])
    app.api_import(body)
    assert [s['id'] for s in app.plan['students']]==[sid]
    assert set(app.plan['seats']['base'])=={sid}


def test_corrupt_primary_can_be_recovered_without_destroying_backup(tmp_path):
    store=Store(tmp_path);p=ready();store.save(p);p['name']='虚构第二版';store.save(p)
    path=store.path(p['id']);path.write_text('{broken')
    info=store.recovery(p['id']);assert info['available'] and info['plan']['name']!='虚构第二版'
    restored=store.recover(p['id']);assert restored['name']==info['plan']['name']
    assert store.load(p['id'])['students']==p['students']


def test_dated_schedule_can_be_exported_before_monitoring_is_complete():
    p=ready();p['invigilation']={}
    assert report.build_excel(p,['schedule'])[:2]==b'PK'
    with pytest.raises(ValueError):report.build_excel(p,['invigilation'])


def test_undo_cannot_overwrite_seating_after_data_changed(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));app.commit(ready());students=app.plan['students'];a=app.plan['seats']['base'][students[0]['id']];b=app.plan['seats']['base'][students[1]['id']]
    app.api_adjust_seat({'student_id':students[0]['id'],'room_id':b['room_id'],'seat':b['seat'],'swap':True})
    p=deepcopy(app.plan);p['rooms'][0]['direction']='vertical';app.api_save({'plan':p,'revision':p['revision']})
    before=deepcopy(app.plan)
    with pytest.raises(ValueError,match='资料|规则'):app.api_undo({})
    assert app.plan==before


def test_grade_prefixes_are_saved_and_used_on_future_generations():
    from exam_room import numbering
    p=ready();s=p['students'][0];old=s['number'];s['number']=''
    q=numbering.apply(p,prefixes={'七年级':'001'},overwrite=False)
    assert q['settings']['number_prefixes']=={'七年级':'001'}
    assert q['students'][0]['number'].startswith('00101')
    q['students'][0]['number']=''
    r=numbering.apply(q)
    assert r['students'][0]['number']==q['number_sources'][s['id']]['number']


def test_locked_physical_position_is_kept_when_numbering_route_changes(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));p=ready();sid=p['students'][0]['id'];pos=p['seats']['base'][sid];pos['locked']=True
    coords={s['seat']:(s['row'],s['col']) for s in engine.seat_layout(p['rooms'][0])};before=coords[pos['seat']];app.commit(p)
    q=deepcopy(app.plan);q['rooms'][0]['direction']='vertical';app.api_save({'plan':q,'revision':q['revision']})
    coords={s['seat']:(s['row'],s['col']) for s in engine.seat_layout(app.plan['rooms'][0])}
    assert coords[app.plan['seats']['base'][sid]['seat']]==before
    assert app.plan['seats']['base'][sid]['locked']


def test_mixed_exam_group_automatically_uses_identical_time():
    p=ready();p['students']+= [dict(s,id='eight-'+s['id'],grade='八年级',class_name='八1',number='8'+s['number']) for s in p['students']]
    p['rooms'].append(dict(p['rooms'][0],id='r2',code='02'))
    p['exams'].append(dict(p['exams'][0],id='e2',grade='八年级',locked=False))
    p['settings'].update(mix_grades=True,exam_groups=[{'exam_ids':[p['exams'][0]['id'],'e2']}])
    q=good(engine.schedule(p))
    assert [(e['date'],e['start'],e['end']) for e in q['exams']][0]==[(e['date'],e['start'],e['end']) for e in q['exams']][1]
    p['exams'][1]['duration']=120
    assert engine.schedule(p)['status']=='infeasible'


def test_partial_seat_solve_does_not_clear_other_stale_schemes():
    from exam_room.changes import finish_seating
    p=ready();p['seats']['special']=deepcopy(p['seats']['base']);p.update(stale=['seats'],stale_seats=['base','special'])
    q=finish_seating(p,'special')
    assert 'seats' in q['stale'] and q['stale_seats']==['base']


def test_monitor_candidates_and_resolving_removed_locked_slot(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));app.commit(ready());d=engine.duties(app.plan)[0]
    p=deepcopy(app.plan);p['invigilation'][d['id']][1]['locked']=True;p['settings']['invigilators']=1
    app.api_save({'plan':p,'revision':p['revision']});assert app.plan['pending_monitor_locks']
    candidates=app.api_monitor_candidates({'duty_id':d['id'],'index':0})
    assert candidates['revision']==app.plan['revision'] and all('reasons' in t for t in candidates['teachers'])
    with pytest.raises(ValueError):app.api_monitor_lock_resolve({'duty_id':d['id'],'index':1,'revision':-1})
    app.api_monitor_lock_resolve({'duty_id':d['id'],'index':1,'revision':app.plan['revision'],'action':'discard'})
    assert not app.plan['pending_monitor_locks'] and len(app.plan['invigilation'][d['id']])==1


def test_save_failure_keeps_active_plan_and_import_row_indices(tmp_path,monkeypatch):
    app=App(tmp_path,License(tmp_path/'lic',None));app.commit(ready());before=deepcopy(app.plan)
    def broken(p):raise OSError('模拟磁盘故障')
    monkeypatch.setattr(app.store,'save',broken)
    with pytest.raises(OSError):app.api_new({'name':'不会替代当前方案'})
    assert app.plan==before
    rows=[{'编号':'X','名称':'错误'}, {'编号':'01','名称':'甲'}, {'编号':'01','名称':'乙'}]
    pre=importer.preflight(app.plan,'rooms',rows,{'code':'编号','name':'名称'},'replace')
    assert any(e.get('row')==3 and e['code']=='row_invalid' for e in pre['errors'])


def test_monitor_resolution_undo_restores_pending_conflict(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));app.commit(ready());d=engine.duties(app.plan)[0]
    app.api_adjust_invigilator({'duty_id':d['id'],'index':1,'teacher_id':app.plan['invigilation'][d['id']][1]['teacher_id'],'locked':True})
    p=deepcopy(app.plan);p['settings']['invigilators']=1;app.api_save({'plan':p,'revision':p['revision']})
    app.api_monitor_lock_resolve({'duty_id':d['id'],'index':1,'revision':app.plan['revision'],'action':'discard'});app.api_undo({})
    assert app.plan['pending_monitor_locks'] and app.plan['invigilation'][d['id']][1]['locked']


def test_impossible_separate_grade_capacity_is_proved_without_solving(monkeypatch):
    from exam_room.model import demo_plan
    p=demo_plan(large=True)
    def should_not_solve(*args,**kwargs):raise AssertionError('已证明容量不足，不应进入求解')
    monkeypatch.setattr(engine,'_solve',should_not_solve)
    result=engine.assign_seats(p)
    assert result['status']=='infeasible' and '51' in result['message'] and '50' in result['message']


def test_backup_recovery_revision_is_newer_and_invalidates_running_result(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));app.commit(ready());p=deepcopy(app.plan);p['name']='虚构新版';app.api_save({'plan':p,'revision':p['revision']})
    rev=app.plan['revision'];app.store.path(p['id']).write_text('damaged');preview=app.api_recovery_preview({'id':p['id']})
    restored=app.api_recover({'id':p['id'],'backup_revision':preview['revision']})['plan']
    assert restored['revision']>rev and restored['name']!=p['name']


def test_damaged_plan_and_backup_can_be_deleted_and_restored_without_data_loss(tmp_path):
    store=Store(tmp_path);p=store.save(ready());p['revision']+=1;store.save(p);store.path(p['id']).write_text('damaged')
    store.delete(p['id']);assert not store.path(p['id']).exists()
    deleted=next(x for x in store.list(True) if x['id']==p['id']);assert deleted['damaged'] and deleted['recoverable']
    store.restore(p['id']);assert store.recovery(p['id'])['available']
    assert store.recover(p['id'])['students']==p['students']


def test_unequal_mixed_grade_interleave_exception_lists_actual_seats():
    p=ready();p['settings']['mix_grades']=True
    p['students'].append(dict(p['students'][0],id='s8',grade='八年级',name='虚构八甲',class_name='八1',number='800001'))
    p['exams'].append(dict(p['exams'][0],id='eight',grade='八年级'))
    p['rooms'][0].update(rows=2,cols=4,capacity=8)
    q=engine.assign_seats(p)['plan'];warnings=engine.validate(q)['warnings']
    assert any(x['code']=='grade_interleave_limited' and x['seat_pairs'] for x in warnings)
