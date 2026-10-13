"""考号方式决定固定座位规则：按考场座位每人独占座位；流水号可共用座位，只考单独排座科目的学生不占固定座位。
只用虚构示例方案。"""
import io
import json
from collections import Counter
from copy import deepcopy

import openpyxl
import pytest

from exam_room import engine, model, numbering, report
from exam_room.licensing import License
from exam_room.server import App

SPECIAL_ONLY = ('s0-0', 's0-1', 's0-2', 's0-3')


def plan(rule):
    """示例方案：七年级英语单独排座，4 名七年级学生只考英语。"""
    p = model.demo_plan()
    p['settings']['number_rule'] = rule
    next(e for e in p['exams'] if e['id'] == 'e0-2')['special_seating'] = True
    for s in p['students']:
        if s['id'] in SPECIAL_ONLY:
            s['subjects'] = ['英语']
    return model.normalize_plan(p)


def good(result):
    assert result['status'] in ('optimal', 'feasible'), result['message']
    return result['plan']


def arranged(rule):
    p = good(engine.assign_seats(plan(rule)))
    p = good(engine.assign_seats(p, exam_id='e0-2'))
    p = numbering.apply(p, prefix='26', rule=rule, overwrite=True)
    return good(engine.assign_invigilators(p))


def shared_positions(p):
    taken = Counter((x['room_id'], x['seat']) for x in p['seats']['base'].values())
    return [pos for pos, n in taken.items() if n > 1]


def errors(p):
    return {x['code'] for x in engine.validate(p)['errors']}


def test_seat_numbers_give_every_pupil_an_exclusive_fixed_seat():
    p = arranged('seat')
    assert set(p['seats']['base']) == {s['id'] for s in p['students']}
    assert shared_positions(p) == []
    assert len({s['number'] for s in p['students']}) == len(p['students'])
    assert all(len(s['number']) == 6 for s in p['students'])
    assert not errors(p)


def test_seat_numbers_never_share_even_when_times_do_not_overlap():
    # 两个年级考试时间错开，按流水号可以共用座位；按考场座位不行。
    p = plan('serial')
    p['rooms'] = p['rooms'][:2]
    for e in p['exams']:
        if e['grade'] == '八年级':
            e.update(date='2026-11-14')
    p['students'] = [s for s in p['students'] if s['grade'] in ('七年级', '八年级')]
    p['exams'] = [e for e in p['exams'] if e['grade'] in ('七年级', '八年级')]
    p['grades'] = ['七年级', '八年级']
    q = good(engine.assign_seats(p))
    assert shared_positions(q), '流水号方式下时间错开的年级应能共用座位'
    p['settings']['number_rule'] = 'seat'
    result = engine.assign_seats(p)
    assert result['status'] == 'infeasible'
    assert '每人独占一个固定座位' in result['message'] and '改用流水号' in result['message']


def test_serial_numbers_leave_special_only_pupils_without_fixed_seat():
    p = arranged('serial')
    assert not set(SPECIAL_ONLY) & set(p['seats']['base'])
    assert set(SPECIAL_ONLY) <= set(p['seats']['e0-2'])
    assert len({s['number'] for s in p['students']}) == len(p['students'])
    assert not errors(p), engine.validate(p)['errors'][:3]


def test_switching_serial_seating_to_seat_numbers_is_flagged_and_blocked():
    p = arranged('serial')
    p['settings']['number_rule'] = 'seat'
    found = [x for x in engine.validate(p)['errors'] if x['code'] == 'number_rule_mismatch']
    assert found and '请重新编排座位，或改用流水号' in found[0]['message']
    assert found[0]['message'].startswith('当前座位按流水号方式编排（4 人没有固定座位）')
    preview = numbering.preview(p, prefix='26', rule='seat', overwrite=True)
    assert preview['errors'][0]['code'] == 'number_rule_mismatch'
    with pytest.raises(ValueError, match='改用流水号'):
        numbering.apply(p, prefix='26', rule='seat', overwrite=True)
    # 重新按考场座位编排后恢复正常。
    q = good(engine.assign_seats(p))
    assert set(SPECIAL_ONLY) <= set(q['seats']['base']) and not shared_positions(q)
    assert 'number_rule_mismatch' not in errors(q)


def test_old_plan_without_number_rule_is_treated_as_seat_numbers():
    raw = deepcopy(plan('seat'))
    del raw['settings']['number_rule']
    p = model.normalize_plan(raw)
    assert engine.number_rule(p) == 'seat' and engine.number_rule(raw) == 'seat'
    q = good(engine.assign_seats(p))
    assert set(SPECIAL_ONLY) <= set(q['seats']['base']) and not shared_positions(q)


def test_changing_number_rule_keeps_seats_and_check_reports_the_mismatch(tmp_path):
    app = App(tmp_path, License(tmp_path / 'lic', None))
    app.commit(arranged('serial'))
    before = deepcopy(app.plan['seats'])
    q = deepcopy(app.plan)
    q['settings']['number_rule'] = 'seat'
    app.api_save({'plan': q, 'revision': app.plan['revision']})
    assert app.plan['seats'] == before and 'seats' not in app.plan['stale']
    assert 'number_rule_mismatch' in {x['code'] for x in app.view()['validation']['errors']}


@pytest.mark.parametrize('rule', ['seat', 'serial'])
def test_every_material_shows_special_only_pupils_at_their_special_seat(rule):
    p = arranged(rule)
    special = p['seats']['e0-2']
    names = {s['id']: s['name'] for s in p['students']}
    rooms = {r['id']: r['name'] for r in p['rooms']}
    sections = list(report.SECTIONS)
    mats, rows, _ = report.materials(p)
    # 每名只考英语的学生只出现在英语一场，位置是单独排座的座位。
    for sid in SPECIAL_ONLY:
        own = [r for r in rows if r['student_id'] == sid]
        assert [r['exam_id'] for r in own] == ['e0-2']
        assert own[0]['考场'] == rooms[special[sid]['room_id']] and own[0]['座号'] == special[sid]['seat']
    # 按考场学生总表（固定座位范围）里不出现他们。
    from exam_room.printing import room_blocks
    fixed = {r['student_id'] for b in room_blocks(p) for r in b['rows']}
    assert not set(SPECIAL_ONLY) & fixed
    # 16 类材料都能正式导出；含学生的 Excel 表里他们的座号与单独排座一致。
    blob = report.build_excel(p, sections)
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    assert len(wb.sheetnames) >= len(sections)
    html = report.build_html(p, sections)
    for sid in SPECIAL_ONLY:
        assert names[sid] in html
    for key in ('students', 'personal', 'tickets', 'labels', 'rosters', 'seating', 'signins'):
        table = mats[key]
        cols = table['columns']
        for line in table['rows']:
            record = dict(zip(cols, line))
            sid = next((x for x in SPECIAL_ONLY if names[x] == record.get('姓名')), None)
            if sid:
                assert record['科目'] == '英语' and int(record['座号']) == special[sid]['seat'], (key, record)
    # 座次图（按监考岗位）里英语场次显示他们，其他场次不显示。
    from exam_room.printing import document
    doc = document(p, ['seating'])
    assert all(names[sid] in doc['html'] for sid in SPECIAL_ONLY)
