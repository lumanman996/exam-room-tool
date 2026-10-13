"""求解失败时的中文诊断。只用虚构学生和教室。"""
from exam_room import engine


def plan(rooms=(6,), mix=False):
    return dict(version=1, id='p', name='虚构诊断', grades=['七年级', '八年级', '九年级'], students=[],
                rooms=[dict(id=f'r{i}', code=f'{i:02}', name=f'虚构教室{i}', rows=1, cols=n, per_desk=1, capacity=n)
                       for i, n in enumerate(rooms, 1)],
                teachers=[], exams=[],
                settings=dict(mode='class', seed=1, mix_grades=mix, mix_groups=[], invigilators=1, time_limit=4,
                              slots=[dict(date='2026-11-01', start='08:00', end='12:00')]),
                seats={'base': {}}, invigilation={}, history=[], revision=0)


def pupils(p, grade, n, subjects=()):
    start = len(p['students'])
    p['students'] += [dict(id=f's{start+i}', name=f'虚构{start+i}', grade=grade, class_name=grade[0] + '1',
                           subjects=list(subjects)) for i in range(n)]


def exam(p, ident, grade, subject, start, end, special=False):
    a, b = (int(x[:2]) * 60 + int(x[3:]) for x in (start, end))
    p['exams'].append(dict(id=ident, grade=grade, subject=subject, duration=b - a, date='2026-11-01',
                           start=start, end=end, special_seating=special))


def seats_message(p):
    result = engine.assign_seats(p)
    assert result['status'] == 'infeasible', result['status']
    return result['message']


def test_more_pupils_at_one_moment_than_seats():
    p = plan(mix=True);pupils(p, '七年级', 4);pupils(p, '八年级', 4)
    exam(p, 'a', '七年级', '语文', '08:00', '09:30');exam(p, 'b', '八年级', '语文', '08:00', '09:30')
    assert '11月1日 08:00 起有 8 人同时考试，可用座位只有 6 个' in seats_message(p)


def test_back_to_back_exams_are_not_counted_as_simultaneous():
    from exam_room import diagnosis
    p = plan();pupils(p, '七年级', 5);pupils(p, '八年级', 5)
    exam(p, 'a', '七年级', '语文', '08:00', '09:30');exam(p, 'b', '八年级', '语文', '09:30', '11:00')
    assert '同时考试' not in diagnosis.seats(p)


def test_staggered_exams_of_different_grades_need_separate_rooms():
    p = plan(rooms=(10,), mix=True);pupils(p, '七年级', 4);pupils(p, '八年级', 4)
    exam(p, 'a', '七年级', '语文', '08:00', '09:30');exam(p, 'b', '八年级', '语文', '09:00', '10:30')
    message = seats_message(p)
    assert '时间交错' in message and '至少需要 2 个考场，可用 1 个' in message


def test_pupils_with_only_special_exams_still_need_a_fixed_seat_number():
    p = plan();pupils(p, '七年级', 6);pupils(p, '七年级', 1, ['英语'])
    exam(p, 'a', '七年级', '语文', '08:00', '09:30');exam(p, 'b', '七年级', '英语', '10:00', '11:30', special=True)
    message = seats_message(p)
    assert '7 名学生需要各自不同的座位（其中 1 人只参加单独排座的科目，仍需固定座号来生成考号）' in message


def test_exam_longer_than_any_allowed_slot_is_named():
    p = plan();pupils(p, '七年级', 3)
    exam(p, 'a', '七年级', '语文', '08:00', '09:30');p['exams'][0].update(duration=300, date='', start='', end='')
    result = engine.schedule(p)
    assert result['status'] == 'infeasible'
    assert result['message'].startswith('七年级语文找不到合适的考试时间。')
    assert '允许时段最长 240 分钟，短于考试时长 300 分钟' in result['message']


def test_grade_total_longer_than_all_slots():
    p = plan();pupils(p, '七年级', 3)
    for i, subject in enumerate(['语文', '数学', '英语']):
        exam(p, f'e{i}', '七年级', subject, '08:00', '09:30')
        p['exams'][-1].update(duration=100, date='', start='', end='')
    result = engine.schedule(p)
    assert result['status'] == 'infeasible'
    assert '七年级各科合计 300 分钟，允许时段合计只有 240 分钟' in result['message']
