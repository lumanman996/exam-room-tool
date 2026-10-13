"""求解失败后的简单诊断：只读方案数据，找出最可能的原因，给教务人员能直接处理的中文提示。

诊断只在求解器已判定无解后运行，不参与求解，也不改变方案。提示是"可能原因"，不是证明。
"""
from collections import defaultdict
from itertools import combinations


def _engine():
    from . import engine
    return engine


def _when(event):
    d, a, b = event
    return f'{int(d[5:7])}月{int(d[8:10])}日 {a//60:02}:{a%60:02}–{b//60:02}:{b%60:02}'


def _label(exam):
    return f'{exam.get("grade","")}{exam.get("subject","")}'


def _rooms_needed(count, capacities):
    """装下 count 人至少要几个考场（先用大考场）；装不下时返回考场数加一。"""
    total = 0
    for i, cap in enumerate(sorted(capacities, reverse=True), 1):
        total += cap
        if total >= count:
            return i
    return len(capacities) + 1


def _compose(title, hints, advice):
    text = title
    if hints:
        text += '可能原因：' + '；'.join(hints[:3]) + '。'
    return text + advice


def schedule_slot(plan, exam, members, windows):
    """某场考试找不到任何可用时段时，说明是时长、座位还是锁定的问题。"""
    e = _engine()
    duration = e._int(exam.get('duration'))
    rooms = plan.get('rooms', [])
    hints = []
    if exam.get('locked'):
        hints.append('这场考试的时间已锁定，但锁定时间不在允许时段内或与时长不符')
    longest = max((w[2] - w[1] for w in windows), default=0)
    if not windows:
        hints.append('还没有设置允许考试的时段')
    elif longest < duration:
        hints.append(f'允许时段最长 {longest} 分钟，短于考试时长 {duration} 分钟')
    seats = sum(len(e.seat_layout(r)) for r in rooms)
    if seats < len(members):
        hints.append(f'共有 {len(members)} 人参加，全部考场只有 {seats} 个座位')
    elif windows and longest >= duration:
        usable = max((sum(len(e.seat_layout(r)) for r in rooms if e._available(r, (w[0], w[1], w[1] + duration)))
                      for w in windows), default=0)
        if usable < len(members):
            hints.append(f'在允许时段内可用的考场最多只有 {usable} 个座位，不够 {len(members)} 人')
    return _compose(f'{_label(exam)}找不到合适的考试时间。', hints,
                    '请延长允许时段、增加考场或调整考场可用时间。')


def schedule(plan, windows):
    """日程整体无解：常见原因是同一年级的考试在允许时段内排不下。"""
    e = _engine()
    exams = plan.get('exams', [])
    hints = []
    window_minutes = sum(w[2] - w[1] for w in windows)
    by_grade = defaultdict(int)
    for ex in exams:
        by_grade[ex.get('grade', '')] += e._int(ex.get('duration'))
    for grade, minutes in sorted(by_grade.items(), key=lambda x: -x[1]):
        if minutes > window_minutes:
            hints.append(f'{grade}各科合计 {minutes} 分钟，允许时段合计只有 {window_minutes} 分钟')
    seats = sum(len(e.seat_layout(r)) for r in plan.get('rooms', []))
    biggest = {}
    for ex in exams:
        biggest[ex.get('grade', '')] = max(biggest.get(ex.get('grade', ''), 0), len(e.participants(plan, ex)))
    if len(biggest) > 1 and sum(biggest.values()) > seats:
        hints.append(f'各年级同时考试需要约 {sum(biggest.values())} 个座位，全部考场只有 {seats} 个，只能错开时间')
    if plan.get('settings', {}).get('exam_groups'):
        hints.append('已设置的"同时混考组"要求几场考试同一时间进行，也会占用时段和座位')
    return _compose('现有条件下无法安排考试日程。', hints,
                    '可尝试延长或增加允许时段、增加考场，或减少同时混考的要求。')


