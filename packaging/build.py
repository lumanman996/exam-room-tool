"""按本机平台构建候选包；失败保留旧交付，日志与临时产物独立保存。"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
NAME='考场编排'
MAC=sys.platform=='darwin'


def validate_public_config(path):
    if not path.is_file():raise ValueError('缺少本产品公钥配置；请由许可管理员提供，勿重新生成既有密钥。')
    try:
        cfg=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(cfg,dict) or set(cfg)-{'public_key','contact'}:raise ValueError()
        key=cfg['public_key']
        if not isinstance(key,str) or not isinstance(cfg.get('contact',''),str):raise ValueError()
        raw=base64.urlsafe_b64decode(key+'='*(-len(key)%4))
        if len(raw)!=32:raise ValueError()
        Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError,KeyError,TypeError):raise ValueError('公钥配置格式无效或含有不允许的字段。') from None
    return hashlib.sha256(raw).hexdigest()


def build_command(work,public,license_build=None):
    sep=':' if MAC else ';'
    cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed','--name',NAME,
         '--distpath',str(work/'dist'),'--workpath',str(work/'build'),'--specpath',str(work),
         '--paths',str(license_build['stage'] if license_build else ROOT),'--add-data',f'{ROOT/"exam_room"/"ui"}{sep}exam_room/ui',
         '--add-data',f'{public}{sep}exam_room','--collect-all','ortools','--collect-data','certifi',
         '--exclude-module','pytest','--exclude-module','playwright']
    if MAC:cmd+=['--osx-bundle-identifier','cn.examroom.tool','--hidden-import','webview.platforms.cocoa']
    else:cmd+=['--hidden-import','webview.platforms.winforms','--hidden-import','webview.platforms.edgechromium']
    cmd+=['--hidden-import','exam_room._license_impl','--hidden-import','exam_room._build_info']
    for name in (license_build or {}).get('hidden_imports',[]):cmd+=['--hidden-import',name]
    return cmd+[str(ROOT/'packaging/entry.py')]


def publish(folder,archive,output):
    """同平台旧候选先保留为备份，发布失败恢复；不清空 dist。"""
    output.mkdir(parents=True,exist_ok=True)
    target=output/folder.name
    previous=output/('.'+folder.name+'-'+uuid.uuid4().hex+'.previous')
    had_previous=target.exists()
    if had_previous:target.rename(previous)
    try:
        shutil.move(str(folder),str(target))
        pending=output/('.'+archive.name+'-'+uuid.uuid4().hex+'.tmp')
        try:
            shutil.copyfile(archive,pending)
            os.replace(pending,output/archive.name)
        finally:pending.unlink(missing_ok=True)
    except Exception:
        shutil.rmtree(target,ignore_errors=True)
        if had_previous:previous.rename(target)
        raise
    if had_previous:shutil.rmtree(previous)
    return output/archive.name


def delivery_resources(folder):
    """仅复制明确的使用资料，生成空白模板与虚构方案。"""
    import openpyxl
    from exam_room.importer import template
    from exam_room.model import demo_plan
    for name in ('使用手册.md','开始使用.txt'):
        shutil.copyfile(ROOT/'docs'/name,folder/name)
    templates=folder/'模板';templates.mkdir()
    for kind,label in [('students','学生名单'),('rooms','考场资料'),('teachers','教师资料'),('exams','考试日程')]:
        wb=openpyxl.load_workbook(io.BytesIO(template(kind)))
        ws=wb['填写资料'];ws.delete_rows(2,ws.max_row-1);ws.auto_filter.ref=ws.dimensions
        wb['填写说明']['A1']='这是空白模板，请从第二行填写资料。'
        wb.save(templates/f'{label}空白模板.xlsx');wb.close()
    example=demo_plan();example['name']='虚构示例考试（仅供练习）'
    (folder/'虚构示例方案.json').write_text(json.dumps(example,ensure_ascii=False,indent=2),encoding='utf-8')


def delivery_manifest(folder,system):
    from exam_room import VERSION
    files=[]
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            target=os.readlink(path)
            files.append(dict(path=str(path.relative_to(folder)),symlink=target,
                              sha256=hashlib.sha256(target.encode()).hexdigest()))
        elif path.is_file():
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            files.append(dict(path=str(path.relative_to(folder)),size=path.stat().st_size,sha256=digest))
    data=dict(product='exam-room-tool',version=VERSION,platform=system,arch=platform.machine(),
              created=datetime.now().astimezone().isoformat(),status='待包内与平台验收',files=files)
    (folder/'交付清单.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return data


def verify_windows_reports(full,native,terminal,baseline,full_directory,current):
    """Reuse only completed Windows source evidence and an exact source snapshot."""
    from tools.native_acceptance import validate_reference,NativeBlocked
    try:
        reference=validate_reference(full)
        if (full.get('summary')!={'通过':len(full['cases']),'失败':0,'环境阻塞':0,'未运行':0}
            or not full['environment']['system'].startswith('Windows-')
            or any(p['details'].get('timeout') is not False for p in full['phase_runs'])):
            raise ValueError('基线不是完成且通过的 Windows 完整验测。')
        if set(reference)!=set(current):raise ValueError('受验测文件范围有新增或删除，不能复用。')
        changed=sorted(k for k in reference if reference[k]!=current[k])
        if set(changed)-{'tests/test_packaging.py'}:raise ValueError('业务、资料、工具或其他测试有变化，不能复用：'+', '.join(changed))
        if (native.get('mode')!='原生验收：run' or native.get('platform')!='windows'
            or not native.get('finished_at') or native['environment'].get('host')!='win32'
            or native['environment'].get('source_sha256_before')!=reference
            or native['environment'].get('source_sha256_after')!=reference
            or terminal.get('mode')!='run' or terminal.get('native_requested') is not True
            or terminal.get('selected_platform')!='windows'):
            raise ValueError('原生证据不是同一稳定 Windows 源码基线。')
        normalize=lambda value:str(value).replace('\\','/').rstrip('/').casefold()
        expected=normalize(baseline)
        if expected.split('/')[-2:]!=[full_directory.casefold(),'report.json']:raise ValueError('原full路径与下载报告不一致。')
        baseline_cases=[c for c in native['cases'] if c['id']=='NATIVE-baseline']
        if len(baseline_cases)!=1 or baseline_cases[0]['status']!='通过':raise ValueError('原生基线未通过。')
        details=baseline_cases[0]['details']
        if normalize(details['reference'])!=expected or details.get('changed_product_files')!=[]:raise ValueError('原生专项引用了不同的full。')
        summary={s:sum(c['status']==s for c in native['cases']) for s in ('通过','失败','环境阻塞','未运行')}
        if native['summary']!=summary or terminal.get('summary')!=summary:raise ValueError('原生报告与终态汇总不同。')
        code=terminal.get('exit_code');ids={c['id'] for c in native['cases']}
        if code==0:
            if (any(c['status']!='通过' for c in native['cases'])
                or not {'NATIVE-host-first','NATIVE-host-reopen'}<=ids
                or len(native['phase_runs'])!=2
                or any(p.get('status')!='通过' or p['details'].get('exit_code')!=0 or p['details'].get('timeout') is not False for p in native['phase_runs'])):
                raise ValueError('原生专项没有实际通过。')
        elif code==2:
            if (native['phase_runs'] or any(c['status'] not in ('通过','环境阻塞') for c in native['cases'])
                or not any(c['id']=='NATIVE-environment' and c['status']=='环境阻塞' for c in native['cases'])):
                raise ValueError('原生终态不是合规环境阻塞。')
        else:raise ValueError('原生专项实际失败，不能复用。')
    except NativeBlocked as exc:
        raise ValueError(str(exc)) from exc
    except (KeyError,TypeError,AttributeError) as exc:
        raise ValueError('基线证据字段缺失或无效。') from exc
    return dict(allowed_changed_files=changed,original_commit=full['environment']['git_commit'],
                original_started_at=full.get('started_at'),original_finished_at=full['finished_at'],
                original_native_finished_at=native['finished_at'],original_native_exit_code=code,
                full_rerun=False,native_rerun=False,final_platform_accepted=False,
                packaging_tests_retested=False,reference_verified=True)


def verify_windows_reference(directory,run_id):
    import re
    from tools.run_testbench import source_fingerprint
    if not re.fullmatch(r'[0-9]+',run_id) or int(run_id)<=0:raise ValueError('参考运行编号须为正整数。')
    directory=directory.resolve();reports=list((directory/'testbench').glob('*/report.json'))
    if len(reports)!=1:raise ValueError('参考附件必须仅有一份完整报告。')
    read=lambda path:json.loads(path.read_text(encoding='utf-8'))
    full_path=reports[0];full=read(full_path);native=read(directory/'ci/native/report.json')
    terminal=read(directory/'ci/native/terminal.json');baseline=read(directory/'ci/full-baseline.json')['report']
    result=verify_windows_reports(full,native,terminal,baseline,full_path.parent.name,source_fingerprint())
    result.update(reference_run_id=run_id,reference_artifact='exam-room-tool-evidence-windows-2022-'+run_id,
                  reference_repository=os.environ.get('GITHUB_REPOSITORY',''),
                  verified_at=datetime.now().astimezone().isoformat())
    target=ROOT/'output/ci/reference-baseline';target.mkdir(parents=True,exist_ok=True)
    for name in ('report.json','report.html','pytest.xml'):
        source=full_path.parent/name
        if source.is_file():shutil.copyfile(source,target/name)
    shutil.copytree(directory/'ci/native',target/'native',dirs_exist_ok=True)
    (ROOT/'output/ci/reference-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));return result


def main(argv=None):
    parser=argparse.ArgumentParser(description='构建考场编排内部候选包，不公开发布')
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    parser.add_argument('--work-dir',type=Path,default=ROOT/'output/build-runs')
    parser.add_argument('--verify-reference',type=Path)
    parser.add_argument('--reference-run-id',default='')
    args=parser.parse_args(argv)
    if args.verify_reference:return verify_windows_reference(args.verify_reference,args.reference_run_id)
    public=ROOT/'exam_room/_license_public.json'
    key_fingerprint=validate_public_config(public)
    for name in ('使用手册.md','开始使用.txt'):
        if not (ROOT/'docs'/name).is_file():raise FileNotFoundError('交付资料缺失：'+name)
    run=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    work=args.work_dir.resolve()/run;work.mkdir(parents=True)
    system='Mac' if MAC else 'Windows'
    cmd=build_command(work,public)
    manifest=dict(started=datetime.now().astimezone().isoformat(),platform=platform.platform(),
                  arch=platform.machine(),python=sys.version,system=system,
                  public_key_sha256=key_fingerprint,command=cmd,status='building')
    try:
        import importlib.util
        spec=importlib.util.spec_from_file_location('exam_room_compile_license',Path(__file__).with_name('compile_license.py'))
        compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)
        compiled_license=compiler.compiled_license
        with compiled_license(ROOT,work) as license_build:
            cmd=build_command(work,public,license_build);manifest['command']=cmd
            manifest['license_module_sha256']=hashlib.sha256(license_build['native'].read_bytes()).hexdigest()
            with (work/'build.log').open('w',encoding='utf-8') as log:
                subprocess.run(cmd,check=True,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        folder=work/f'{NAME}-{system}';folder.mkdir()
        if MAC:
            src=work/'dist'/f'{NAME}.app'
            if not src.is_dir():raise FileNotFoundError('构建没有生成 Mac 应用包。')
            shutil.move(str(src),str(folder/src.name))
        else:
            src=work/'dist'/NAME
            if not (src/f'{NAME}.exe').is_file():raise FileNotFoundError('构建没有生成 Windows 程序。')
            for item in src.iterdir():shutil.move(str(item),str(folder/item.name))
        native_files=[p for p in folder.rglob('_license_impl.*') if p.suffix in ('.pyd','.so')]
        if len(native_files)!=1 or any(p.suffix in ('.py','.pyc','.c') for p in folder.rglob('_license_impl.*')):
            raise ValueError('候选包必须且只能包含编译的本产品许可验证模块。')
        if hashlib.sha256(native_files[0].read_bytes()).hexdigest()!=manifest['license_module_sha256']:
            raise ValueError('候选包许可模块与本次编译产物不一致。')
        delivery_resources(folder)
        delivery_manifest(folder,system)
        archive=work/f'exam-room-tool-{system}.zip'
        if MAC:subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(folder),str(archive)],check=True)
        else:shutil.make_archive(str(archive.with_suffix('')),'zip',work,folder.name)
        manifest.update(status='candidate_built',archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        result=publish(folder,archive,args.output.resolve())
        print(result)
        return result
    except Exception as exc:
        manifest.update(status='failed',error_type=type(exc).__name__)
        raise
    finally:
        manifest['ended']=datetime.now().astimezone().isoformat()
        (work/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
