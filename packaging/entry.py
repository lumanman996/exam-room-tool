"""Frozen entry: record startup before importing application/native dependencies."""
import contextlib
from datetime import datetime,timezone
import faulthandler
import json
import os
from pathlib import Path
import sys
import traceback


def _bootstrap():
    selftest='--selftest' in sys.argv[1:]
    home=os.environ.get('EXAM_ROOM_HOME')
    directory=Path(home) if home else Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ExamRoomTool'/'logs'
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'startup.log';stage='entry_started';code=1;error=None
    original=(sys.stdout,sys.stderr);started=datetime.now(timezone.utc).isoformat()
    with path.open('a+',encoding='utf-8',buffering=1) as log:
        offset=log.tell()
        def mark(value):
            nonlocal stage
            stage=value;log.write(datetime.now(timezone.utc).isoformat()+' '+value+'\n');log.flush()
        if sys.stdout is None:sys.stdout=log
        if sys.stderr is None:sys.stderr=log
        was_enabled=faulthandler.is_enabled()
        try:
            mark('entry_started')
            log.write(json.dumps({'pid':os.getpid(),'selftest':selftest,'frozen':bool(getattr(sys,'frozen',False)),
                'python':sys.version,'platform':sys.platform,'bundle':str(getattr(sys,'_MEIPASS',''))},ensure_ascii=False)+'\n')
            if selftest and not home:raise RuntimeError('自检必须指定隔离的 EXAM_ROOM_HOME。')
            faulthandler.enable(file=log)
            if selftest:faulthandler.dump_traceback_later(60,repeat=True,file=log)
            if selftest and sys.platform=='win32':
                import ctypes
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                flags=0x0001|0x0002|0x8000
                previous=kernel.SetErrorMode(flags);kernel.SetErrorMode(previous|flags)
                mark('windows_error_mode_configured')
            import multiprocessing
            multiprocessing.freeze_support()
            mark('importing_application')
            from exam_room.app import main
            mark('running_selftest' if selftest else 'running_application')
            with contextlib.redirect_stdout(log) if selftest else contextlib.nullcontext():
                code=main()
            code=int(code or 0);mark('application_returned')
        except BaseException as exc:
            if isinstance(exc,SystemExit):code=exc.code if isinstance(exc.code,int) else (0 if exc.code is None else 1)
            else:code=1
            error=type(exc).__name__;traceback.print_exc(file=log);log.flush()
            if not selftest:raise
        finally:
            if selftest:faulthandler.cancel_dump_traceback_later()
            faulthandler.disable()
            sys.stdout,sys.stderr=original
            if was_enabled and sys.stderr is not None:faulthandler.enable()
        if selftest:
            log.seek(offset);parsed=[]
            for line in log.read().splitlines():
                try:value=json.loads(line)
                except ValueError:continue
                if isinstance(value,dict) and 'ok' in value:parsed.append(value)
            actual=parsed[-1] if parsed else None
            ok=code==0 and actual is not None and actual.get('ok') is True and error is None
            if code==0 and not ok:code=1
            receipt=dict(ok=ok,exit_code=code,run_id=os.environ.get('EXAM_ROOM_SELFTEST_RUN_ID',''),
                started=started,ended=datetime.now(timezone.utc).isoformat(),last_stage=stage,
                error_type=error,selftest_result=actual,native_window_tested=False)
            (directory/'selftest-result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        mark('entry_finished exit='+str(code))
    return code


def _notify_failure(path):
    message='考场编排启动失败，请联系软件提供者。诊断文件：'+str(path)
    try:
        if sys.platform=='win32':
            import ctypes
            ctypes.WinDLL('user32').MessageBoxW(None,message,'考场编排',0x10)
        elif sys.stderr is not None:sys.stderr.write(message+'\n')
    except Exception:pass


def bootstrap():
    try:return _bootstrap()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code,int) else (0 if exc.code is None else 1)
    except BaseException:
        if '--selftest' not in sys.argv[1:]:
            home=os.environ.get('EXAM_ROOM_HOME')
            directory=Path(home) if home else Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ExamRoomTool'/'logs'
            _notify_failure(directory/'startup.log')
        return 1


if __name__=='__main__':
    raise SystemExit(bootstrap())
