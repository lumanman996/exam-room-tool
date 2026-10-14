"""构建支持验证：模拟构建产物，不实际运行 PyInstaller 或签发许可。"""
import json
import io
import subprocess
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('exam_build_support',Path(__file__).resolve().parents[1]/'packaging/build.py')
build=importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def prepare(root):
    (root/'exam_room/ui').mkdir(parents=True)
    (root/'exam_room/ui/index.html').write_text('虚构界面')
    (root/'exam_room/_license_public.json').write_text(json.dumps({'public_key':'A'*43,'contact':''}))
    (root/'exam_room/_license_impl.py').write_text('import json\n')
    (root/'packaging').mkdir()
    (root/'packaging/entry.py').write_text('pass')
    (root/'dist').mkdir()
    (root/'dist/previous.zip').write_bytes(b'previous candidate')
    (root/'docs').mkdir()
    (root/'docs/使用手册.md').write_text('虚构手册')
    (root/'docs/开始使用.txt').write_text('开始使用')


def test_failed_build_keeps_previous_delivery(tmp_path,monkeypatch):
    prepare(tmp_path)
    monkeypatch.setattr(build,'ROOT',tmp_path)
    def fail(*args,**kwargs):raise subprocess.CalledProcessError(1,['PyInstaller'])
    monkeypatch.setattr(build.subprocess,'run',fail)
    with pytest.raises(subprocess.CalledProcessError):build.main([])
    assert (tmp_path/'dist/previous.zip').read_bytes()==b'previous candidate'


def test_delivery_resources_are_blank_and_fictional(tmp_path,monkeypatch):
    import openpyxl
    prepare(tmp_path);monkeypatch.setattr(build,'ROOT',tmp_path)
    folder=tmp_path/'candidate';folder.mkdir()
    build.delivery_resources(folder)
    assert (folder/'使用手册.md').read_text()=='虚构手册'
    assert (folder/'开始使用.txt').read_text()=='开始使用'
    files=list((folder/'模板').glob('*.xlsx'));assert len(files)==4
    for path in files:
        wb=openpyxl.load_workbook(path)
        assert wb['填写资料'].max_row==1
        assert '空白' in wb['填写说明']['A1'].value
        wb.close()
    example=json.loads((folder/'虚构示例方案.json').read_text())
    assert '虚构' in example['name'] and example['students']


def test_publish_failure_restores_old_candidate(tmp_path,monkeypatch):
    folder=tmp_path/'work/考场编排-Windows';folder.mkdir(parents=True)
    (folder/'new.exe').write_bytes(b'new')
    archive=tmp_path/'work/exam-room-tool-Windows.zip';archive.write_bytes(b'new zip')
    output=tmp_path/'dist';old=output/folder.name;old.mkdir(parents=True)
    (old/'old.exe').write_bytes(b'old')
    (output/archive.name).write_bytes(b'old zip')
    def fail(*args):raise OSError('fictional publish failure')
    monkeypatch.setattr(build.os,'replace',fail)
    with pytest.raises(OSError):build.publish(folder,archive,output)
    assert (old/'old.exe').read_bytes()==b'old'
    assert (output/archive.name).read_bytes()==b'old zip'
    assert not list(output.glob('.*.tmp'))


@pytest.mark.parametrize('value',[{}, {'public_key':'invalid'}, {'public_key':'A'*43,'unexpected':'fictional'}])
def test_invalid_public_config_refused_before_build(tmp_path,value):
    path=tmp_path/'public.json';path.write_text(json.dumps(value))
    with pytest.raises(ValueError):build.validate_public_config(path)


def test_windows_command_collects_solver_native_host_and_ca_bundle(tmp_path,monkeypatch):
    monkeypatch.setattr(build,'MAC',False)
    cmd=build.build_command(tmp_path,tmp_path/'public.json')
    for item in ['ortools','certifi','webview.platforms.winforms','webview.platforms.edgechromium']:assert item in cmd
    assert cmd[cmd.index('--distpath')+1]==str(tmp_path/'dist')


