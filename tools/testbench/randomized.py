"""随机对抗验测：按固定种子生成虚构方案，走完 日程→固定座位→单独排座→考号→监考，
再用独立于产品 validate 的规则逐条核对硬规则。不读取真实资料。

每个种子是一个用例；失败时报告种子号，可用 --case PROP-<种子> 单独复现。
求解器在限时内无解或超时都不算失败，但无解提示必须是教务人员能看懂的中文。
"""
import random
from collections import Counter, defaultdict
from itertools import combinations

from exam_room import engine, errors, model, numbering

GRADES = ['七年级', '八年级', '九年级']
SUBJECTS = ['语文', '数学', '英语', '物理', '化学', '道法']
SOLVED = ('optimal', 'feasible')


def _minutes(text):
    h, m = text.split(':')
    return int(h) * 60 + int(m)


def _event(item):
    return item['date'], _minutes(item['start']), _minutes(item['end'])


def _overlap(a, b):
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]


def make_plan(seed):
    """规模刻意偏小（每年级最多约 120 人、8 个考场），让 quick 模式也能跑完若干组。"""
    rng = random.Random(seed)
    p = model.new_plan(f'随机虚构考试{seed}')
    grades = GRADES[:rng.randint(1, 3)]
    p['grades'] = grades
    own = {g: rng.sample(SUBJECTS, rng.randint(1, 4)) for g in grades}
    sid = 0
    for g in grades:
        for c in range(1, rng.randint(2, 5)):
            for _ in range(rng.randint(5, 30)):
                subjects = [] if rng.random() < 0.85 else rng.sample(own[g], rng.randint(1, len(own[g])))
                p['students'].append(dict(id=f's{sid}', name=f'虚构学生{sid}', grade=g, class_name=f'{g[0]}{c}',
                                          student_no='', number='', subjects=subjects, original={},
                                          score=rng.choice([rng.randint(200, 600), None])))
                sid += 1
    for r in range(rng.randint(2, 8)):
        rows, cols, per = rng.randint(3, 7), rng.randint(3, 7), rng.choice([1, 1, 1, 2])
        disabled = rng.sample(range(1, rows * cols * per + 1), rng.randint(0, 3)) if rng.random() < .3 else []
        p['rooms'].append(dict(id=f'r{r}', code=f'{r + 1:02}', name=f'虚构第{r + 1:02}考场', location='', rows=rows,
                               cols=cols, per_desk=per, aisles=[], disabled=disabled,
                               capacity=rows * cols * per - len(disabled), order=rng.choice(['straight', 'snake']),
                               direction=rng.choice(['horizontal', 'vertical']), seat_labels={}, availability=[],
                               invigilators=None))
    for t in range(rng.randint(3, 25)):
        away = [dict(date='2026-11-12', start='08:00', end='12:00')] if rng.random() < .2 else []
        p['teachers'].append(dict(id=f't{t}', name=f'虚构教师{t}', subjects=rng.sample(SUBJECTS, rng.randint(0, 2)),
                                  classes=[], unavailable=away))
    eid = 0
    for g in grades:
        for subject in own[g]:
            p['exams'].append(dict(id=f'e{eid}', grade=g, subject=subject, duration=rng.choice([60, 90, 120]),
                                   date='', start='', end='', locked=False, special_seating=rng.random() < .1,
                                   invigilators=None))
            eid += 1
    s = p['settings']
    s['slots'] = [dict(date=d, start=a, end=b) for d in ('2026-11-12', '2026-11-13')
                  for a, b in (('08:00', '11:30'), ('14:00', '17:00'))]
    s.update(mode=rng.choice(['class', 'random', 'score']), seed=rng.randint(1, 10_000),
             mix_grades=rng.random() < .4, invigilators=rng.choice([1, 2]), time_limit=5)
    # 最后再抽考号方式，前面的随机序列保持不变。
    s['number_rule'] = rng.choice(['seat', 'serial'])
    return model.normalize_plan(p)