def seats(plan, exam_id=None):
    """座位无解：按时段比较人数与座位，检查不能混排的年级和时间交错的考试。"""
    e = _engine()
    rooms = plan.get('rooms', [])
    caps = {r['id']: len(e.seat_layout(r)) for r in rooms}
    exams = [x for x in plan.get('exams', []) if e._event(x)]
    sizes = {x['id']: len(e.participants(plan, x)) for x in exams}
    hints = []

    def usable(event):
        return [caps[r['id']] for r in rooms if caps[r['id']] and e._available(r, event)]

    # 1. 某一时刻正在考试的总人数超过可用座位。
    worst = None
    for day, start in sorted({e._event(x)[:2] for x in exams}):
        running = [x for x in exams if e._event(x)[0] == day and e._event(x)[1] <= start < e._event(x)[2]]
        demand = sum(sizes[x['id']] for x in running)
        supply = sum(caps[r['id']] for r in rooms if caps[r['id']] and all(e._available(r, e._event(x)) for x in running))
        if demand > supply and (worst is None or demand - supply > worst[0]):
            moment = _when((day, start, start))[:-6]
            worst = (demand - supply, f'{moment} 起有 {demand} 人同时考试，可用座位只有 {supply} 个')
    if worst:
        hints.append(worst[1])

    # 2. 同一时间的不同年级不允许混排，各自要占用整间考场。
    for event in sorted({e._event(x) for x in exams}):
        grades = defaultdict(int)
        for x in exams:
            if e._event(x) == event:
                grades[x['grade']] += sizes[x['id']]
        if len(grades) > 1 and all(not e._mix(plan, a, b) for a, b in combinations(grades, 2)):
            caps_now = usable(event)
            needed = sum(_rooms_needed(n, caps_now) for n in grades.values())
            if needed > len(caps_now):
                hints.append(f'{_when(event)} {"、".join(grades)}同时考试且不能混排，'
                             f'至少需要 {needed} 个考场，可用 {len(caps_now)} 个')
                break

    # 3. 时间部分重叠但不完全相同的考试不能同场，各自需要考场。
    for a, b in combinations(exams, 2):
        ea, eb = e._event(a), e._event(b)
        if a['grade'] != b['grade'] and ea != eb and e._overlap(ea, eb):
            caps_now = [caps[r['id']] for r in rooms if caps[r['id']] and e._available(r, ea) and e._available(r, eb)]
            needed = _rooms_needed(sizes[a['id']], caps_now) + _rooms_needed(sizes[b['id']], caps_now)
            if needed > len(caps_now):
                hints.append(f'{_label(a)}（{_when(ea)}）与{_label(b)}（{_when(eb)}）时间交错，不能同场，'
                             f'至少需要 {needed} 个考场，可用 {len(caps_now)} 个')
                break

    # 4. 固定座位：学生整次考试坐同一位置。时间安排互相交错或不能混排的几组学生，整次考试都不能共用考场。
    if not exam_id:
        base = [x for x in exams if not x.get('special_seating')]
        members = {x['id']: {s['id'] for s in e.participants(plan, x)} for x in base}
        cohorts = defaultdict(int)
        for s in plan.get('students', []):
            # 没有固定座位场次的学生也要一个不重复的座号来生成考号。
            cohorts[s.get('grade', ''), tuple(sorted(e._event(x) for x in base if s['id'] in members[x['id']]))] += 1
        ordered = sorted(cohorts, key=lambda c: -cohorts[c])
        all_caps = [c for c in caps.values() if c]

        def clique(conflict):
            chosen = []
            for c in ordered:
                if all(conflict(c, d) for d in chosen):
                    chosen.append(c)
            return chosen

        apart = clique(lambda a, b: bool(a[1] and b[1]) and any(not e._compatible(plan, a[0], x, b[0], y) for x in a[1] for y in b[1]))
        needed = sum(_rooms_needed(cohorts[c], all_caps) for c in apart)
        if len(apart) > 1 and needed > len(all_caps):
            desc = '、'.join(f'{c[0]}{cohorts[c]}人' for c in apart[:4])
            hints.append(f'固定座位下有 {len(apart)} 组学生（{desc}）的考试时间互相交错或不能混排，'
                         f'整次考试都不能共用考场，至少需要 {needed} 个考场，只有 {len(all_caps)} 个')
        shared = clique(lambda a, b: e._cohort_conflict(a[1], b[1]))
        total = sum(cohorts[c] for c in shared)
        if total > sum(all_caps):
            idle = sum(cohorts[c] for c in shared if not c[1])
            why = f'（其中 {idle} 人只参加单独排座的科目，仍需固定座号来生成考号）' if idle else ''
            hints.append(f'固定座位下有 {total} 名学生需要各自不同的座位{why}，全部考场只有 {sum(all_caps)} 个')

    # 5. 锁定座位和已排的单独排座都会固定占用位置。
    mapping = plan.get('seats', {}).get(exam_id or 'base', {})
    locked = sum(1 for pos in mapping.values() if pos.get('locked'))
    if locked:
        hints.append(f'有 {locked} 名学生的座位已锁定，编排时不会移动')
    if not exam_id:
        special = [x for x in exams if x.get('special_seating') and plan.get('seats', {}).get(x['id'])]
        if special:
            taken = sum(len(plan['seats'][x['id']]) for x in special)
            hints.append(f'{len(special)} 场单独排座的考试已占用 {taken} 个座位次，同一时段这些位置不能再用')

    advice = '可尝试增加考场、允许相关年级混排、调整考试时间或解除部分锁定。'
    if not exam_id and len({e._event(x) for x in exams if not x.get('special_seating')}) > 1:
        advice +='固定座位要求学生整次考试坐同一位置；某些科目人数或时间差别大时，可将其设为单独排座。'
    return _compose('现有条件下无法完成座位编排。', hints, advice)
