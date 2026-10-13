from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest
from exam_room import engine, importer, report, numbering
from exam_room.model import normalize_plan
from exam_room.rooms import layout_preview
from test_engine import fixture_plan, good, errors


@pytest.mark.parametrize('direction,order,coords',[
    ('horizontal','straight',[(1,1),(1,2),(1,3),(2,1),(2,2),(2,3)]),
    ('horizontal','snake',[(1,1),(1,2),(1,3),(2,3),(2,2),(2,1)]),
    ('vertical','straight',[(1,1),(2,1),(1,2),(2,2),(1,3),(2,3)]),
    ('vertical','snake',[(1,1),(2,1),(2,2),(1,2),(1,3),(2,3)]),
])
def test_four_numbering_directions(direction,order,coords):
    room=dict(fixture_plan()['rooms'][0],direction=direction,order=order)
    layout=engine.seat_layout(room)
    assert [(s['row'],s['col']) for s in layout]==coords
    assert [s['seat'] for s in layout]==list(range(1,7))


def test_vertical_double_desk_disabled_capacity_preview_and_import():
    room=dict(fixture_plan()['rooms'][0],cols=2,per_desk=2,capacity=5,
              direction='vertical',order='snake',disabled=[2],aisles=[1])
    layout=engine.seat_layout(room)
    assert [s['seat'] for s in layout]==[1,3,4,5,6]
    assert layout[1]==dict(seat=3,row=2,col=2,desk=1,side=2)
    assert {s['seat'] for s in layout_preview(room)['positions'] if s['usable']}=={1,3,4,5,6}
    imported=importer.import_rows('rooms',[{'方向':'竖排','顺序':'蛇形'}],{'direction':'方向','order':'顺序'})[0]
    assert imported['direction']=='vertical'
    assert normalize_plan(fixture_plan())['rooms'][0]['direction']=='horizontal'


@pytest.mark.parametrize('grade_count',[2,3])
@pytest.mark.parametrize('mode',['class','random','score'])
def test_selected_grades_alternate_seat_numbers(grade_count,mode):
    p=fixture_plan(6)
    grades=['七','八','九'][:grade_count]
    for i,s in enumerate(p['students']):s.update(grade=grades[i%grade_count],class_name=grades[i%grade_count]+'1')
    p['exams']=[dict(p['exams'][0],id='e'+g,grade=g) for g in grades]
    p['settings'].update(mix_grades=True,mix_groups=[grades],mode=mode)
    q=good(engine.assign_seats(p))
    ordered=sorted(q['students'],key=lambda s:q['seats']['base'][s['id']]['seat'])
    sequence=[s['grade'] for s in ordered]
    assert all(len(set(sequence[i:i+grade_count]))==grade_count for i in range(0,6,grade_count))
    assert not errors(q)&{'mixed_grade','seat_duplicate','room_overlap','seat_missing'}
    assert q['seats']==good(engine.assign_seats(p))['seats']


def test_pair_mixing_keeps_third_grade_separate_and_locked_position():
    p=fixture_plan(9)
    for i,s in enumerate(p['students']):s.update(grade=['七','八','九'][i%3],class_name=str(i))
    p['rooms'].append(dict(p['rooms'][0],id='r2',code='02'))
    p['exams']=[dict(p['exams'][0],id='e'+g,grade=g) for g in ['七','八','九']]
    p['settings'].update(mix_grades=True,mix_groups=[['七','八']])
    p['seats']['base']['s0']=dict(room_id='r1',seat=3,locked=True)
    q=good(engine.assign_seats(p))
    assert q['seats']['base']['s0']==p['seats']['base']['s0']
    room_grades={}
    for s in q['students']:room_grades.setdefault(q['seats']['base'][s['id']]['room_id'],set()).add(s['grade'])
    assert all('九' not in gs or len(gs)==1 for gs in room_grades.values())
    assert not errors(q)&{'mixed_grade','seat_duplicate','room_overlap','seat_missing'}


@pytest.mark.parametrize('order',['straight','snake'])
def test_vertical_print_and_exam_numbers_use_same_physical_positions(order):
    import re
    p=fixture_plan()
    p['school']='虚构测试学校'
    p['rooms'][0].update(direction='vertical',order=order)
    p['students']=[dict(s,number='') for s in p['students']]
    q=numbering.apply(good(engine.assign_seats(p)),prefix='0026',overwrite=True)
    html=report.build_html(q,['seating'],draft=True)
    table=re.search(r'<table class="seats">(.*?)</table>',html).group(1)
    printed=[int(n) for n in re.findall(r'<small>(\d+) 号</small>',table)]
    expected=[s['seat'] for s in sorted(engine.seat_layout(q['rooms'][0]),key=lambda s:(s['row'],s['col']))]
    assert printed==expected
    assert all(s['number']=='002601'+str(q['seats']['base'][s['id']]['seat']).zfill(2) for s in q['students'])
    assert normalize_plan(q)['rooms'][0]['direction']=='vertical'
    assert not numbering.source_issues(q)


def test_time_input_accepts_typing_adjusts_five_minutes_and_rejects_bad_time():
    script=Path(__file__).parents[1]/'exam_room/ui/controls.js'
    code=f"""
    const assert=require('node:assert/strict');
    const {{parseClock,shiftClock,mixPreset}}=require({json.dumps(str(script))});
    assert.equal(parseClock('8：05'),'08:05');
    assert.equal(shiftClock('08:05',5),'08:10');
    assert.equal(shiftClock('08:05',-5),'08:00');
    assert.throws(()=>parseClock('24:00'));assert.throws(()=>parseClock('8:5'));
    assert.throws(()=>shiftClock('23:58',5));assert.throws(()=>shiftClock('00:02',-5));
    assert.deepEqual(mixPreset('separate',''),{{mix_grades:false,mix_groups:[]}});
    assert.deepEqual(mixPreset('all',''),{{mix_grades:true,mix_groups:[]}});
    assert.deepEqual(mixPreset('pair','七年级|九年级'),{{mix_grades:true,mix_groups:[['七年级','九年级']]}});
    """
    subprocess.run(['node','-e',code],check=True,capture_output=True,text=True)


def test_existing_numbers_sort_ascending_preserve_text_and_put_missing_last():
    p=fixture_plan();p['settings']['mode']='number'
    nums=['260110','260102','','000001','260103','260101']
    for s,n in zip(p['students'],nums):s['number']=n
    q=good(engine.assign_seats(p))
    ordered=sorted(q['students'],key=lambda s:q['seats']['base'][s['id']]['seat'])
    assert [s['number'] for s in ordered]==['000001','260101','260102','260103','260110','']


def test_direction_and_manual_time_save_mark_existing_seats_stale(tmp_path):
    from exam_room.server import App
    from exam_room.licensing import License
    app=App(root=tmp_path,license=License(tmp_path/'lic',None))
    p=normalize_plan(good(engine.assign_seats(fixture_plan())))
    app.commit(p)
    q=deepcopy(app.plan);q['rooms'][0]['direction']='vertical'
    state=app.api_save({'plan':q,'revision':q['revision']})
    assert 'seats' in state['plan']['stale']
    assert app.store.load(q['id'])['rooms'][0]['direction']=='vertical'
    q=deepcopy(app.plan);q['exams'][0].update(start='08:05',end='09:35',duration=90)
    state=app.api_save({'plan':q,'revision':q['revision']})
    assert 'seats' in state['plan']['stale']
    assert app.store.load(q['id'])['exams'][0]['start']=='08:05'
    assert engine.assign_seats(app.plan)['status']=='feasible'