def violations(p):
    """独立核对硬规则，不调用 engine.validate。返回中文问题列表。"""
    found = []
    rooms = {r['id']: r for r in p['rooms']}
    layouts = {rid: {x['seat'] for x in engine.seat_layout(r)} for rid, r in rooms.items()}
    occupied = defaultdict(list)
    room_use = defaultdict(dict)
    for ex in p['exams']:
        if not ex.get('date'):
            found.append(f'{ex["id"]} 没有考试时间')
            continue
        mapping = p['seats'].get(ex['id'] if ex.get('special_seating') else 'base', {})
        members = [s for s in p['students']
                   if s['grade'] == ex['grade'] and (not s['subjects'] or ex['subject'] in s['subjects'])]
        used = set()
        for s in members:
            pos = mapping.get(s['id'])
            if not pos:
                found.append(f'{s["id"]} 在 {ex["id"]} 没有座位')
                continue
            place = pos['room_id'], pos['seat']
            if place[0] not in rooms or place[1] not in layouts[place[0]]:
                found.append(f'{s["id"]} 的座位 {place} 不存在')
                continue
            if place in used:
                found.append(f'{ex["id"]} 有两人坐在 {place}')
            used.add(place)
            occupied[place].append((s['id'], ex))
            room_use[place[0]][ex['id']] = ex
    for place, entries in occupied.items():
        for (a, ea), (b, eb) in combinations(entries, 2):
            if a != b and ea['id'] != eb['id'] and _overlap(_event(ea), _event(eb)):
                found.append(f'同一时间两场考试共用座位 {place}')
    for rid, entries in room_use.items():
        for a, b in combinations(entries.values(), 2):
            if _overlap(_event(a), _event(b)):
                if _event(a) != _event(b):
                    found.append(f'考场 {rid} 时间交错的两场考试同场')
                elif a['grade'] != b['grade'] and not engine._mix(p, a['grade'], b['grade']):
                    found.append(f'考场 {rid} 不允许混排的年级同场')
    for a, b in combinations([x for x in p['exams'] if x.get('date')], 2):
        if a['grade'] == b['grade'] and _overlap(_event(a), _event(b)):
            found.append(f'同一年级 {a["id"]} 与 {b["id"]} 时间重叠')
    slots = [_event(x) for x in p['settings']['slots']]
    for ex in p['exams']:
        if ex.get('date'):
            x = _event(ex)
            if x[2] - x[1] != int(ex['duration']):
                found.append(f'{ex["id"]} 起止时间与时长不符')
            if not any(s[0] == x[0] and s[1] <= x[1] and x[2] <= s[2] for s in slots):
                found.append(f'{ex["id"]} 超出允许时段')
    numbers = Counter(s['number'] for s in p['students'] if s.get('number'))
    found += [f'考号 {n} 重复' for n, c in numbers.items() if c > 1]
    teachers = {t['id']: t for t in p['teachers']}
    busy = defaultdict(list)
    for duty in engine.duties(p):
        ids = [a['teacher_id'] for a in p['invigilation'].get(duty['id'], []) if a.get('teacher_id')]
        if len(ids) != len(set(ids)):
            found.append(f'{duty["id"]} 同一教师重复监考')
        for tid in ids:
            t = teachers[tid]
            if any(_overlap(_event(duty), _event(u)) for u in t['unavailable']):
                found.append(f'{tid} 在不可用时段被安排监考')
            if p['settings'].get('avoid_subject', True) and set(t['subjects']) & set(duty['subjects']):
                found.append(f'{tid} 监考了自己任教的学科')
            busy[tid].append(duty)
    for tid, entries in busy.items():
        for a, b in combinations(entries, 2):
            if _overlap(_event(a), _event(b)):
                found.append(f'{tid} 同一时间监考两场')
    return found


def check_seed(seed):
    p = make_plan(seed)
    steps = {}

    def step(name, result):
        steps[name] = result['status']
        if result['status'] == 'infeasible':
            assert errors.is_user_message(ValueError(result['message'])), f'{name} 无解提示不是中文：{result["message"]}'
            steps[name + '提示'] = result['message']
        return result['status'] in SOLVED + (('partial',) if name == '监考' else ())

    result = engine.schedule(p)
    if not step('日程', result):
        return dict(seed=seed, **steps)
    p = result['plan']
    keys = [None] + [e['id'] for e in p['exams'] if e.get('special_seating')]
    for key in keys:
        result = engine.assign_seats(p, exam_id=key)
        if not step('座位' if key is None else f'单独排座{key}', result):
            return dict(seed=seed, **steps)
        p = result['plan']
    rule = engine.number_rule(p)
    steps['考号方式'] = rule
    base = p['seats'].get('base', {})
    special_only = {s['id'] for s in p['students']} - {s['id'] for e in p['exams'] if not e.get('special_seating')
                                                       for s in engine.participants(p, e)}
    if rule == 'seat':
        # 按考场座位：人人独占固定座位，同一前缀生成考号也必须不重复。
        taken = Counter((x['room_id'], x['seat']) for x in base.values())
        assert all(n == 1 for n in taken.values()), '按考场座位方式下有学生共用固定座位'
        assert set(base) == {s['id'] for s in p['students']}, '按考场座位方式下有学生没有固定座位'
        p = numbering.apply(p, prefix='26', rule='seat', overwrite=True)
    else:
        assert not special_only & set(base), '流水号方式下只考单独排座科目的学生占了固定座位'
        p = numbering.apply(p, prefix='26', rule='serial', overwrite=True)
    steps['只考单独排座人数'] = len(special_only)
    result = engine.assign_invigilators(p)
    step('监考', result)
    p = result['plan']
    found = violations(p)
    if result['status'] == 'partial':
        found = [x for x in found if '监考' not in x]
    assert not found, '；'.join(found[:5])
    return dict(seed=seed, students=len(p['students']), rooms=len(p['rooms']), exams=len(p['exams']), **steps)


def run(recorder, seeds=8, only=None):
    for seed in range(seeds):
        ident = f'PROP-{seed:03}'
        if only and ident not in only:
            continue
        recorder.run(ident, f'随机虚构方案（种子 {seed}）硬规则独立核对', lambda seed=seed: check_seed(seed))