def test_mocked_windows_candidate_contains_only_delivery_resources(tmp_path,monkeypatch):
    import zipfile
    prepare(tmp_path);monkeypatch.setattr(build,'ROOT',tmp_path);monkeypatch.setattr(build,'MAC',False)
    (tmp_path/'admin').mkdir();(tmp_path/'admin/not-for-delivery.txt').write_text('fictional administrator fixture')
    def simulate(cmd,**kwargs):
        if '--distpath' not in cmd:
            (Path(kwargs['cwd'])/'exam_room/_license_impl.test.pyd').write_bytes(b'fictional native')
            return subprocess.CompletedProcess(cmd,0)
        dest=Path(cmd[cmd.index('--distpath')+1])/'考场编排';dest.mkdir(parents=True)
        (dest/'考场编排.exe').write_bytes(b'fictional executable')
        (dest/'_license_impl.test.pyd').write_bytes(b'fictional native')
        return subprocess.CompletedProcess(cmd,0)
    monkeypatch.setattr(build.subprocess,'run',simulate)
    archive=build.main([])
    assert (tmp_path/'dist/previous.zip').read_bytes()==b'previous candidate'
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        assert '考场编排-Windows/考场编排.exe' in names
        assert '考场编排-Windows/开始使用.txt' in names
        assert '考场编排-Windows/虚构示例方案.json' in names
        assert not any('/admin/' in p or '/output/' in p for p in names)
        manifest=json.loads(z.read('考场编排-Windows/交付清单.json'))
        from exam_room import VERSION
        assert manifest['version']==VERSION and manifest['status']=='待包内与平台验收'
        assert any(p['path']=='考场编排.exe' and p['sha256'] for p in manifest['files'])


def test_smoke_report_does_not_turn_json_failure_into_success(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('exam_smoke_support',Path(__file__).resolve().parents[1]/'packaging/smoke_test.py')
    smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
    def fake(*args,**kwargs):return subprocess.CompletedProcess(args[0],0,'{"ok":false}\n','')
    monkeypatch.setattr(smoke.subprocess,'run',fake)
    report=tmp_path/'report.json'
    with pytest.raises(SystemExit):smoke.main(['--report',str(report)])
    assert not json.loads(report.read_text())['ok']


def test_entry_no_console_selftest_keeps_real_receipt(tmp_path):
    import os,sys
    entry=Path(__file__).parents[1]/'packaging/entry.py'
    code="import sys,runpy;sys.stdout=sys.stderr=None;sys.argv=['entry','--selftest'];runpy.run_path(sys.argv[0] if False else "+repr(str(entry))+",run_name='__main__')"
    env={**os.environ,'PYTHONPATH':str(entry.parents[1]),'EXAM_ROOM_HOME':str(tmp_path),
         'EXAM_ROOM_SELFTEST_RUN_ID':'fictional-smoke-run','EXAM_ROOM_NO_UPDATE_CHECK':'1'}
    result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,timeout=45)
    assert result.returncode==0,result.stderr
    receipt=tmp_path/'selftest-result.json'
    assert receipt.is_file(),'无控制台自检缺少实际结果回执'
    data=json.loads(receipt.read_text(encoding='utf-8'))
    assert data['ok'] and data['exit_code']==0 and data['run_id']=='fictional-smoke-run'
    assert data['selftest_result']['ok'] is True
    assert 'importing_application' in (tmp_path/'startup.log').read_text(encoding='utf-8')


