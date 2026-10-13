from copy import deepcopy
import pytest
from test_edit_history import app_fixture
from exam_room import importer
from exam_room.model import normalize_plan


def test_catalog_is_separate_and_subject_batch_skips_existing(tmp_path):
    a=app_fixture(tmp_path);before=deepcopy(a.plan['exams']);catalog=a.view()['subject_catalog']
    assert any(x['name']=='数学' for x in catalog)
    a.api_subject_catalog_save({'catalog':[{'name':'数学','duration':120},{'name':'虚构新科目','duration':35}],'revision':a.plan['revision']})
    assert a.plan['exams']==before
    body={'grades':['七年级','八年级'],'subjects':['数学','虚构新科目'],'date':'2026-12-12','start':'10:00','end':'10:45'}
    pre=a.api_subject_batch_preview(body)
    assert len(pre['exams'])==2 and len(pre['duplicates'])==2
    a.api_subject_batch({**body,'revision':pre['revision']})
    assert all(e['duration']==45 for e in a.plan['exams'] if e['subject']=='虚构新科目')
    a.api_open({'id':a.plan['id']});assert a.view()['subject_catalog'][1]['name']=='虚构新科目'
    a.api_edit_undo({'revision':a.plan['revision']});assert a.plan['exams']==before


def test_complete_times_always_determine_minutes(tmp_path):
    a=app_fixture(tmp_path);q=deepcopy(a.plan);q['exams'][0].update(start='08:20',end='09:55',duration=90)
    a.api_save({'plan':q,'revision':q['revision']});assert a.plan['exams'][0]['duration']==95
    for change in ({'start':'10:00','end':'09:00'},{'start':'','end':'','duration':0},{'start':'','end':'','duration':-1}):
        q=deepcopy(a.plan);q['exams'][0].update(change)
        with pytest.raises(ValueError):a.api_save({'plan':q,'revision':q['revision']})


def test_import_conflicting_duration_requires_clear_resolution(tmp_path):
    a=app_fixture(tmp_path)
    rows=[{'年级':'七','科目':'虚构科目','开始':'08:00','结束':'09:35','分钟':90,'日期':'2026-12-12'}]
    mapping={'grade':'年级','subject':'科目','start':'开始','end':'结束','duration':'分钟','date':'日期'}
    pre=importer.preflight(a.plan,'exams',rows,mapping)
    assert any(e['code']=='duration_mismatch' and e['row']==1 for e in pre['errors'])
    pre=importer.preflight(a.plan,'exams',rows,{k:v for k,v in mapping.items() if k!='duration'})
    assert not pre['errors'] and pre['rows'][0]['duration']==95


def test_catalog_defaults_and_unknown_grade_rejected(tmp_path):
    a=app_fixture(tmp_path)
    with pytest.raises(ValueError):a.api_subject_batch_preview({'grades':['十年级'],'subjects':['语文']})
    with pytest.raises(ValueError):a.api_subject_catalog_save({'catalog':[{'name':'新科','duration':0}],'revision':a.plan['revision']})
    assert any(x['name']=='道德与法治' for x in a.api_defaults({'group':'subjects'})['values'])


def test_batch_update_actual_exam_times_and_used_custom_reset(tmp_path):
    a=app_fixture(tmp_path);a.api_subject_catalog_save({'catalog':[{'name':'虚构自定义','duration':40}],'revision':a.plan['revision']})
    a.api_subject_batch({'grades':['七年级'],'subjects':['虚构自定义'],'revision':a.plan['revision']})
    values=a.api_defaults({'group':'subjects'})['values'];assert any(r['name']=='虚构自定义' for r in values)
    ids=[e['id'] for e in a.plan['exams'] if e['grade']=='七年级']
    body={'kind':'exams','action':'update','ids':ids,'fields':{'date':'2026-12-12','start':'08:20','end':'09:55'}}
    pre=a.api_bulk_preview(body);a.api_bulk_apply({**body,'revision':pre['revision']})
    assert all(e['duration']==95 for e in a.plan['exams'] if e['id'] in ids)


def test_partial_import_duration_cannot_disagree_with_saved_times(tmp_path):
    a=app_fixture(tmp_path)
    pre=importer.preflight(a.plan,'exams',[{'年级':'七','科目':'数学','分钟':95}],{'grade':'年级','subject':'科目','duration':'分钟'},'update')
    assert any(e['code']=='duration_mismatch' for e in pre['errors'])
