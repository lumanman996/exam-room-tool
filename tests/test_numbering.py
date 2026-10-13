from copy import deepcopy
import io

import openpyxl
import pytest
from exam_room import engine, report
from exam_room.model import new_plan, normalize_plan
from exam_room.storage import Store


def numbers():
    from exam_room import numbering
    return numbering


def seated():
    p=new_plan('虚构考号测试')
    p['grades']=['七年级','八年级']
    p['students']=[dict(id='a',name='学生甲',grade='七年级',class_name='七1'),
                   dict(id='b',name='学生乙',grade='八年级',class_name='八1')]
    p['rooms']=[dict(id='r',code='3',name='第三考场',rows=2,cols=5,capacity=10)]
    p=normalize_plan(p)
    p['seats']['base']={'a':dict(room_id='r',seat=8),'b':dict(room_id='r',seat=9)}
    return p


@pytest.mark.parametrize('prefix',['01','260','2026','00001'])
def test_prefix_is_flexible_and_components_are_two_digits(prefix):
    p=seated(); snapshot=deepcopy(p)
    v=numbers().preview(p,prefix=prefix)
    assert not v['errors']
    assert [r['new_number'] for r in v['rows']]==[prefix+'0308',prefix+'0309']
    q=numbers().apply(p,prefix=prefix)
    assert p==snapshot
    assert [s['number'] for s in q['students']]==[prefix+'0308',prefix+'0309']
    assert q['settings']['number_prefix']==prefix


def test_only_fill_missing_and_validate_against_preserved_students():
    p=seated();p['students'][0]['number']='260309'
    v=numbers().preview(p,prefix='26')
    assert v['rows'][0]['new_number']=='260309'
    assert any(e['code']=='number_duplicate' for e in v['errors'])
    with pytest.raises(ValueError):numbers().apply(p,prefix='26')
    q=numbers().apply(p,prefix='26',overwrite=True)
    assert [s['number'] for s in q['students']]==['260308','260309']


@pytest.mark.parametrize('kind',['missing','disabled','room100','seat100','room00','seat00','fraction'])
def test_invalid_location_blocks_whole_batch(kind):
    p=seated()
    if kind=='missing':p['seats']['base'].pop('b')
    if kind=='disabled':p['rooms'][0]['disabled']=[9];p['rooms'][0]['capacity']=9
    if kind=='room100':p['rooms'][0]['code']='100'
    if kind=='room00':p['rooms'][0]['code']='00'
    if kind=='seat100':p['seats']['base']['b']['seat']=100
    if kind=='seat00':p['seats']['base']['b']['seat']=0
    if kind=='fraction':p['seats']['base']['b']['seat']=1.5
    old=deepcopy(p)
    assert numbers().preview(p,prefix='26')['errors']
    with pytest.raises(ValueError):numbers().apply(p,prefix='26')
    assert p==old


def test_grade_scope_and_reused_seat_do_not_silently_make_duplicates():
    p=seated();p['seats']['base']['b']['seat']=8
    assert numbers().preview(p,prefix='26')['errors']
    q=numbers().apply(p,prefix='26',grade='七年级')
    q=numbers().apply(q,prefix='27',grade='八年级')
    assert [s['number'] for s in q['students']]==['260308','270308']


def test_source_detects_base_changes_but_not_subject_only_changes():
    q=numbers().apply(seated(),prefix='26')
    q['seats']['e1']={'a':dict(room_id='r',seat=1)}
    assert not numbers().source_issues(q)
    q['seats']['base']['a']['seat']=1
    assert any(x['student_id']=='a' for x in numbers().source_issues(q))
    assert 'number_seat_mismatch' in {x['code'] for x in engine.validate(q)['errors']}
    with pytest.raises(ValueError):report.build_excel(q,['students'])
    q=numbers().apply(q,prefix='26',overwrite=True)
    assert not numbers().source_issues(q)
    q['rooms'][0]['code']='04'
    assert numbers().source_issues(q)


def test_undo_and_store_preserve_text_numbers_and_sources(tmp_path):
    p=seated();p['students'][0]['number']='000001'
    p['exams']=[dict(id='e',grade='七年级',subject='语文',date='2026-11-12',start='08:00',end='09:30',duration=90)]
    p=normalize_plan(p)
    q=numbers().apply(p,prefix='0026',overwrite=True)
    st=Store(tmp_path);st.save(q);q=st.load(q['id'])
    assert q['students'][0]['number']=='00260308'
    wb=openpyxl.load_workbook(io.BytesIO(report.build_excel(q,['students'],draft=True)))
    cell=wb['学生编排总表']['D3']
    assert cell.value=='00260308' and cell.data_type=='s'
    restored=numbers().undo(q)
    assert [s['number'] for s in restored['students']]==['000001','']
    assert not restored['number_sources']
    q['students'][0]['number']='人工修改'
    with pytest.raises(ValueError):numbers().undo(q)


def test_preview_and_apply_service_rejects_stale_revision(tmp_path):
    from exam_room.server import App
    from exam_room.licensing import License
    app=App(root=tmp_path,license=License(tmp_path/'lic',None));app.commit(seated())
    v=app.api_number_preview(dict(prefix='26'))
    assert v['revision']==app.plan['revision'] and not v['errors']
    q=deepcopy(app.plan);q['seats']['base']['a']['seat']=1
    app.api_save(dict(plan=q,revision=q['revision']))
    with pytest.raises(ValueError):app.api_numbers(dict(prefix='26',rule='seat',revision=v['revision']))
    result=app.api_numbers(dict(prefix='26',rule='seat',revision=app.plan['revision']))
    assert result['plan']['students'][0]['number']=='260301'
    restored=app.api_number_undo({})['plan']
    assert restored['students'][0]['number']==''


def test_current_grade_prefix_override_wins_global_prefix_but_saved_map_keeps_legacy_behavior():
    from exam_room.model import normalize_plan
    from test_engine import fixture_plan,place_all
    p=normalize_plan(place_all(fixture_plan()));p['settings']['number_prefixes']={'七年级':'OLD'}
    numbering=numbers()
    result=numbering.preview(p,prefix='77',prefixes={'七年级':'88'},overwrite=True)
    assert all(r['new_number'].startswith('88') for r in result['rows'])
    result=numbering.preview(p,prefix='77',overwrite=True)
    assert all(r['new_number'].startswith('77') for r in result['rows'])
