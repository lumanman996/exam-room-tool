"""独立主线程原生宿主；DOM驱动不冒充系统键鼠或文件对话框。"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey,Ed25519PublicKey
from exam_room.licensing import License,b64,unb64,sign_code
from tools.native_acceptance import NativeBlocked,native_exit
from tools.testbench.common import Recorder,assert_plan,assert_excel,assert_pdf_text,dump,service


class NativePage:
    def __init__(self,window):self.window=window

    def js(self,expression):return self.window.evaluate_js(expression)

    def wait(self,expression,timeout=20):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=self.js(expression)
            if value:return value
            time.sleep(.08)
        raise AssertionError('原生页面等待超时：'+expression[:240])

    def click(self,selector):
        self.js('(()=>{const e=document.querySelector('+json.dumps(selector)+');if(!e||e.disabled||!e.getClientRects().length)throw Error("找不到可点击控件");e.focus();e.click();return true})()')

    def fill(self,selector,value):
        self.js('(()=>{const e=document.querySelector('+json.dumps(selector)+');if(!e||e.disabled||!e.getClientRects().length)throw Error("找不到可编辑控件");e.focus();e.value='+json.dumps(value)+';e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));return true})()')

    def navigate(self,name):
        self.click(f'#nav [data-page="{name}"]')
        self.wait('document.querySelector('+json.dumps('#'+name)+').classList.contains("active")')

    def home(self):
        if not self.js('document.querySelector("#home").classList.contains("active")'):
            self.click('#backHome')
        self.wait('document.querySelector("#home").classList.contains("active")')

    def api_click(self,selector,endpoint):
        began=self.js('window.__nativeEvidence.api.length')
        self.click(selector)
        expression='window.__nativeEvidence.api.slice('+str(began)+').find(x=>x.endpoint==='+json.dumps('/api/'+endpoint)+')'
        entry=self.wait(expression,30)
        assert entry['result'].get('ok'),entry['result'].get('error')
        return entry['result'].get('data')

    def export(self,selector):
        began=self.js('window.__nativeEvidence.api.length')
        self.click(selector)
        expression='window.__nativeEvidence.api.slice('+str(began)+').find(x=>x.endpoint==="/api/export_status"&&["done","error","cancelled"].includes(x.result?.data?.state))'
        entry=self.wait(expression,100)
        task=entry['result']['data'];assert task['state']=='done',task
        return task['result']

    def errors(self):return self.js('window.__nativeEvidence.errors')


def install_observer(page):
    page.js('''(()=>{
        window.__nativeEvidence={api:[],errors:[],resources:performance.getEntriesByType('resource').map(x=>new URL(x.name).pathname)};
        addEventListener('error',e=>__nativeEvidence.errors.push(String(e.message||e.target?.src||'资源错误')),{capture:true});
        addEventListener('unhandledrejection',e=>__nativeEvidence.errors.push(String(e.reason)));
        const original=fetch;window.fetch=async(...args)=>{
            try{const response=await original(...args);const path=new URL(args[0],location.href).pathname;
                if(path.startsWith('/api/'))response.clone().json().then(result=>__nativeEvidence.api.push({endpoint:path,status:response.status,result}));
                return response;
            }catch(e){__nativeEvidence.errors.push(String(e));throw e}
        };
        return true;
    })()''')


def assert_native_host(window,page,selected):
    import webview
    renderer=window.gui.renderer
    if selected=='mac':
        from webview.platforms.cocoa import BrowserView
        import WebKit
        wk=BrowserView.instances[window.uid].webview
        assert renderer=='wkwebview' and wk.isKindOfClass_(WebKit.WKWebView),'没有真实WKWebView实例'
        native_class=str(wk.__class__.__name__)
        visible=bool(window.native.isVisible());key_window=bool(window.native.isKeyWindow())
        assert not visible and not key_window,'隐藏验收不应占用前台窗口'
    else:
        assert renderer=='edgechromium','Windows必须使用实际WebView2，不能MSHTML替代'
        native_class=str(type(window.native))
        visible=bool(window.native.Visible)
        assert not visible,'隐藏验收不应显示Windows窗口'
        key_window=None  # 未读取系统前台窗口，不能把False写成实际观测。
    assert page.js('typeof Workspace==="object"&&typeof ExportUI==="object"'), '关键页面脚本未加载'
    return dict(renderer=renderer,native_class=native_class,window_visible=visible,key_window=key_window,
        user_agent=page.js('navigator.userAgent'),dom_triggered=True,os_mouse_keyboard=False)


def open_saved(page,client,ident):
    page.wait('document.querySelector('+json.dumps(f'[data-open="{ident}"]')+')')
    page.api_click(f'[data-open="{ident}"]','open')
    page.wait('document.querySelector("#planName").value.length>0')
    assert client.call('state')['plan']['id']==ident


def save_name(page,client,name):
    page.navigate('overview')
    page.js('(()=>{const e=document.querySelector("#planMenu");if(e)e.open=true;return true})()')
    before=client.call('state')['plan']
    page.fill('#planName',name);page.api_click('#planInfoSave','save')
    page.wait('!document.querySelector("#planMenu").classList.contains("dirty")&&document.querySelector("#saveStatus").textContent.startsWith("已保存")')
    after=client.call('state')['plan']
    assert after['name']==name and after['seats']==before['seats'] and after['invigilation']==before['invigilation']
    assert_plan(after)
    assert client.app.store.load(after['id'])==after
    return dict(name=name,students=len(after['students']),revision=after['revision'],disk_matches=True,arrangements_preserved=True)


def materials(page,client,root):
    from pypdf import PdfReader
    from exam_room.pdf import find_browser
    import io
    page.navigate('export')
    page.click('#exportSelectAll')
    before=client.call('state')['plan']
    page.fill('#printSection','room_students');page.fill('#printPaper','A3');page.fill('#printFont','14')
    page.api_click('#printSave','report_layout_save')
    p=client.call('state')['plan'];assert p['seats']==before['seats'] and p['stale']==before['stale']
    preview=page.export('#previewBtn')
    page.wait('document.querySelector("#exportStatus").textContent.includes("预览已更新")')
    assert preview['page_count']>0 and preview['pages']
    xlsx=page.export('#exportXlsx');assert xlsx['name'].endswith('.xlsx'),xlsx
    blob=client.download(xlsx);layouts=p['report_layouts'];sections=list(client.call('state')['sections'])
    assert len(sections)==16,sections
    assert_excel(blob,p,sections,layouts=layouts)
    (root/'全部材料.xlsx').write_bytes(blob)
    pdf=page.export('#exportPdf');assert pdf['name'].endswith('.pdf'),pdf
    blob=client.download(pdf);reader=PdfReader(io.BytesIO(blob));count=len(reader.pages)
    assert count==preview['page_count'],(count,preview['page_count'])
    assert_pdf_text('\n'.join(item.extract_text() or '' for item in reader.pages),p)
    (root/'全部材料.pdf').write_bytes(blob)
    page.wait('document.querySelector("#exportStatus").textContent.includes("已生成")')
    dump(root/'导出终态.json',dict(preview_pages=preview['page_count'],xlsx=xlsx,pdf=pdf))
    return dict(excel_sections=len(sections),pdf_pages=count,preview_pages=preview['page_count'],pdf_browser=find_browser(),
        all_students_verified=True,native_printing=False,system_file_dialog=False,layout_persisted=True)


def licensing(page,client,clock,key):
    assert client.app.license.status()['state']=='trial'
    clock['now']+=timedelta(days=4)
    ident=client.call('state')['plan']['id'];page.home()
    page.api_click('#refreshBtn','state')
    open_saved(page,client,ident)
    page.wait('document.querySelector("#licence").textContent.includes("试用结束")')
    page.navigate('export')
    page.wait('document.querySelector("#exportXlsx").disabled')
    assert '到期' in page.js('document.querySelector("#exportGate").textContent')
    result=client.raw('export_start',{'format':'xlsx','sections':['students']})
    assert not result['ok'] and result['license'],result
    before=client.call('state')['plan']
    save_name(page,client,before['name']+'·到期仍可保存')
    code=sign_code(key,client.app.license.machine,'2026-12-31')
    page.click('#licenceBtn');page.wait('document.querySelector("#activationCode")')
    page.fill('#activationCode',code);page.api_click('#formSave','activate')
    page.wait('!document.querySelector("#formDialog").open')
    assert client.app.license.status()['state']=='active'
    page.navigate('export');page.wait('!document.querySelector("#exportXlsx").disabled')
    return dict(trial=True,expired_blocks_export=True,expired_still_saves=True,activation_restores=True,temporary_test_key_in_memory=True)


def recover(page,client):
    expected=client.call('state')['plan'];ident=expected['id']
    # 先保留包含当前完整内容的备份，只损坏隔离的虚构文件。
    client.call('save',{'plan':expected,'revision':expected['revision']})
    client.app.store.path(ident).write_text('{虚构损坏文件',encoding='utf-8')
    page.home();page.api_click('#refreshBtn','state')
    info=page.api_click(f'[data-recover="{ident}"]','recovery_preview')
    page.wait('document.querySelector("#formDialog").open')
    page.api_click('#formSave','recover');page.wait('!document.querySelector("#formDialog").open')
    restored=client.call('state')['plan'];assert restored['revision']>expected['revision']
    assert restored['students']==expected['students'] and restored['seats']==expected['seats']
    assert restored['report_layouts']==expected['report_layouts'] and restored['invigilation']==expected['invigilation']
    assert client.app.store.load(ident)==restored;assert_plan(restored)
    assert client.app.store.recovery(ident)['available']
    return dict(backup_revision=info['revision'],restored_revision=restored['revision'],disk_matches=True,arrangements_preserved=True)


def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--step',choices=['first','reopen'],required=True)
    ap.add_argument('--workspace',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--platform',choices=['mac','windows'],required=True);args=ap.parse_args(argv)
    root=args.workspace.resolve();recorder=Recorder(args.output);os.environ['EXAM_ROOM_HOME']=str(root/'config')
    checkpoint=root/'checkpoint.json'
    if args.step=='first':
        key=Ed25519PrivateKey.generate();public=key.public_key();clock={'now':datetime(2026,10,7,tzinfo=timezone.utc)}
    else:
        saved=json.loads(checkpoint.read_text(encoding='utf-8'));key=None
        public=Ed25519PublicKey.from_public_bytes(unb64(saved['public_key']));clock={'now':datetime.fromisoformat(saved['clock'])}
    license=License(root/'测试许可',public,machine='FICTIONAL-NATIVE-'+args.platform,clock=lambda:clock['now'])
    state={'step':args.step,'window_closed':False,'platform':args.platform,'fictional':True}
    with service(root/'本机 数据',license=license) as client:
        state['url']=client.url
        if args.step=='first':
            p=json.loads((root/'虚构标准方案.json').read_text(encoding='utf-8'));p=client.import_plan(p)['plan'];ident=p['id']
        else:ident=saved['plan']['id']
        import webview
        if args.platform=='mac':
            # pywebview首次启动会激活NSApplication。隐藏测试进程禁止激活，避免抢前端CUA焦点。
            from webview.platforms.cocoa import BrowserView
            BrowserView.app.setActivationPolicy_(2)
        window=webview.create_window('虚构原生验收·考场编排',client.url,width=1320,height=880,min_size=(1050,700),hidden=True,focus=False)
        client.app.window=window
        def closed():state['window_closed']=True
        window.events.closed+=closed
        def driver():
            page=NativePage(window)
            def record(ident,name,fn):
                result=recorder.run(ident,name,fn)
                if result['status']!='通过':
                    html=page.js('document.documentElement.outerHTML')
                    html=html.replace(client.app.token,'FICTIONAL-TOKEN-REDACTED')
                    (recorder.root/ident/'失败页面.html').write_text(html,encoding='utf-8')
                    dump(recorder.root/ident/'页面状态.json',page.js('({pages:[...document.querySelectorAll("main>.active")].map(x=>x.id),dialogs:[...document.querySelectorAll("dialog[open]")].map(x=>x.id),license:document.querySelector("#licence").textContent,dirty:[...document.querySelectorAll(".dirty")].map(x=>x.id)})'))
                return result
            try:
                if not window.events.loaded.wait(25):raise AssertionError('原生宿主页面未加载')
                install_observer(page)
                record('NATIVE-host-'+args.step,'真实原生宿主与脚本加载',lambda:assert_native_host(window,page,args.platform))
                open_saved(page,client,ident)
                if args.step=='first':
                    record('NATIVE-edit','原生页面中文信息保存',lambda:save_name(page,client,'虚构·原生验收考试'))
                    record('NATIVE-materials','原生页面16类Excel/实际PDF与版式预览',lambda:materials(page,client,recorder.root))
                    record('NATIVE-license','原生页面测试许可到期与激活',lambda:licensing(page,client,clock,key))
                    record('NATIVE-restore','虚构文件损坏、真实页面恢复及版本',lambda:recover(page,client))
                    p=client.call('state')['plan'];assert_plan(p)
                    dump(checkpoint,dict(plan=p,public_key=b64(public.public_bytes_raw()),clock=clock['now'].isoformat(),first_url=client.url))
                else:
                    def reopened():
                        p=client.call('state')['plan'];assert p==saved['plan'];assert client.url!=saved['first_url']
                        assert page.js('document.querySelector("#planName").value')==p['name'];assert_plan(p)
                        return dict(new_process=True,new_port=True,disk_and_page_match=True,report_layouts_preserved=True)
                    record('NATIVE-reopen','新进程、新服务端口重开完整方案',reopened)
                    def licensed():
                        assert client.app.license.status()['state']=='active'
                        page.navigate('export');page.wait('!document.querySelector("#exportXlsx").disabled')
                        return dict(test_activation_retained=True)
                    record('NATIVE-license-reopen','测试许可重启保留',licensed)
                errors=page.errors();dump(recorder.root/'页面错误.json',errors)
                dump(recorder.root/'原生页面请求.json',page.js('window.__nativeEvidence.api'))
                def error_free():assert not errors,errors
                recorder.run('NATIVE-page-errors','原生页面没有脚本或请求异常',error_free)
            except Exception as exc:
                def failure():raise exc
                recorder.run('NATIVE-driver','原生驱动完成实际操作',failure)
            finally:window.destroy()
        webview.start(driver,gui='edgechromium' if args.platform=='windows' else None,private_mode=True,storage_path=str(root/('原生profile-'+args.step)))
        state['renderer']=window.gui.renderer
    def closed_service():
        assert state['window_closed'],'原生窗口未正常关闭'
        url=urlparse(state['url'])
        try:
            connection=socket.create_connection((url.hostname,url.port),timeout=.5);connection.close()
        except OSError:return dict(window_closed=True,service_socket_closed=True)
        raise AssertionError('窗口退出后本次服务仍在监听')
    if args.step=='first':recorder.run('NATIVE-close','隐藏原生窗口关闭及服务释放',closed_service)
    else:recorder.run('NATIVE-close-reopen','重开窗口关闭及服务释放',closed_service)
    dump(recorder.root/'worker-state.json',state)
    return native_exit(recorder.cases)


if __name__=='__main__':raise SystemExit(main())
