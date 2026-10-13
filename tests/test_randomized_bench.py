"""随机对抗验测的检查器本身要能发现违规，否则"全部通过"没有意义。"""
from copy import deepcopy

from exam_room import engine, model, numbering
from tools.testbench import randomized as prop


def solved():
    p = model.demo_plan()
    for fn in (engine.schedule, engine.assign_seats):
        p = fn(p)['plan']
    p = numbering.apply(p, prefix='26', overwrite=True)
    return engine.assign_invigilators(p)['plan']


def test_checker_passes_a_valid_plan_and_catches_planted_violations():
    p = solved()
    assert prop.violations(p) == []
    base = p['seats']['base']
    a, b = list(base)[:2]

    q = deepcopy(p);q['seats']['base'][b] = dict(q['seats']['base'][a])
    assert any('坐在' in x for x in prop.violations(q))

    q = deepcopy(p);del q['seats']['base'][a]
    assert any('没有座位' in x for x in prop.violations(q))

    q = deepcopy(p);q['students'][1]['number'] = q['students'][0]['number']
    assert any('考号' in x and '重复' in x for x in prop.violations(q))

    q = deepcopy(p);q['exams'][0]['end'] = '23:00'
    assert any('时长不符' in x for x in prop.violations(q))

    q = deepcopy(p);duty = next(d for d in q['invigilation'] if q['invigilation'][d])
    teacher = q['invigilation'][duty][0]['teacher_id']
    q['invigilation'][duty] = [dict(teacher_id=teacher, locked=False)] * 2
    assert any('重复监考' in x for x in prop.violations(q))


def test_seeds_are_reproducible():
    keys = ('students', 'rooms', 'teachers', 'exams', 'settings')
    content = lambda seed: {k: prop.make_plan(seed)[k] for k in keys}
    assert content(3) == content(3)
    assert content(3) != content(4)
