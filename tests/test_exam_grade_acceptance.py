"""测试方独立真实HTTP验收；新方案的年级范围不能由导入资料改变。"""
from copy import deepcopy
import pytest

from tools.testbench.common import load,service

GRADES=['七年级','八年级','九年级']


def disk(client,p):return client.app.store.path(p['id']).read_bytes()


def unchanged(client,before,blob):
    assert client.call('state')['plan']==before
    assert disk(client,before)==blob


def import_body(p,grade):
    return dict(kind='students',mode='replace',revision=p['revision'],
        rows=[{'姓名':'虚构新生','年级':grade,'班级':grade+'虚构1班','考号':'001001'}],
        mapping={'name':'姓名','grade':'年级','class_name':'班级','number':'考号'})


def explicit():
    p=load('C01_tiny_completed');p['grades']=GRADES[:]
    p['settings']['mix_presets']=[{'id':'fictional-preset','name':'虚构七八合编','groups':[GRADES[:2]]}]
    return p


def test_empty_exam_retains_all_three_configured_grades(tmp_path):
    with service(tmp_path/'empty') as client:
        p=client.call('new',{'name':'虚构无学生三年级','grades':GRADES})['plan']
        assert p.get('grades')==GRADES
        assert not p['students'] and not p['exams']
        assert client.app.store.load(p['id'])['grades']==GRADES


def test_two_student_grades_do_not_remove_third_and_presets_reopen(tmp_path):
    with service(tmp_path/'persist',explicit()) as client:
        p=client.call('state')['plan'];assert p['grades']==GRADES
        assert {s['grade'] for s in p['students']}==set(GRADES[:2])
        p['settings']['mix_grades']=True;p['settings']['mix_groups']=[GRADES[:2]]
        p=client.call('save',{'plan':p,'revision':p['revision']})['plan']
        assert p['settings']['mix_presets']==explicit()['settings']['mix_presets']
    with service(tmp_path/'persist') as client:
        loaded=client.call('open',{'id':p['id']})['plan']
        assert loaded==p and loaded['grades']==GRADES
        assert loaded['settings']['mix_groups']==[GRADES[:2]]


@pytest.mark.parametrize('grades,unknown',[([],GRADES[0]),(GRADES,'十年级')])
def test_unset_or_unknown_grade_preflight_and_import_are_atomic(tmp_path,grades,unknown):
    with service(tmp_path/'import') as client:
        p=client.call('new',{'name':'虚构导入拒绝','grades':grades})['plan'];blob=disk(client,p)
        body=import_body(p,unknown)
        preview=client.call('import_preflight',body)
        assert preview['errors'],'未设置或未知年级未被预检拒绝'
        assert not client.raw('import',body)['ok']
        unchanged(client,p,blob)
        assert client.call('state')['plan'].get('grades')==grades


def test_unknown_grade_cannot_bypass_preflight_by_saving_plan(tmp_path):
    with service(tmp_path/'save',explicit()) as client:
        p=client.call('state')['plan'];blob=disk(client,p);bad=deepcopy(p)
        bad['students'][0]['grade']='十年级'
        response=client.raw('save',{'plan':bad,'revision':p['revision']})
        assert not response['ok'],'直接保存绕过了本次考试年级范围'
        unchanged(client,p,blob)


@pytest.mark.parametrize('groups',[[[GRADES[0]]],[[GRADES[0],'十年级']],[GRADES[:2],GRADES[1:]]])
def test_preset_rejects_single_unknown_or_overlapping_groups(tmp_path,groups):
    with service(tmp_path/'preset',explicit()) as client:
        p=client.call('state')['plan'];blob=disk(client,p);bad=deepcopy(p)
        bad['settings']['mix_presets']=[{'id':'bad','name':'虚构非法组','groups':groups}]
        assert not client.raw('save',{'plan':bad,'revision':p['revision']})['ok']
        unchanged(client,p,blob)


def test_referenced_grade_removal_keeps_all_existing_data(tmp_path):
    with service(tmp_path/'remove',explicit()) as client:
        p=client.call('state')['plan'];blob=disk(client,p);bad=deepcopy(p)
        bad['grades']=GRADES[1:];bad['settings']['mix_presets']=[]
        assert not client.raw('save',{'plan':bad,'revision':p['revision']})['ok']
        unchanged(client,p,blob)


def test_legacy_missing_field_migrates_but_explicit_empty_does_not(tmp_path):
    legacy=load('C01_tiny_completed');assert 'grades' not in legacy
    with service(tmp_path/'legacy',legacy) as client:
        p=client.call('state')['plan'];assert p.get('grades')==GRADES[:2]
    with service(tmp_path/'explicit') as client:
        p=client.call('new',{'name':'虚构显式空年级','grades':[]})['plan']
        assert p.get('grades')==[]


def test_grade_list_change_marks_existing_arrangement_for_review(tmp_path):
    with service(tmp_path/'stale',explicit()) as client:
        p=client.call('state')['plan'];before=deepcopy(p['seats'])
        p['grades'].append('十年级')
        updated=client.call('save',{'plan':p,'revision':p['revision']})['plan']
        assert updated['grades']==GRADES+['十年级']
        assert updated['seats']==before
        assert {'seats','invigilation'}<=set(updated['stale'])
