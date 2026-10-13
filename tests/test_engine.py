"""Only synthetic pupils and teachers are used in these rule tests."""
from copy import deepcopy
from threading import Event
import importlib.util
import pytest

spec = importlib.util.find_spec('exam_room.engine')
if spec:
    from exam_room import engine
else:
    engine = None

@pytest.fixture(autouse=True)
def engine_available():
    assert engine is not None, '核心引擎尚未实现'


def fixture_plan(n=6):
    return dict(version=1, id='p', name='虚构学校考试', grades=['七年级','八年级','九年级'],students=[
        dict(id=f's{i}', name=f'测试学生{i}', grade='七', class_name=f'七{i%3+1}',
             student_no=f'学{i}', number=f'{i+1:05}', score=100-i,
             subjects=[]) for i in range(n)],
        rooms=[dict(id='r1', code='01', name='虚构教室1', rows=2, cols=3,
                    per_desk=1, aisles=[], disabled=[], capacity=6,
                    order='straight', availability=[], invigilators=None)],
        teachers=[dict(id=f't{i}', name=f'教师{i}', subjects=[], classes=[], unavailable=[])
                  for i in range(6)],
        exams=[dict(id='e1', grade='七', subject='语文', duration=90,
                    date='2026-11-01', start='08:00', end='09:30', locked=False,
                    special_seating=False, invigilators=None)],
        settings=dict(mode='class', seed=42, mix_grades=False, mix_groups=[],
                      invigilators=2, avoid_subject=True, avoid_class=True,
                      slots=[dict(date='2026-11-01', start='08:00', end='10:00')],
                      time_limit=4), seats={'base': {}}, invigilation={}, history=[], revision=0)


def good(result):
    assert result['status'] in ('optimal', 'feasible'), result
    return result['plan']


def place_all(p):
    p['seats']['base'] = {s['id']: dict(room_id='r1', seat=i+1, locked=False)
                          for i, s in enumerate(p['students'])}
    return p


def errors(p):
    return {x['code'] for x in engine.validate(p)['errors']}


def test_layout_snake_double_disabled_capacity_and_aisles():
    r = dict(rows=2, cols=3, per_desk=2, order='snake', disabled=[2, 8], capacity=8, aisles=[2])
    seats = engine.seat_layout(r)
    assert len(seats) == 8
    assert [s['seat'] for s in seats] == [1,3,4,5,6,7,9,10]
    assert seats[5] == dict(seat=7, row=2, col=6, desk=3, side=2)
    assert seats[6]['col'] == 4


def test_participants_filter_subjects_and_grade():
    p = fixture_plan(3)
    p['students'][0]['subjects'] = ['数学']
    p['students'][2]['grade'] = '八'
    assert [s['id'] for s in engine.participants(p,p['exams'][0])] == ['s1']


def test_schedule_preserves_locked_and_avoids_grade_overlap_and_balances_days():
    p=fixture_plan()
    p['exams'][0]['locked']=True
    p['exams'] += [dict(p['exams'][0], id=f'e{i}', subject=f'科{i}', locked=False, date='',start='',end='') for i in range(2,5)]
    p['settings']['slots']=[dict(date=d,start=s,end=e) for d in ['2026-11-01','2026-11-02'] for s,e in [('08:00','10:00'),('10:20','12:20'),('14:00','16:00')]]
    q=good(engine.schedule(p))
    assert q['exams'][0] == p['exams'][0]
    assert sorted([sum(x['date']==d for x in q['exams']) for d in ['2026-11-01','2026-11-02']]) == [2,2]
    assert 'grade_overlap' not in errors(q)
    assert p['exams'][1]['date']==''


def test_schedule_respects_slot_length_and_room_availability():
    p=fixture_plan()
    p['settings']['slots']=[dict(date='2026-11-01',start='08:00',end='09:00')]
    assert engine.schedule(p)['status']=='infeasible'
    p['settings']['slots'].append(dict(date='2026-11-01',start='10:00',end='12:00'))
    p['rooms'][0]['availability']=[dict(date='2026-11-01',start='10:00',end='12:00')]
    q=good(engine.schedule(p))
    assert q['exams'][0]['start']=='10:00'


def test_schedule_allocates_room_capacity_across_grades():
    p=fixture_plan(12)
    for s in p['students'][6:]: s['grade']='八'
    p['exams'].append(dict(p['exams'][0],id='e2',grade='八'))
    assert engine.schedule(p)['status']=='infeasible'
    p['settings']['slots'].append(dict(date='2026-11-01',start='10:00',end='12:00'))
    q=good(engine.schedule(p))
    assert q['exams'][0]['start'] != q['exams'][1]['start']


