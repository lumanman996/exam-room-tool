"""导出固定快照；生成期间修改方案不会改变正在输出的材料。"""
from copy import deepcopy
from pathlib import Path
import threading
import time
from . import errors,report,printing
from .model import uid


class Cancelled(Exception):pass


def request(plan,body):
    sections=body.get('sections',[])
    if not isinstance(sections,list) or not sections or any(x not in report.SECTIONS for x in sections) or len(set(sections))!=len(sections):raise ValueError('请至少选择一种有效材料，不要重复选择。')
    fmt=body.get('format','xlsx')
    if fmt not in ('xlsx','preview','html','pdf'):raise ValueError('不支持的导出格式。')
    if 'revision' in body and body['revision']!=plan['revision']:raise ValueError('方案已更新，请重新载入后预览或导出。')
    layouts=body.get('layouts',{})
    if not isinstance(layouts,dict) or any(k not in report.SECTIONS for k in layouts):raise ValueError('版式材料名称无效。')
    layouts={k:printing.normalize_layout(v,k) for k,v in layouts.items()}
    scope=printing.scope_options(plan,body.get('scope'))
    report.check_export(plan,bool(body.get('draft')),sections)
    return dict(format=fmt,sections=sections,draft=bool(body.get('draft')),layouts=layouts,scope=scope)


def build(plan,options,output,cancel,progress):
    def checkpoint():
        if cancel.is_set():raise Cancelled('已取消生成，本次文件未发布。')
    checkpoint();progress('正在生成固定版本材料…')
    if options['format']=='xlsx':
        blob=report.build_excel(plan,options['sections'],options['draft'],options['layouts'],options['scope']);checkpoint()
        return dict(name='考务材料.xlsx',blob=blob,kind='xlsx',pages=[],page_count=None)
    doc=printing.document(plan,options['sections'],options['draft'],options['layouts'],options['scope']);checkpoint()
    result=dict(doc,name='打印预览.html' if options['format']=='preview' else '考务材料.html',blob=doc['html'].encode(),kind='html')
    if options['format']=='pdf':
        from .pdf import html_to_pdf,page_count
        progress('正在调用本机浏览器打印 PDF…');out=Path(output)/(uid()+'-考务材料.pdf')
        try:
            if html_to_pdf(doc['html'],out,cancel=cancel):
                checkpoint();actual=page_count(out)
                if actual==doc['page_count']:
                    result.update(name='考务材料.pdf',blob=out.read_bytes(),kind='pdf',pdf_page_count=actual)
                else:result['message']='浏览器的分页与预览不一致，已保留可打印网页，请核对纸张设置后打印。'
            else:result['message']='未能调用本机浏览器完成 PDF，已保留可打印网页，可在浏览器中打开并打印。'
        finally:out.unlink(missing_ok=True)
    checkpoint()
    if options['format']!='preview':result.pop('html',None)
    return result


def start(app,body):
    app.license.require_export();p=deepcopy(app.require());options=request(p,body)
    if app.export_task and app.export_task['state']=='running':raise ValueError('已有材料正在生成，请稍候或取消。')
    ident=uid();cancel=threading.Event();app.export_cancel_event=cancel
    app.export_task=dict(id=ident,state='running',phase='preparing',snapshot_revision=p['revision'],started=time.time(),message='正在准备材料…')
    def progress(message):
        with app.lock:
            if app.export_task and app.export_task['id']==ident:app.export_task.update(message=message,phase='rendering')
    def run():
        try:
            result=build(p,options,app.root/'output',cancel,progress)
            with app.lock:
                if cancel.is_set():raise Cancelled('已取消生成，本次文件未发布。')
                # Recheck at publication too (a long task may cross trial expiry).
                app.license.require_export()
                blob=result.pop('blob');download=app.downloadable(result.pop('name'),blob)
                result.update(download,snapshot_revision=p['revision'],stale=not app.plan or app.plan['id']!=p['id'] or app.plan['revision']!=p['revision'])
                app.export_task.update(state='done',phase='done',result=result,elapsed=round(time.time()-app.export_task['started'],2))
        except Cancelled as e:
            with app.lock:app.export_task.update(state='cancelled',phase='cancelled',message=str(e))
        except Exception as e:
            with app.lock:app.export_task.update(state='error',phase='error',message=errors.user_message(e),error=errors.user_message(e))
    threading.Thread(target=run,daemon=True).start();return deepcopy(app.export_task)
