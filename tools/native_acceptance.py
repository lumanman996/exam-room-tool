#!/usr/bin/env python3
"""原生宿主独立验收。prepare不执行宿主，run只放行本机已执行的自动范围。"""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime
from importlib import util
from importlib.metadata import version,PackageNotFoundError
import json
import os
from pathlib import Path
import platform
import shutil
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.run_testbench import command_result,source_fingerprint,source_stability,write_report
from tools.testbench.common import dump


class NativeBlocked(RuntimeError):pass


def resolve_platform(requested,host):
    actual={'darwin':'mac','win32':'windows'}.get(host)
    if not actual:raise NativeBlocked('当前系统没有本入口支持的原生宿主。')
    if requested!='auto' and requested!=actual:
        raise NativeBlocked(f'请求 {"Windows" if requested=="windows" else "Mac"} 原生验收，但当前系统是 {actual}。')
    return actual


def check_runtime(selected,available,interactive):
    names=['webview']+(['AppKit','WebKit','objc'] if selected=='mac' else ['clr'])
    missing=[name for name in names if not available(name)]
    if missing:raise NativeBlocked('缺少原生依赖：'+', '.join(missing))
    if not interactive:raise NativeBlocked('当前没有交互桌面会话，原生宿主未运行；不能用CI构建或浏览器代替。')


def interactive_desktop():
    if sys.platform!='win32':return True
    from ctypes import wintypes
    class USEROBJECTFLAGS(ctypes.Structure):
        _fields_=[('inherit',wintypes.BOOL),('reserved',wintypes.BOOL),('flags',wintypes.DWORD)]
    user32=ctypes.WinDLL('user32',use_last_error=True)
    user32.GetProcessWindowStation.restype=wintypes.HANDLE
    station=user32.GetProcessWindowStation()
    flags=USEROBJECTFLAGS();needed=wintypes.DWORD()
    user32.GetUserObjectInformationW.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    ok=user32.GetUserObjectInformationW(station,1,ctypes.byref(flags),ctypes.sizeof(flags),ctypes.byref(needed))
    return bool(ok and flags.flags&1)


def baseline_changes(reference,current):
    # 新报告统一POSIX分隔符；旧Windows报告仍可能含反斜杠。
    reference={k.replace('\\','/'):v for k,v in reference.items()}
    current={k.replace('\\','/'):v for k,v in current.items()}
    names={k for k in reference.keys()|current.keys() if k.startswith('exam_room/')}
    return sorted(k for k in names if reference.get(k)!=current.get(k))


def validate_reference(data):
    phases=data.get('phase_runs',[]);env=data.get('environment',{})
    required={'资料准备','源码回归','前端单元','scenarios','随机对抗','browser','scale'}
    valid=(data.get('mode')=='full' and bool(data.get('finished_at')) and bool(data.get('cases'))
        and all(x.get('status')=='通过' for x in data.get('cases',[]))
        and required=={x.get('id') for x in phases}
        and all(x.get('details',{}).get('exit_code')==0 for x in phases)
        and bool(env.get('source_sha256_after'))
        and env.get('source_sha256_before')==env.get('source_sha256_after'))
    if not valid:raise NativeBlocked('需要本次已结束且实际通过的完整full报告，prepare/quick/中间快照不能作为原生基线。')
    return env['source_sha256_after']


def native_exit(cases):
    if not cases or any(x['status']=='失败' for x in cases):return 1
    if any(x['status']=='环境阻塞' for x in cases):return 2
    return 0 if all(x['status']=='通过' for x in cases) else 1