@pytest.mark.parametrize('mode',['class','random','score'])
def test_seating_is_complete_deterministic_and_keeps_locked(mode):
    p=fixture_plan()
    p['settings']['mode']=mode
    p['seats']['base']['s0']=dict(room_id='r1',seat=4,locked=True)
    a=good(engine.assign_seats(p)); b=good(engine.assign_seats(p))
    assert a['seats']==b['seats']
    assert set(a['seats']['base'])=={s['id'] for s in p['students']}
    assert a['seats']['base']['s0']==p['seats']['base']['s0']
    assert len({(x['room_id'],x['seat']) for x in a['seats']['base'].values()})==6
    assert set(p['seats']['base'])=={'s0'}


def test_seating_can_reuse_seat_across_nonoverlapping_grades():
    p=fixture_plan(12)
    for s in p['students'][6:]: s['grade']='八'
    p['exams'].append(dict(p['exams'][0],id='e2',grade='八',start='10:00',end='11:30'))
    q=good(engine.assign_seats(p))
    assert len(q['seats']['base'])==12
    assert not (errors(q) & {'room_overlap','seat_duplicate','mixed_grade'})


def test_mixing_requires_permission_and_exact_times():
    p=fixture_plan(6)
    for s in p['students'][3:]: s['grade']='八'
    p['exams'].append(dict(p['exams'][0],id='e2',grade='八'))
    assert engine.assign_seats(p)['status']=='infeasible'
    p['settings']['mix_grades']=True
    q=good(engine.assign_seats(p))
    assert len(engine.duties(q))==1
    p['exams'][1]['end']='10:00';p['exams'][1]['duration']=120
    assert engine.assign_seats(p)['status']=='infeasible'


def test_special_seating_contains_only_participants():
    p=fixture_plan()
    p['exams'][0]['special_seating']=True
    p['students'][0]['subjects']=['数学']
    p['exams'].append(dict(p['exams'][0],id='math',subject='数学',start='10:00',end='11:30'))
    p['settings']['slots'][0]['end']='12:00'
    q=good(engine.assign_seats(p,exam_id='e1'))
    assert set(q['seats']['e1'])=={f's{i}' for i in range(1,6)}
    assert q['seats']['base']=={}