def test_entry_import_failure_is_logged_and_exits_without_selftest_dialog(tmp_path):
    import os,sys
    entry=Path(__file__).parents[1]/'packaging/entry.py'
    code="""import sys,runpy,builtins
original=builtins.__import__
def fail(name,*args,**kwargs):
    if name=='exam_room.app':raise ModuleNotFoundError('fictional missing startup dependency')
    return original(name,*args,**kwargs)
builtins.__import__=fail
sys.stdout=sys.stderr=None
sys.argv=['entry','--selftest']
runpy.run_path(ENTRY,run_name='__main__')
""".replace('ENTRY',repr(str(entry)))
    result=subprocess.run([sys.executable,'-c',code],env={**os.environ,'PYTHONPATH':str(entry.parents[1]),
        'EXAM_ROOM_HOME':str(tmp_path),'EXAM_ROOM_SELFTEST_RUN_ID':'fictional-failed-run'},capture_output=True,timeout=10)
    assert result.returncode==1
    assert (tmp_path/'startup.log').is_file(),'入口导入错误未留下诊断'
    assert 'fictional missing startup dependency' in (tmp_path/'startup.log').read_text(encoding='utf-8')
    receipt=json.loads((tmp_path/'selftest-result.json').read_text(encoding='utf-8'))
    assert not receipt['ok'] and receipt['last_stage']=='importing_application'