def checklist(selected):
    entries=[('host','真实原生宿主及全部静态脚本'),('edit','中文虚构信息保存与检查'),
        ('restore','实际文件损坏恢复及版本保护'),('export','全部Excel与实际PDF独立核对'),
        ('license','试用、到期、测试激活及重启保留'),('restart','关闭服务与新进程新端口重开'),
        ('file-dialog','系统文件选择及另存对话框'),('input','真实键鼠与中文输入法'),
        ('print-physical','系统打印及纸面材料'),('package','最终包内启动、完整流程与自检'),
        ('upgrade','真实升级与失败回滚')]
    return [dict(id=f'{p}-{key}',platform=p,name=name,status='未运行',
        automation='隐藏宿主程序触发DOM/真实HTTP' if key in ('host','edit','restore','export','license','restart') else '原生桌面或交付环境另验')
        for p in ('mac','windows') for key,name in entries]


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode',choices=['prepare','run'],default='prepare')
    ap.add_argument('--platform',choices=['auto','mac','windows'],default='auto')
    ap.add_argument('--output',type=Path)
    ap.add_argument('--baseline',type=Path,help='本次完成且通过的full report.json；CI必须传该平台实际生成的路径')
    args=ap.parse_args(argv)
    stamp=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')
    directory=(args.output or ROOT/'output/native-acceptance'/(stamp+'-'+uuid4().hex[:6])).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    # 中文及空格路径，明确不用真实资料。
    workspace=directory/'虚构 原生验收资料';workspace.mkdir(exist_ok=True)
    plan=json.loads((ROOT/'testkit/fixtures/C01_tiny_completed/方案.json').read_text(encoding='utf-8'))
    plan['grades']=['七年级','八年级','九年级']
    dump(workspace/'虚构标准方案.json',plan)
    before=source_fingerprint();cases=[];phase_runs=[];selected=None
    environment={'system':platform.platform(),'python':sys.version,'host':sys.platform,'fictional':True,'window':'hidden, focus=False','source_sha256_before':before}
    for name in ('pywebview','pyobjc-core','pyobjc-framework-WebKit','pythonnet','openpyxl','pypdf'):
        try:environment[name]=version(name)
        except PackageNotFoundError:environment[name]='未安装'
    limitations=['隐藏真实宿主通过不代替可见窗口、真实键鼠/中文输入法、系统文件对话框或实际打印。',
        '其他平台、最终程序包、签名公证及真实升级本次未运行；本入口当前仅运行源码。',
        'PDF由产品实际导出器生成，不能代替WKWebView原生打印或实际纸面打印。',
        '此入口独立创建真实App和pywebview窗口，不代替生产app.main完整启动/退出入口验收。']
    try:
        baseline=args.baseline
        if baseline is None and args.mode=='run':
            pointer=ROOT/'output/testbench/latest.txt'
            if not pointer.is_file():raise NativeBlocked('尚无本平台完整full报告；请先运行full，再传 --baseline 的确切路径。')
            baseline=Path(pointer.read_text(encoding='utf-8').strip())/'report.json'
        if baseline is not None:
            reference=validate_reference(json.loads(baseline.read_text(encoding='utf-8')))
            changed=baseline_changes(reference,before)
            cases.append(dict(id='NATIVE-baseline',name='稳定产品基线',status='失败' if changed else '通过',seconds=0,details={'reference':str(baseline),'changed_product_files':changed}))
            if changed:raise ValueError('产品与已验收基线不同，先交总协调确认版本。')
        else:
            cases.append(dict(id='NATIVE-prepare',name='原生清单与虚构样本准备',status='通过',seconds=0,details={'native_executed':False,'full_reference_verified':False}))
        selected=resolve_platform(args.platform,sys.platform)
        if args.mode=='run':
            check_runtime(selected,lambda name:util.find_spec(name) is not None,interactive_desktop())
            for step in ('first','reopen'):
                phase_dir=directory/step
                command=[sys.executable,'-m','tools.testbench.native_worker','--step',step,'--workspace',str(workspace),'--output',str(phase_dir),'--platform',selected]
                result=command_result(command,phase_dir,'原生-'+step,150)
                phase_runs.append(result)
                result_file=phase_dir/'results.json'
                sub=json.loads(result_file.read_text(encoding='utf-8')) if result_file.exists() else []
                cases+=sub
                if not sub or (result['status']!='通过' and all(x['status']=='通过' for x in sub)):cases.append(result)
                if result['status']!='通过':break
        else:
            limitations.insert(0,'prepare仅准备清单/虚构样本并核对基线，没有运行任何原生宿主。')
    except NativeBlocked as exc:
        cases.append(dict(id='NATIVE-environment',name='原生环境',status='环境阻塞',seconds=0,details={'reason':str(exc),'native_executed':False}))
    except Exception as exc:
        cases.append(dict(id='NATIVE-setup',name='原生验收准备',status='失败',seconds=0,details={'error':str(exc)}))
    after=source_fingerprint();environment['source_sha256_after']=after
    cases.append(source_stability(before,after))
    matrix=checklist(selected)
    if args.mode=='run' and selected:
        mapping={'host':['NATIVE-host-first','NATIVE-host-reopen'],'edit':['NATIVE-edit'],'restore':['NATIVE-restore'],
            'export':['NATIVE-materials'],'license':['NATIVE-license','NATIVE-license-reopen'],
            'restart':['NATIVE-close','NATIVE-reopen','NATIVE-close-reopen']}
        for row in matrix:
            if row['platform']!=selected:continue
            ids=mapping.get(row['id'].removeprefix(selected+'-'),[])
            items=[x for x in cases if x['id'] in ids]
            if ids and len(items)==len(ids):row['status']='通过' if all(x['status']=='通过' for x in items) else '失败'
    dump(directory/'checklist.json',matrix)
    data=dict(mode='原生验收：'+args.mode,environment=environment,cases=cases,phase_runs=phase_runs,limitations=limitations,
        scope='selected host automated checks only',platform=selected,finished_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
    write_report(directory,data)
    code=native_exit(cases)
    dump(directory/'terminal.json',{'exit_code':code,'mode':args.mode,'native_requested':args.mode=='run','selected_platform':selected,'summary':data['summary']})
    print('原生验收报告：'+str(directory/'report.html'),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
