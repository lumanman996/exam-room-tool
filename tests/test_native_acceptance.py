"""原生验收不允许用准备完成、其他平台或缺失宿主冒充通过。"""
import json
from pathlib import Path

import pytest


def api():
    from tools import native_acceptance
    return native_acceptance


def test_other_platform_cannot_claim_native_execution():
    with pytest.raises(api().NativeBlocked,match='Windows'):
        api().resolve_platform('windows','darwin')
    assert api().resolve_platform('auto','darwin')=='mac'
    assert api().resolve_platform('auto','win32')=='windows'


def test_missing_native_dependency_and_noninteractive_session_are_blocked():
    with pytest.raises(api().NativeBlocked,match='webview'):
        api().check_runtime('mac',lambda name:False,True)
    with pytest.raises(api().NativeBlocked,match='交互'):
        api().check_runtime('windows',lambda name:True,False)


def test_baseline_checks_product_without_rejecting_new_acceptance_tools():
    reference={'exam_room/server.py':'a','tools/run_testbench.py':'b'}
    current={**reference,'tools/native_acceptance.py':'c'}
    assert api().baseline_changes(reference,current)==[]
    current['exam_room/server.py']='changed'
    assert api().baseline_changes(reference,current)==['exam_room/server.py']


@pytest.mark.parametrize('reference,current,expected',[
    ({r'exam_room\server.py':'old'},{r'exam_room\server.py':'changed'},['exam_room/server.py']),
    ({r'exam_room\server.py':'same'},{'exam_room/server.py':'same'},[]),
    ({'exam_room/server.py':'same'},{r'exam_room\server.py':'same'},[]),
    ({r'exam_room\server.py':'old'},{},['exam_room/server.py']),
    ({},{r'exam_room\new.py':'added'},['exam_room/new.py']),
])
def test_windows_baseline_detects_changed_added_and_removed_product_paths(reference,current,expected):
    assert api().baseline_changes(reference,current)==expected


def test_empty_and_blocked_results_are_not_native_passes():
    assert api().native_exit([])==1
    assert api().native_exit([{'status':'环境阻塞'}])==2
    assert api().native_exit([{'status':'通过'},{'status':'失败'}])==1
    assert api().native_exit([{'status':'通过'}])==0


def test_scoped_pass_never_changes_printing_or_other_platform_checklist():
    rows=api().checklist('mac')
    assert all(r['status']=='未运行' for r in rows)
    assert any(r['platform']=='windows' for r in rows)
    assert any(r['id']=='mac-print-physical' for r in rows)
    assert any(r['id']=='mac-package' for r in rows)


def test_baseline_must_be_finished_full_not_prepare_or_partial():
    with pytest.raises(api().NativeBlocked,match='完整'):
        api().validate_reference({'mode':'prepare','cases':[{'status':'通过'}]})
    with pytest.raises(api().NativeBlocked,match='完整'):
        api().validate_reference({'mode':'full','finished_at':'done','cases':[]})


def test_baseline_requires_every_full_phase_including_randomized():
    phases=('资料准备','源码回归','前端单元','scenarios','随机对抗','browser','scale')
    def report(ids):
        return {'mode':'full','finished_at':'done','cases':[{'status':'通过'}],
                'phase_runs':[{'id':k,'details':{'exit_code':0}} for k in ids],
                'environment':{'source_sha256_before':{'a':'1'},'source_sha256_after':{'a':'1'}}}
    assert api().validate_reference(report(phases))=={'a':'1'}
    with pytest.raises(api().NativeBlocked,match='完整'):
        api().validate_reference(report([k for k in phases if k!='随机对抗']))
