"""自动验测入口；所有用户操作在虚构方案及隔离目录内完成。"""
import argparse
from datetime import datetime
from html import escape
import json
import hashlib
from importlib.metadata import version, PackageNotFoundError
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def command_result(command, directory, ident, timeout):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    log=directory/(ident+'.log'); started=time.perf_counter()
    env={**os.environ,'EXAM_ROOM_HOME':str(directory/'workspace'),'PYTHONUNBUFFERED':'1'}
    timeout_hit=False
    with log.open('w',encoding='utf-8') as f:
        try:
            process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,
                                     start_new_session=os.name!='nt')
        except OSError as exc:
            f.write(str(exc))
            return dict(id=ident,name=ident,status='环境阻塞',seconds=round(time.perf_counter()-started,3),
                        details=dict(error=str(exc),exit_code=None,timeout=False,log=str(log),command=command))
        try: code=process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timeout_hit=True
            if os.name=='nt': subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
            else:
                import signal
                os.killpg(process.pid,signal.SIGTERM)
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name=='nt': process.kill()
                else: os.killpg(process.pid,signal.SIGKILL)
                process.wait()
            code=-1
    return dict(id=ident,name=ident,status='通过' if code==0 else '失败',
        seconds=round(time.perf_counter()-started,3),details=dict(exit_code=code,timeout=timeout_hit,log=str(log),command=command))


def exit_status(cases):
    return 1 if not cases or any(c['status']!='通过' for c in cases) else 0


def source_fingerprint():
    files={p for folder in ('exam_room','tools','tests') for p in (ROOT/folder).rglob('*')
           if p.suffix in ('.py','.js','.html','.css')}
    files.update(p for p in (ROOT/'testkit').rglob('*') if p.suffix in ('.json','.xlsx','.csv'))
    files.update(ROOT.glob('requirements*.txt'))
    files.update(p for p in (ROOT/'pytest.ini',ROOT/'conftest.py',ROOT/'.gitattributes') if p.is_file())
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def source_stability(before,after):
    changed=sorted(p for p in before.keys()|after.keys() if before.get(p)!=after.get(p))
    return dict(id='RUN-source-stability',name='运行期间源码、测试及样本保持一致',
                status='失败' if changed else '通过',seconds=0,
                details=dict(changed_files=changed,note='源码发生变化时需稳定后重新运行；阶段证据不作为最终验收。'))


