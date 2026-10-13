"""年级由教务显式设定；所有资料均为虚构，错误操作不落盘。"""
from copy import deepcopy
import base64,json
from pathlib import Path
import pytest
from exam_room import engine,importer,report
from exam_room.model import new_plan,normalize_plan
from exam_room.server import App
from exam_room.licensing import License
from test_backend_hardening import ready


def app_at(root,grades=None):
    app=App(root,License(root/'license',None))
    app.api_new({'name':'虚构年级设置','grades':grades or []})
    return app


def import_body(grade='七年级',kind='students'):
    if kind=='students':rows=[{'姓名':'虚构甲','年级':grade,'班级':'虚构1'}];mapping={'name':'姓名','grade':'年级','class_name':'班级'}
    else:rows=[{'年级':grade,'科目':'语文','时长':90}];mapping={'grade':'年级','subject':'科目','duration':'时长'}
    return dict(kind=kind,rows=rows,mapping=mapping,mode='append')


def test_new_explicit_empty_and_legacy_migration_are_distinct():
    p=new_plan();assert p['grades']==[] and not p['grade_review_required']
    p['students']=[dict(name='虚构甲',grade='初一',class_name='虚构1')]
    assert normalize_plan(p)['grades']==[]
    old=deepcopy(p);del old['grades'];del old['grade_review_required']
    q=normalize_plan(old)
    assert q['grades']==['七年级'] and q['grade_review_required']
    assert normalize_plan(q)['grade_review_required']


def test_api_new_preserves_declared_order_and_unused_grades(tmp_path):
    app=app_at(tmp_path,['毕业班','初一','拓展班'])
    assert app.plan['grades']==['毕业班','七年级','拓展班']
    assert app.store.load(app.plan['id'])['grades']==app.plan['grades']


@pytest.mark.parametrize('grades',[['七','初一'],[''],['  '],['七',7],'七年级',None])
def test_invalid_grade_list_does_not_replace_active_plan(tmp_path,grades):
    app=app_at(tmp_path,['七年级']);before=deepcopy(app.plan)
    with pytest.raises(ValueError):app.api_new({'name':'无效设置','grades':grades})
    assert app.plan==before


@pytest.mark.parametrize('grades,grade',[([], '七年级'),(['七年级'],'八年级')])
@pytest.mark.parametrize('kind',['students','exams'])
def test_unknown_grade_preflight_and_import_reject_atomically(tmp_path,grades,grade,kind):
    app=app_at(tmp_path,grades);before=deepcopy(app.plan)
    path=app.store.path(app.plan['id']);disk=path.read_bytes()
    body=import_body(grade,kind)
    errors=app.api_import_preflight(body)['errors']
    assert any(e['field']=='grade' and e['row']==1 for e in errors)
    with pytest.raises(ValueError):app.api_import(body)
    assert app.plan==before and path.read_bytes()==disk


def test_known_grade_import_save_clone_and_plan_export(tmp_path):
    app=app_at(tmp_path,['七年级','备用班']);app.api_import(import_body('初一'))
    assert app.plan['grades']==['七年级','备用班']
    data=app.api_plan_export({});exported=json.loads(Path(data['path']).read_text(encoding='utf-8'))
    assert exported['grades']==app.plan['grades']
    clone=app.store.clone(app.plan['id'],'虚构副本');assert clone['grades']==app.plan['grades']


def test_referenced_grade_deletion_and_unknown_save_keep_data(tmp_path):
    app=app_at(tmp_path,['七年级']);app.api_import(import_body())
    before=deepcopy(app.plan);disk=app.store.path(before['id']).read_bytes()
    for mutation in [lambda p:p.update(grades=[]),lambda p:p['students'][0].update(grade='未知年级')]:
        p=deepcopy(before);mutation(p)
        with pytest.raises(ValueError):app.api_save({'plan':p,'revision':before['revision']})
        assert app.plan==before and app.store.path(before['id']).read_bytes()==disk


@pytest.mark.parametrize('groups',[[['甲']], [['甲','未知']], [['甲','乙'],['乙','丙']], [['甲','甲']]])
def test_invalid_active_and_named_groups_are_rejected(tmp_path,groups):
    app=app_at(tmp_path,['甲','乙','丙']);before=deepcopy(app.plan)
    for key,value in [('mix_groups',groups),('mix_presets',[dict(id='preset1',name='虚构组',groups=groups)])]:
        p=deepcopy(before);p['settings'][key]=value
        with pytest.raises(ValueError):app.api_save({'plan':p,'revision':before['revision']})
        assert app.plan==before


def test_named_groups_roundtrip_unused_grade_independent_and_stale(tmp_path):
    app=App(tmp_path,License(tmp_path/'license',None));p=ready()
    p['grades']=['七年级','八年级','九年级'];app.commit(p)
    p=deepcopy(app.plan);p['settings']['mix_presets']=[dict(id='p1',name='虚构甲乙混排',groups=[['七','初二']])]
    saved=app.api_save({'plan':p,'revision':p['revision']})['plan']
    assert saved['settings']['mix_presets'][0]['groups']==[['七年级','八年级']]
    assert saved['settings']['mix_groups']==[] and not saved['settings']['mix_grades']
    p=deepcopy(saved);p['grades'].append('拓展班')
    saved=app.api_save({'plan':p,'revision':p['revision']})['plan']
    assert 'seats' in saved['stale'] and 'invigilation' in saved['stale']
    assert saved['history_epoch']>p['history_epoch']
    assert app.store.load(saved['id'])['settings']['mix_presets']==saved['settings']['mix_presets']


def test_explicit_unknown_grade_cannot_solve_or_formally_export():
    p=ready();p['grades']=[]
    assert any(e['code']=='grade_unknown' for e in engine.validate(p)['errors'])
    assert engine.assign_seats(p)['status']=='infeasible'
    with pytest.raises(ValueError):report.check_export(p,draft=False,sections=['students'])
    with pytest.raises(ValueError):report.check_export(p,draft=False,sections=['schedule'])


def test_save_cannot_reenter_legacy_migration_by_removing_grade_field(tmp_path):
    app=app_at(tmp_path,['七年级','备用班']);app.api_import(import_body())
    before=deepcopy(app.plan);p=deepcopy(before);del p['grades']
    p['students'].append(dict(p['students'][0],id='unknown',name='虚构乙',grade='八年级'))
    disk=app.store.path(before['id']).read_bytes()
    with pytest.raises(ValueError):app.api_save({'plan':p,'revision':before['revision']})
    assert app.plan==before and app.store.path(before['id']).read_bytes()==disk


def test_print_scope_and_numbering_accept_declared_grade_without_students():
    from exam_room import printing,numbering
    p=ready();p['grades']=['七年级','八年级','九年级']
    assert printing.scope_options(p,{'grades':['八年级']})['grades']==['八年级']
    assert printing.filtered_rows(p,{'grades':['八年级']})==[]
    document=printing.document(p,['students'],scope={'grades':['八年级']})
    assert '当前范围没有资料' in document['html']
    preview=numbering.preview(p,prefix='26',grade='八年级')
    assert preview['rows']==[] and preview['errors']==[]
    assert preview['warnings']
    with pytest.raises(ValueError):numbering.preview(p,prefix='26',grade='未知年级')