def smoke_support():
    spec=importlib.util.spec_from_file_location('exam_smoke_support',Path(__file__).parents[1]/'packaging/smoke_test.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_smoke_timeout_retains_partial_output_and_isolated_startup_log(tmp_path,monkeypatch):
    smoke=smoke_support()
    def timeout(cmd,**kwargs):
        Path(kwargs['env']['EXAM_ROOM_HOME'],'startup.log').write_text('running_selftest\nfictional waiting stack',encoding='utf-8')
        raise subprocess.TimeoutExpired(cmd,180,output=b'partial output',stderr=b'partial error')
    monkeypatch.setattr(smoke.subprocess,'run',timeout)
    report=tmp_path/'timeout.json'
    with pytest.raises(SystemExit):smoke.main(['--report',str(report)])
    data=json.loads(report.read_text(encoding='utf-8'))
    assert data['timeout'] and data['stdout']=='partial output' and data['stderr']=='partial error'
    assert 'fictional waiting stack' in Path(data['diagnostics']['startup.log']).read_text(encoding='utf-8')


def test_frozen_zero_exit_without_selftest_receipt_is_not_pass(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sys
    smoke=smoke_support();monkeypatch.setattr(smoke,'ROOT',tmp_path)
    monkeypatch.setattr(smoke,'sys',SimpleNamespace(platform='win32',executable=sys.executable))
    exe=tmp_path/'dist/考场编排-Windows/考场编排.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'fake executable')
    monkeypatch.setattr(smoke.subprocess,'run',lambda cmd,**kwargs:subprocess.CompletedProcess(cmd,0,'',''))
    report=tmp_path/'missing.json'
    with pytest.raises(SystemExit):smoke.main(['--frozen','--report',str(report)])
    data=json.loads(report.read_text(encoding='utf-8'))
    assert not data['ok'] and data['diagnosis']=='entry_not_observed'


def reference_data():
    files={'exam_room/app.py':'a'*64,'tests/test_packaging.py':'b'*64}
    full=dict(mode='full',started_at='original-start',finished_at='original-finish',
        cases=[dict(id=f'C{i}',status='通过') for i in range(61)],
        summary={'通过':61,'失败':0,'环境阻塞':0,'未运行':0},
        environment=dict(system='Windows-2022Server-10.0.20348-SP0',git_commit='9'*40,
            source_sha256_before=files.copy(),source_sha256_after=files.copy()),
        phase_runs=[dict(id=k,status='通过',details={'exit_code':0,'timeout':False}) for k in ('资料准备','源码回归','前端单元','scenarios','随机对抗','browser','scale')])
    baseline=r'D:\a\exam-room-tool\output\testbench\reference\report.json'
    cases=[dict(id='NATIVE-baseline',status='通过',details={'reference':baseline,'changed_product_files':[]}),
           dict(id='NATIVE-host-first',status='通过'),dict(id='NATIVE-host-reopen',status='通过')]
    native=dict(mode='原生验收：run',platform='windows',finished_at='native-original-finish',cases=cases,
        environment=dict(host='win32',source_sha256_before=files.copy(),source_sha256_after=files.copy()),
        summary={'通过':3,'失败':0,'环境阻塞':0,'未运行':0},
        phase_runs=[dict(id=k,status='通过',details={'exit_code':0,'timeout':False}) for k in ('原生-first','原生-reopen')])
    terminal=dict(mode='run',native_requested=True,selected_platform='windows',exit_code=0,summary=native['summary'].copy())
    return full,native,terminal,baseline,files.copy()


def test_reference_only_packaging_test_change_allowed():
    verify=getattr(build,'verify_windows_reports',None)
    assert callable(verify),'未实现Windows严格基线复用校验'
    full,native,terminal,baseline,current=reference_data();current['tests/test_packaging.py']='c'*64
    result=verify(full,native,terminal,baseline,'reference',current)
    assert result['allowed_changed_files']==['tests/test_packaging.py']
    assert result['original_commit']==full['environment']['git_commit']
    assert not result['full_rerun'] and not result['native_rerun']


@pytest.mark.parametrize('bad',['platform','unfinished','case_failed','phase_timeout','business','other_test','missing_file','native_platform','native_terminal','native_baseline','native_fingerprint'])
def test_reference_rejects_incompatible_or_unverified_evidence(bad):
    verify=getattr(build,'verify_windows_reports',None)
    assert callable(verify),'未实现Windows严格基线复用校验'
    full,native,terminal,baseline,current=reference_data()
    if bad=='platform':full['environment']['system']='macOS'
    elif bad=='unfinished':full.pop('finished_at')
    elif bad=='case_failed':full['cases'][0]['status']='失败'
    elif bad=='phase_timeout':full['phase_runs'][0]['details']['timeout']=True
    elif bad=='business':current['exam_room/app.py']='c'*64
    elif bad=='other_test':current['tests/other.py']='c'*64
    elif bad=='missing_file':current.pop('tests/test_packaging.py')
    elif bad=='native_platform':native['platform']='mac'
    elif bad=='native_terminal':terminal['exit_code']=1
    elif bad=='native_baseline':native['cases'][0]['details']['reference']='different/report.json'
    elif bad=='native_fingerprint':native['environment']['source_sha256_after']['exam_room/app.py']='d'*64
    with pytest.raises(ValueError):verify(full,native,terminal,baseline,'reference',current)


def entry_support():
    spec=importlib.util.spec_from_file_location('exam_entry_support',Path(__file__).parents[1]/'packaging/entry.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_normal_startup_failure_has_simple_visible_notice(tmp_path,monkeypatch):
    from types import SimpleNamespace
    entry=entry_support();messages=[]
    monkeypatch.setenv('EXAM_ROOM_HOME',str(tmp_path));monkeypatch.setattr(entry.sys,'argv',['entry'])
    def fail():raise RuntimeError('fictional startup failure')
    monkeypatch.setitem(entry.sys.modules,'exam_room.app',SimpleNamespace(main=fail))
    monkeypatch.setattr(entry,'_notify_failure',lambda path:messages.append(str(path)),raising=False)
    assert entry.bootstrap()==1
    assert len(messages)==1 and 'startup.log' in messages[0]
    assert 'fictional startup failure' in (tmp_path/'startup.log').read_text(encoding='utf-8')


def test_startup_log_failure_notifies_normal_user_but_never_selftest(tmp_path,monkeypatch):
    entry=entry_support();messages=[];blocked=tmp_path/'not-a-directory';blocked.write_text('fictional')
    monkeypatch.setenv('EXAM_ROOM_HOME',str(blocked))
    monkeypatch.setattr(entry,'_notify_failure',lambda path:messages.append(str(path)),raising=False)
    monkeypatch.setattr(entry.sys,'argv',['entry']);assert entry.bootstrap()==1
    assert len(messages)==1
    monkeypatch.setattr(entry.sys,'argv',['entry','--selftest']);assert entry.bootstrap()==1
    assert len(messages)==1


@pytest.mark.parametrize('valid',[True,False])
def test_frozen_receipt_must_match_this_process_run(tmp_path,monkeypatch,valid):
    from types import SimpleNamespace
    import sys
    smoke=smoke_support();monkeypatch.setattr(smoke,'ROOT',tmp_path)
    monkeypatch.setattr(smoke,'sys',SimpleNamespace(platform='win32',executable=sys.executable))
    exe=tmp_path/'dist/考场编排-Windows/考场编排.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'fake executable')
    def frozen(cmd,**kwargs):
        folder=Path(kwargs['env']['EXAM_ROOM_HOME'])
        (folder/'startup.log').write_text('entry_started\napplication_returned',encoding='utf-8')
        receipt={'ok':True,'exit_code':0,'run_id':kwargs['env']['EXAM_ROOM_SELFTEST_RUN_ID'] if valid else 'wrong-run',
                 'selftest_result':{'ok':True,'license_module_kind':'native','license_product':'exam-room-tool'}}
        (folder/'selftest-result.json').write_text(json.dumps(receipt),encoding='utf-8')
        return subprocess.CompletedProcess(cmd,0,'','')
    monkeypatch.setattr(smoke.subprocess,'run',frozen);report=tmp_path/'receipt.json'
    if valid:assert smoke.main(['--frozen','--report',str(report)])==0
    else:
        with pytest.raises(SystemExit):smoke.main(['--frozen','--report',str(report)])
    data=json.loads(report.read_text(encoding='utf-8'))
    assert data['ok'] is valid and data['receipt_verified'] is valid and not data['json_observed']


def test_reference_preserves_compliant_native_environment_block():
    full,native,terminal,baseline,current=reference_data()
    native['cases']=[native['cases'][0],dict(id='NATIVE-environment',status='环境阻塞')]
    native['phase_runs']=[];native['summary']={'通过':1,'失败':0,'环境阻塞':1,'未运行':0}
    terminal.update(exit_code=2,summary=native['summary'].copy())
    result=build.verify_windows_reports(full,native,terminal,baseline,'reference',current)
    assert result['original_native_exit_code']==2 and not result['final_platform_accepted']


def test_reference_input_requires_positive_numeric_run_and_one_report(tmp_path):
    for value in ('', '0', '-1', '../other', '37707978489x'):
        with pytest.raises(ValueError):build.verify_windows_reference(tmp_path,value)
    with pytest.raises(ValueError):build.verify_windows_reference(tmp_path,'37707978489')


def test_frozen_receipt_rejects_python_license_even_if_ok_and_exit_zero(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sys
    smoke=smoke_support();monkeypatch.setattr(smoke,'ROOT',tmp_path)
    monkeypatch.setattr(smoke,'sys',SimpleNamespace(platform='win32',executable=sys.executable))
    exe=tmp_path/'dist/考场编排-Windows/考场编排.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'fake executable')
    def frozen(cmd,**kwargs):
        receipt={'ok':True,'exit_code':0,'run_id':kwargs['env']['EXAM_ROOM_SELFTEST_RUN_ID'],
                 'selftest_result':{'ok':True,'license_module_kind':'python','license_product':'exam-room-tool'}}
        (Path(kwargs['env']['EXAM_ROOM_HOME'])/'selftest-result.json').write_text(json.dumps(receipt))
        return subprocess.CompletedProcess(cmd,0,'','')
    monkeypatch.setattr(smoke.subprocess,'run',frozen)
    with pytest.raises(SystemExit):smoke.main(['--frozen','--report',str(tmp_path/'report.json')])
    assert not json.loads((tmp_path/'report.json').read_text())['ok']