def write_report(directory,data):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    data['summary']={s:sum(c['status']==s for c in data['cases']) for s in ('通过','失败','环境阻塞','未运行')}
    (directory/'report.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    rows=''.join('<tr><td>'+escape(c['id'])+'</td><td>'+escape(c['name'])+'</td><td>'+escape(c['status'])+
        '</td><td>'+str(c['seconds'])+'</td><td><pre>'+escape(json.dumps(c['details'],ensure_ascii=False,indent=2))+
        '</pre></td></tr>' for c in data['cases'])
    limitations=''.join('<li>'+escape(x)+'</li>' for x in data.get('limitations',[]))
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>考场编排·验测台报告</title>
<style>body{background:#faf7ef;color:#242936;font:16px system-ui;margin:40px}h1{color:#334c83}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;border:1px solid #d8dce5;text-align:left;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}small{color:#616b80}</style>
<h1>考场编排·验测台</h1><p>虚构资料 · 本机隔离运行 · '''+escape(data['mode'])+'''</p><p>'''+escape(json.dumps(data['summary'],ensure_ascii=False))+'''</p>
<details><summary>本次环境</summary><pre>'''+escape(json.dumps(data['environment'],ensure_ascii=False,indent=2))+'''</pre></details>
<p>未运行的交付检查：不是已通过项目。</p><ul>'''+limitations+'''</ul><table><thead><tr><th>编号</th><th>检查</th><th>结果</th><th>秒</th><th>实际结果与证据</th></tr></thead><tbody>'''+rows+'</tbody></table></html>'
    (directory/'report.html').write_text(html,encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['quick','full'],default='full')
    parser.add_argument('--phase',choices=['scenarios','browser','scale','property'],help=argparse.SUPPRESS)
    parser.add_argument('--seeds',type=int,default=8,help=argparse.SUPPRESS)
    parser.add_argument('--output',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--case',action='append',help='只运行指定自动场景，可重复指定；不代表完整验收')
    args=parser.parse_args()
    if args.phase:
        from tools.testbench.common import Recorder
        recorder=Recorder(args.output)
        phase_before=source_fingerprint()
        if args.phase=='browser':
            from tools.testbench.browser import run
            run(recorder,only=args.case)
        elif args.phase=='property':
            from tools.testbench.randomized import run
            run(recorder,seeds=args.seeds,only=args.case)
        else:
            from tools.testbench.scenarios import run
            run(recorder,scale=args.phase=='scale',only=args.case)
        if not recorder.cases:
            def missing_case():raise ValueError('没有匹配的测试场景，请核对case编号；没有实际执行不能通过。')
            recorder.run('RUN-no-cases','所选测试场景实际存在',missing_case)
        phase_after=source_fingerprint()
        (recorder.root/'source-evidence.json').write_text(json.dumps(dict(before=phase_before,after=phase_after,
            stability=source_stability(phase_before,phase_after)),ensure_ascii=False,indent=2),encoding='utf-8')
        scoped_cases=recorder.cases+[source_stability(phase_before,phase_after)]
        write_report(recorder.root,dict(mode='针对性阶段：'+args.phase,environment=dict(python=sys.version,
            system=platform.platform(),source_sha256_before=phase_before,source_sha256_after=phase_after),
            cases=scoped_cases,limitations=[
                '仅本阶段实际结果，不代表完整源码、其他阶段或Windows/Mac原生程序包已通过。']))
        return exit_status(scoped_cases)
    stamp=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')
    directory=ROOT/'output'/'testbench'/(stamp+'-'+uuid4().hex[:6]); directory.mkdir(parents=True)
    def git(*args): return subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    before=source_fingerprint()
    packages={}
    for name in ('ortools','playwright','openpyxl','pypdf','pytest'):
        try: packages[name]=version(name)
        except PackageNotFoundError: packages[name]='未安装'
    data=dict(mode=args.mode,started_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),environment=dict(python=sys.version,system=platform.platform(),packages=packages,
        git_commit=git('rev-parse','HEAD'),working_changes=git('status','--short'),fictional=True),cases=[],phase_runs=[],limitations=[
        'Mac与Windows最终程序包的原生窗口、系统文件对话框、实际打印、签名与升级安装：本轮不打包，未运行。',
        '浏览器自动化验证实际HTML前端与本机后端，不代表各系统pywebview原生宿主已通过。'])
    data['environment']['source_sha256_before']=before
    data['environment']['fixture_inventory_sha256']=hashlib.sha256((ROOT/'testkit/inventory.json').read_bytes()).hexdigest()
    phases=[('资料准备',[sys.executable,'tools/prepare_testkit.py','--verify-only'],90),
            ('源码回归',[sys.executable,'-m','pytest','-q','--junitxml='+str(directory/'pytest.xml')],240),
            ('scenarios',None,300),
            ('随机对抗',[sys.executable,'tools/run_testbench.py','--phase','property','--output',str(directory/'随机对抗'),
                     '--seeds',str(40 if args.mode=='full' else 8),*[x for case in args.case or [] for x in ('--case',case)]],
             600 if args.mode=='full' else 180)]
    frontend_tests=sorted((ROOT/'tests/frontend').glob('*.test.js'))
    if frontend_tests: phases.insert(2,('前端单元',[__import__('shutil').which('node') or 'node','--test',*map(str,frontend_tests)],90))
    if args.mode=='full': phases += [('browser',None,360),('scale',None,260)]
    else: data['limitations'].append('quick模式未运行完整浏览器和1,500人求解；需full复测。')
    if args.case: data['limitations'].append('仅指定case运行；未选场景均未运行，不能作为完整验收。')
    for ident,command,timeout in phases:
        print('开始 '+ident,flush=True)
        phase_root=directory/ident
        if command is None:
            command=[sys.executable,'tools/run_testbench.py','--phase',ident,'--output',str(phase_root)]
            for case in args.case or []: command.extend(['--case',case])
        result=command_result(command,phase_root,ident,timeout)
        data['phase_runs'].append(result)
        if (phase_root/'results.json').exists():
            sub=json.loads((phase_root/'results.json').read_text(encoding='utf-8'))
            data['cases']+=sub
            if result['status']!='通过' and all(c['status']=='通过' for c in sub): data['cases'].append(result)
        else: data['cases'].append(result)
        print(f"{ident}：{result['status']} ({result['seconds']}秒)，日志 {result['details']['log']}",flush=True)
        write_report(directory,data)
    after=source_fingerprint(); data['environment']['source_sha256_after']=after
    data['finished_at']=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    data['cases'].append(source_stability(before,after)); write_report(directory,data)
    (ROOT/'output'/'testbench'/'latest.txt').write_text(str(directory),encoding='utf-8')
    print('报告：'+str(directory/'report.html'),flush=True)
    print(json.dumps(data['summary'],ensure_ascii=False),flush=True)
    return exit_status(data['cases'])


if __name__=='__main__': raise SystemExit(main())
