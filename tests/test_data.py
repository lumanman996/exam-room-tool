import json
from pathlib import Path
import pytest
import openpyxl
from exam_room.model import new_plan, normalize_plan, generate_numbers
from exam_room.importer import preview, import_rows, template
from exam_room.storage import Store


def test_numbering_keeps_existing_and_zeros():
    p = new_plan('期末')
    p['grades']=['七年级']
    p['students'] = [{'name':'学生甲','grade':'七年级','class_name':'七1','number':'00001'},
                     {'name':'学生乙','grade':'七年级','class_name':'七1'}]
    p = normalize_plan(p)
    p = generate_numbers(p)
    assert [s['number'] for s in p['students']] == ['00001','00002']
    assert len({s['id'] for s in p['students']}) == 2


def test_import_title_row_and_number_format(tmp_path):
    w = openpyxl.Workbook(); s = w.active
    s.append(['虚构考试']); s.append(['学生姓名','班级','考号','总分'])
    s.append(['学生甲','七1',12,100]); s['C3'].number_format='00000'
    f=tmp_path/'s.xlsx'; w.save(f)
    info=preview(f.read_bytes(),'s.xlsx','students')
    assert info['header_row']==2
    assert info['rows'][0]['考号']=='00012'
    rows=import_rows('students',info['rows'],info['mapping'])
    assert rows[0]['grade']=='七年级' and rows[0]['number']=='00012'
    assert rows[0]['original']['总分']==100


def test_csv_and_templates():
    info=preview('姓名,年级,班级,考号\n学生甲,七年级,七1,00123\n'.encode(),'a.csv','students')
    assert import_rows('students',info['rows'],info['mapping'])[0]['number']=='00123'
    for kind in ('students','rooms','teachers','exams'):
        assert template(kind)[:2]==b'PK'


def test_store_roundtrip_clone_trash_and_recover(tmp_path):
    st=Store(tmp_path); p=normalize_plan(new_plan('测试'))
    p['settings']['seed']=765; st.save(p)
    assert st.load(p['id'])['settings']['seed']==765
    q=st.clone(p['id'],'副本'); assert q['id']!=p['id']
    st.delete(p['id']); assert len(st.list())==1
    assert st.list(True)[0]['id']==p['id']
    st.restore(p['id']); assert len(st.list())==2
    with pytest.raises(ValueError): st.load('../bad')


def test_newer_plan_version_rejected():
    with pytest.raises(ValueError): normalize_plan({'version':99})


def test_common_junior_grade_names_are_normalized():
    p=new_plan();p['students']=[dict(name='虚构甲',grade=7,class_name='701')]
    p['grades']=['七年级']
    p['exams']=[dict(grade='初一',subject='语文')]
    p=normalize_plan(p)
    assert p['students'][0]['grade']==p['exams'][0]['grade']=='七年级'