def test_class_seating_avoids_same_desk_where_possible():
    p=fixture_plan(6)
    p['rooms'][0].update(rows=1,cols=3,per_desk=2)
    q=good(engine.assign_seats(p))
    groups={}
    for s in p['students']:
        seat=q['seats']['base'][s['id']]['seat'];groups.setdefault((seat-1)//2,set()).add(s['class_name'])
    assert all(len(x)==2 for x in groups.values())


def test_duties_workload_and_invigilation_hard_avoidance():
    p=place_all(fixture_plan())
    p['teachers'][0]['subjects']=['语文']
    p['teachers'][1]['classes']=['七1']
    p['teachers'][2]['unavailable']=[dict(date='2026-11-01',start='09:00',end='10:00')]
    ds=engine.duties(p)
    assert ds[0]['id']=='r1|2026-11-01|08:00|09:30'
    assert ds[0]['required']==2 and len(ds[0]['student_ids'])==6
    q=good(engine.assign_invigilators(p))
    assigned={a['teacher_id'] for a in q['invigilation'][ds[0]['id']]}
    assert assigned <= {'t3','t4','t5'} and len(assigned)==2
    assert sum(x['minutes'] for x in engine.workload(q))==180
    assert not engine.validate(q)['errors']


def test_invigilator_lock_and_overlap_cannot_be_relaxed():
    p=place_all(fixture_plan())
    d=engine.duties(p)[0]['id']
    p['invigilation'][d]=[dict(teacher_id='t0',locked=True)]
    p['teachers'][0]['subjects']=['语文']
    assert engine.assign_invigilators(p)['status']=='infeasible'
    p['settings']['avoid_subject']=False
    q=good(engine.assign_invigilators(p))
    assert q['invigilation'][d][0]==dict(teacher_id='t0',locked=True)


def test_invigilator_balance_across_equal_duties():
    p=place_all(fixture_plan())
    p['exams'] += [dict(p['exams'][0],id=f'e{i}',date=f'2026-11-0{i}') for i in range(2,4)]
    q=good(engine.assign_invigilators(p))
    assert {x['count'] for x in engine.workload(q)}=={1}


def test_cancelled_and_timeout_are_not_infeasible():
    p=fixture_plan();cancel=Event();cancel.set()
    for fn in [engine.schedule,engine.assign_seats,engine.assign_invigilators]:
        assert fn(p,cancel=cancel)['status']=='cancelled'
    p['settings']['time_limit']=0
    assert engine.schedule(p)['status']=='timeout'


def test_validation_reports_missing_assignments_duplicates_and_score_warning():
    p=fixture_plan();p['students'][1]['number']=p['students'][0]['number'];p['students'][0]['score']=None
    codes=errors(p)
    assert {'number_duplicate','seat_missing'}<=codes
    assert 'missing_score' in {x['code'] for x in engine.validate(p)['warnings']}
    p=place_all(fixture_plan());p['seats']['base']['s1']['seat']=1
    assert 'seat_duplicate' in errors(p)
    assert 'invigilator_missing' in errors(p)


def test_validation_room_availability_and_grade_overlap():
    p=place_all(fixture_plan())
    p['exams'].append(dict(p['exams'][0],id='e2',subject='数学',start='09:00',end='10:30'))
    p['rooms'][0]['availability']=[dict(date='2026-11-01',start='10:00',end='12:00')]
    assert {'room_unavailable','grade_overlap','student_overlap'}<=errors(p)


def test_adjust_seat_swaps_and_history_without_mutating_or_requiring_invigilators():
    p=place_all(fixture_plan())
    q=engine.adjust_seat(p,'s0','r1',2,swap=True,locked=True)
    assert q['seats']['base']['s0']['seat']==2
    assert q['seats']['base']['s1']['seat']==1
    assert q['seats']['base']['s0']['locked'] is True
    assert len(q['history'])==1 and q['history'][0]['seats']==p['seats']
    assert p['seats']['base']['s0']['seat']==1
    with pytest.raises(ValueError): engine.adjust_seat(p,'s0','r1',2)
    with pytest.raises(ValueError): engine.adjust_seat(p,'s0','r1',99)


def test_adjust_invigilator_checks_avoidance_overlap_and_saves_history():
    p=place_all(fixture_plan());d=engine.duties(p)[0]['id']
    p['teachers'][0]['subjects']=['语文']
    with pytest.raises(ValueError): engine.adjust_invigilator(p,d,0,'t0')
    q=engine.adjust_invigilator(p,d,0,'t1',locked=True)
    assert q['invigilation'][d][0]==dict(teacher_id='t1',locked=True)
    assert len(q['history'])==1
    cleared=engine.adjust_invigilator(q,d,0,'')
    assert cleared['invigilation'][d][0]['teacher_id']==''


def test_aisle_is_after_the_named_desk_column():
    room=dict(rows=1,cols=3,per_desk=2,capacity=6,aisles=[2])
    pairs={(a,b) for a,b,w in engine._neighbors(room)}
    assert (2,3) in pairs
    assert (4,5) not in pairs


def test_schedule_can_fill_long_window_and_reject_locked_outside_window():
    p=fixture_plan()
    p['settings']['slots']=[dict(date='2026-11-01',start='08:00',end='12:00')]
    p['exams'].append(dict(p['exams'][0],id='e2',subject='数学'))
    q=good(engine.schedule(p))
    assert 'grade_overlap' not in errors(q)
    p['exams'][0].update(locked=True,start='14:00',end='15:30')
    assert engine.schedule(p)['status']=='infeasible'


def test_teacher_shortage_keeps_eligible_assignments_and_explains_vacancies():
    p=place_all(fixture_plan());p['teachers']=p['teachers'][:2]
    p['teachers'][0]['subjects']=['语文']
    result=engine.assign_invigilators(p)
    assert result['status']=='partial'
    duty=engine.duties(p)[0]['id']
    assert [x['teacher_id'] for x in result['plan']['invigilation'][duty]].count('t1')==1
    assert result['unfilled'][0]['missing']==1
    assert '回避' in result['unfilled'][0]['reasons'][0]
    assert 'invigilator_missing' in errors(result['plan'])


def test_manual_special_seat_preserves_other_participants():
    p=place_all(fixture_plan())
    q=engine.adjust_seat(p,'s0','r1',2,exam_id='e1',swap=True)
    assert len(q['seats']['e1'])==6
    assert q['seats']['e1']['s0']['seat']==2
    assert q['seats']['e1']['s1']['seat']==1
    assert q['seats']['base']==p['seats']['base']
    assert q['exams'][0]['special_seating']
    assert 'seat_missing' not in errors(q)


def test_selected_score_column_does_not_overwrite_original_score():
    p=fixture_plan(2);p['settings']['mode']='score';p['settings']['score_field']='数学'
    p['students'][0]['original']={'数学':1};p['students'][1]['original']={'数学':99}
    q=good(engine.assign_seats(p))
    assert q['seats']['base']['s1']['seat']<q['seats']['base']['s0']['seat']
    assert q['students'][0]['score']==100
    q['settings']['score_field']=''
    q=good(engine.assign_seats(q))
    assert q['seats']['base']['s0']['seat']<q['seats']['base']['s1']['seat']


def monitor_overlap_plan():
    p=fixture_plan(3)
    p['students'][1]['grade']='八';p['students'][2]['grade']='九'
    p['rooms']=[dict(p['rooms'][0],id=f'r{i}',code=f'{i+1:02}') for i in range(3)]
    p['seats']['base']={f's{i}':dict(room_id=f'r{i}',seat=1,locked=False) for i in range(3)}
    p['exams']=[dict(p['exams'][0],id=f'e{i}',grade=g,start=a,end=b,duration=d)
                for i,(g,a,b,d) in enumerate([('七','08:00','09:30',90),('八','08:30','10:00',90),('九','09:30','11:00',90)])]
    p['settings']['slots']=[dict(date='2026-11-01',start='08:00',end='11:00')]
    p['teachers']=p['teachers'][:4]
    return p


def test_monitor_overlap_groups_allow_touching_and_preserve_locked_positions():
    p=monitor_overlap_plan();ds=engine.duties(p)
    p['invigilation']={ds[0]['id']:[dict(teacher_id='',locked=False),dict(teacher_id='t0',locked=True)],
                       ds[2]['id']:[dict(teacher_id='t0',locked=True)]}
    q=good(engine.assign_invigilators(p))
    assert q['invigilation'][ds[0]['id']][1]==p['invigilation'][ds[0]['id']][1]
    assert q['invigilation'][ds[2]['id']][0]['teacher_id']=='t0'
    for a,b in [(0,1),(1,2)]:
        assert not ({x['teacher_id'] for x in q['invigilation'][ds[a]['id']]} &
                    {x['teacher_id'] for x in q['invigilation'][ds[b]['id']]})
    assert not (errors(q)&{'teacher_overlap','invigilator_missing'})


def test_monitor_overlapping_locks_are_infeasible_not_relaxed():
    p=monitor_overlap_plan();ds=engine.duties(p)
    for d in ds[:2]:p['invigilation'][d['id']]=[dict(teacher_id='t0',locked=True)]
    result=engine.assign_invigilators(p)
    assert result['status']=='infeasible' and result['message'].startswith('现有条件下')
    assert result['plan']['invigilation']==p['invigilation']


def test_large_monitor_finds_all_posts_before_fairness_with_short_budget():
    import json
    from pathlib import Path
    from exam_room.model import normalize_plan
    p=normalize_plan(json.loads((Path(__file__).parents[1]/'testkit/fixtures/C20_large_mixed/方案.json').read_text(encoding='utf-8')))
    p=good(engine.assign_seats(p));p['settings']['time_limit']=5
    result=engine.assign_invigilators(p)
    assert result['status'] in ('feasible','optimal'),result['status']
    assert not result.get('unfilled')
    q=result['plan']
    assert sum(bool(a['teacher_id']) for entries in q['invigilation'].values() for a in entries)==300
    assert not (errors(q)&{'teacher_overlap','invigilator_missing','subject_avoidance','class_avoidance'})


def test_monitor_hint_reassigns_flexible_teachers_and_is_deterministic():
    hint=getattr(engine,'_invigilator_hint',None)
    assert callable(hint),'尚未给监考求解提供合法匹配初值'
    ds=[dict(id=f'd{i}',date='2026-11-01',start='08:00',end='09:00',required=1) for i in range(3)]
    teachers=fixture_plan()['teachers'][:3]
    eligible={(0,0),(0,1),(1,0),(1,2),(2,0),(2,2)}
    a=hint(ds,teachers,eligible,{0:[],1:[],2:[]})
    assert a==hint(ds,teachers,eligible,{0:[],1:[],2:[]})
    assert len(a)==3 and a<=eligible
    assert {di for di,ti in a}=={0,1,2} and {ti for di,ti in a}=={0,1,2}


def test_monitor_hint_respects_overlapping_locks_and_keeps_shortage_real():
    hint=getattr(engine,'_invigilator_hint',None)
    assert callable(hint),'尚未给监考求解提供合法匹配初值'
    ds=[dict(id=f'd{i}',date='2026-11-01',start=a,end=b,required=1)
        for i,(a,b) in enumerate([('08:00','09:00'),('08:30','09:30'),('09:00','10:00')])]
    teachers=fixture_plan()['teachers'][:1];eligible={(0,0),(1,0),(2,0)}
    assert hint(ds,teachers,eligible,{0:['t0'],1:[],2:['t0']})=={(0,0),(2,0)}
    assert hint(ds,teachers,eligible,{0:['t0'],1:['t0'],2:[]}) is None
    cancel=Event();cancel.set()
    assert hint(ds,teachers,eligible,{0:[],1:[],2:[]},cancel=cancel) is None


def test_monitor_cancel_during_solver_keeps_input_unchanged():
    p=place_all(fixture_plan());original=deepcopy(p);cancel=Event()
    result=engine.assign_invigilators(p,cancel=cancel,progress=lambda message:cancel.set())
    assert result['status']=='cancelled'
    assert result['plan']==original and p==original
