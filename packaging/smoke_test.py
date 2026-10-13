"""隔离执行源码或冻结程序自检，保存真实退出、回执及失败诊断。"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


def _text(value):
    return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else value or ''


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen',action='store_true')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args(argv)
    cmd=[sys.executable,'-m','exam_room','--selftest']
    if args.frozen:
        exe=(ROOT/'dist'/'考场编排-Mac'/'考场编排.app'/'Contents'/'MacOS'/'考场编排') if sys.platform=='darwin' else ROOT/'dist'/'考场编排-Windows'/'考场编排.exe'
        if not exe.is_file():raise SystemExit('找不到候选包里的程序，请先构建。')
        cmd=[str(exe),'--selftest']
    run_id=uuid4().hex
    record=dict(started=datetime.now().astimezone().isoformat(),frozen=args.frozen,command=cmd,
                platform=platform.platform(),arch=platform.machine(),isolated=True,native_window_tested=False,
                run_id=run_id,ok=False,exit_code=None,stdout='',stderr='',diagnostics={})
    try:
        with tempfile.TemporaryDirectory(prefix='exam-room-smoke-') as folder:
            env={**os.environ,'EXAM_ROOM_HOME':folder,'EXAM_ROOM_SELFTEST_RUN_ID':run_id,
                 'EXAM_ROOM_NO_UPDATE_CHECK':'1','PYTHONIOENCODING':'utf-8'}
            try:
                result=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
                record.update(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr,ok=result.returncode==0)
            except subprocess.TimeoutExpired as exc:
                record.update(timeout=True,stdout=_text(exc.stdout),stderr=_text(exc.stderr))
            finally:
                base=args.report.parent if args.report else ROOT/'output/smoke-diagnostics'
                base.mkdir(parents=True,exist_ok=True)
                dest=Path(tempfile.mkdtemp(prefix=(args.report.stem if args.report else 'smoke')+'-evidence-',dir=base))
                for name in ('startup.log','selftest-result.json'):
                    source=Path(folder)/name
                    if source.is_file():
                        shutil.copyfile(source,dest/name);record['diagnostics'][name]=str((dest/name).resolve())
                receipt=Path(folder)/'selftest-result.json'
                if receipt.is_file():
                    try:record['receipt']=json.loads(receipt.read_text(encoding='utf-8'))
                    except (OSError,ValueError):record['receipt_error']='自检回执无法读取。'
            parsed=[]
            for line in record['stdout'].splitlines():
                try:value=json.loads(line)
                except ValueError:continue
                if isinstance(value,dict) and 'ok' in value:parsed.append(value)
            if parsed:
                record['selftest_result']=parsed[-1];record['ok']=record['ok'] and parsed[-1]['ok'] is True
            record['json_observed']=bool(parsed)
            if args.frozen:
                receipt=record.get('receipt',{})
                valid=(isinstance(receipt,dict) and receipt.get('run_id')==run_id and receipt.get('exit_code')==0
                       and receipt.get('ok') is True and isinstance(receipt.get('selftest_result'),dict)
                       and receipt['selftest_result'].get('ok') is True
                       and receipt['selftest_result'].get('license_module_kind')=='native'
                       and receipt['selftest_result'].get('license_product')=='exam-room-tool')
                record['receipt_verified']=valid;record['ok']=record['ok'] and valid
            if not record['ok']:
                record['diagnosis']=('entry_not_observed' if 'startup.log' not in record['diagnostics'] else
                    'timeout_after_entry' if record.get('timeout') else 'selftest_failed_after_entry')
    except Exception as exc:
        record.update(ok=False,error_type=type(exc).__name__,error=str(exc))
    finally:
        record['ended']=datetime.now().astimezone().isoformat()
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    if not record.get('ok'):raise SystemExit(record.get('stdout','')+record.get('stderr','') or '候选程序自检失败或超时，请查看启动诊断。')
    print(json.dumps({'ok':True,'frozen':args.frozen,'json_observed':record['json_observed'],
                     'receipt_verified':record.get('receipt_verified',False),
                     'message':'本机服务、界面资源、求解器和 Excel 自检通过；未验证原生窗口。'},ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
