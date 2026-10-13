"""考场编排程序入口。"""
import argparse,sys,webbrowser,time
from . import APP_NAME, VERSION, paths
from .server import start

def main(argv=None):
    ap=argparse.ArgumentParser(description='考场编排')
    ap.add_argument('--browser',action='store_true',help='用浏览器打开')
    ap.add_argument('--selftest',action='store_true',help='本地服务自检')
    a=ap.parse_args(argv);httpd,url,app=start()
    if a.selftest:
        import urllib.request,json
        from . import engine,report,numbering
        from .model import demo_plan
        try:
            from .licensing import module_kind
            if paths.FROZEN:
                if module_kind()!='native' or app.license.status().get('broken'):raise RuntimeError('包内许可验证模块缺失或损坏。')
                app.license.require_export()
            ok=APP_NAME.encode() in urllib.request.urlopen(url).read()
            ok=ok and all(urllib.request.urlopen(url+script).status==200 for script in tuple(x for x in ('numbering.js','rooms.js','controls.js','appearance.js','workspace.js','export.js') if (paths.UI/x).is_file()))
            p=demo_plan()
            for fn in (engine.assign_seats,engine.assign_invigilators):
                result=fn(p)
                if result['status'] not in ('optimal','feasible'):raise RuntimeError(result['message'])
                p=result['plan']
            p=numbering.apply(p,prefix='26',overwrite=True)
            checks=engine.validate(p)
            ok=ok and not checks['errors'] and report.build_excel(p,['students'])[:2]==b'PK'
            print(json.dumps({'ok':ok,'license_module_kind':module_kind(),'license_product':'exam-room-tool','license_public_present':paths.PUBLIC.is_file(),'license_state':app.license.status()['state'],'message':'本机服务、界面、求解器及 Excel 导出自检完成'},ensure_ascii=False),flush=True)
            return 0 if ok else 1
        finally:httpd.shutdown()
    try:
        if not a.browser:
            import webview
            app.window=webview.create_window(APP_NAME,url,width=1320,height=880,min_size=(1050,700));webview.start();httpd.shutdown();return 0
    except Exception: pass
    webbrowser.open(url);app.last_ping=time.monotonic()+20
    try:
        while time.monotonic()-app.last_ping<30: time.sleep(1)
    except KeyboardInterrupt: pass
    httpd.shutdown();return 0

if __name__=='__main__':sys.exit(main())
