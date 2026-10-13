from copy import deepcopy
import io
import openpyxl
import pytest
from exam_room import engine,numbering,report
from test_edit_history import app_fixture


def physical_positions(p):
    layouts={r['id']:{x['seat']:(x['row'],x['col']) for x in engine.seat_layout(r)} for r in p['rooms']}
    return {(key,sid):layouts[pos['room_id']][pos['seat']] for key,m in p['seats'].items() for sid,pos in m.items()}


def test_label_swap_preserves_all_students_and_locks_and_generated_numbers(tmp_path):
    a=app_fixture(tmp_path);q=engine.assign_seats(a.plan)['plan'];q['seats']['e0-0']=deepcopy(q['seats']['base']);q['exams'][0]['special_seating']=True
    for s in q['students']:s['number']=''
    q=numbering.apply(q,prefix='002',overwrite=True);sid=next(iter(q['seats']['base']));q['seats']['base'][sid]['locked']=True;a.commit(q)
    before=deepcopy(a.plan);coords=physical_positions(before);pos=before['seats']['base'][sid];rid=pos['room_id'];first=pos['seat'];second=next(x['seat'] for x in engine.seat_layout(next(r for r in before['rooms'] if r['id']==rid)) if x['seat']!=first)
    body={'room_id':rid,'first':first,'second':second};pre=a.api_seat_labels_preview(body)
    assert pre['number_review']
    a.api_seat_labels_apply({**body,'revision':pre['revision']})
    assert physical_positions(a.plan)==coords and a.plan['seats']['base'][sid]['seat']==second and a.plan['seats']['base'][sid]['locked']
    assert a.plan['students']==before['students'] and numbering.source_issues(a.plan)
    wb=openpyxl.load_workbook(io.BytesIO(report.build_excel(a.plan,['students'],True)))
    values=list(wb.active.values);assert any(str(second).zfill(2) in row for row in values);wb.close()
    a.api_open({'id':a.plan['id']});assert physical_positions(a.plan)==coords
    a.api_edit_undo({'revision':a.plan['revision']});assert a.plan['rooms']==before['rooms'] and a.plan['seats']==before['seats']


def test_labels_reject_disabled_capacity_and_duplicates(tmp_path):
    a=app_fixture(tmp_path);q=deepcopy(a.plan);q['rooms'][0].update(capacity=2,disabled=[1]);a.api_save({'plan':q,'revision':q['revision']})
    for first,second in [(1,2),(2,4),(2,2),(0,2)]:
        with pytest.raises(ValueError):a.api_seat_labels_preview({'room_id':'r0','first':first,'second':second})
    raw=deepcopy(a.plan['rooms'][0]);raw['seat_labels']={'1:1':2,'1:2':2}
    with pytest.raises(ValueError):a.api_room_layout_preview({'room':raw})


def test_restore_default_and_route_shape_changes_keep_physical_positions(tmp_path):
    a=app_fixture(tmp_path);a.commit(engine.assign_seats(a.plan)['plan']);rid=a.plan['rooms'][0]['id'];before=physical_positions(a.plan)
    a.api_seat_labels_apply({'room_id':rid,'first':1,'second':2,'revision':a.plan['revision']})
    a.api_seat_labels_apply({'room_id':rid,'action':'reset','revision':a.plan['revision']});assert physical_positions(a.plan)==before
    q=deepcopy(a.plan);q['rooms'][0]['direction']='vertical';a.api_save({'plan':q,'revision':q['revision']});assert physical_positions(a.plan)==before
    a.api_seat_labels_apply({'room_id':rid,'first':1,'second':2,'revision':a.plan['revision']})
    q=deepcopy(a.plan);q['rooms'][0].update(rows=6,cols=5)
    with pytest.raises(ValueError,match='座号'):a.api_save({'plan':q,'revision':q['revision'],'confirm_impact':True})


def test_all_saved_loaded_imported_seat_labels_are_validated(tmp_path):
    import json,base64
    from exam_room.model import normalize_plan
    a=app_fixture(tmp_path);before=deepcopy(a.plan);raw=a.store.path(a.plan['id']).read_bytes()
    q=deepcopy(a.plan);q['rooms'][0]['seat_labels']={'1:1':2}
    with pytest.raises(ValueError):a.api_save({'plan':q,'revision':q['revision']})
    assert a.plan==before and a.store.path(a.plan['id']).read_bytes()==raw
    with pytest.raises(ValueError):normalize_plan(q)
    with pytest.raises(ValueError):a.api_plan_import({'data':base64.b64encode(json.dumps(q).encode()).decode()})
    assert a.plan==before
    a.store.path(a.plan['id']).write_text(json.dumps(q))
    with pytest.raises(ValueError):a.store.load(q['id'])


def test_shape_change_and_default_labels_are_one_atomic_operation(tmp_path):
    a=app_fixture(tmp_path);a.commit(engine.assign_seats(a.plan)['plan']);rid='r0'
    a.api_seat_labels_apply({'room_id':rid,'first':1,'second':2,'revision':a.plan['revision']})
    before=deepcopy(a.plan);coords=physical_positions(a.plan)
    body={'kind':'rooms','action':'update','ids':[rid],'fields':{'rows':6,'cols':5},'reset_labels':True}
    pre=a.api_bulk_preview(body)
    a.api_bulk_apply({**body,'revision':pre['revision'],'confirm_impact':True})
    room=next(r for r in a.plan['rooms'] if r['id']==rid);assert not room['seat_labels']
    for key,sid in physical_positions(a.plan):assert physical_positions(a.plan)[key,sid]==coords[key,sid]
    a.api_edit_undo({'revision':a.plan['revision']});assert a.plan['rooms']==before['rooms'] and a.plan['seats']==before['seats']
