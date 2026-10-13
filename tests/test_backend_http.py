"""隔离本机服务验证新的契约；只使用小型虚构方案。"""
import json,time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.request import Request,urlopen
from copy import deepcopy
import pytest
from exam_room.server import App,start
from exam_room.licensing import License
from exam_room import paths
from test_backend_hardening import ready
from pathlib import Path


def test_http_new_interfaces_fixed_revision_snapshot_and_download(tmp_path):
    app=App(tmp_path,License(tmp_path/'license',None));app.commit(ready());httpd,url,_=start(app)
    def call(name,body=None):
        req=Request(url+'api/'+name,data=json.dumps(body or {}).encode(),headers={'X-Token':app.token})
        return json.loads(urlopen(req).read())
    try:
        state=call('state')['data'];rev=state['plan']['revision']
        assert state['capabilities']['async_export'] and state['report_layout_defaults']['seating']['field_order']==[]
        assert 'monitors' not in state['export_stages']['schedule']
        for script in ('appearance.js','workspace.js','export.js'):assert urlopen(url+script).status==200
        layout=state['report_layout_defaults']['room_students'];layout['font_size']=12
        saved=call('report_layout_save',dict(layouts={'room_students':layout},revision=rev));assert saved['ok']
        assert not call('report_layout_save',dict(layouts={'room_students':layout},revision=rev))['ok']
        job=call('export_start',dict(format='preview',sections=['room_students'],revision=app.plan['revision']))['data']
        for _ in range(150):
            status=call('export_status',dict(id=job['id']))['data']
            if status['state']!='running':break
            time.sleep(.02)
        assert status['state']=='done',status
        result=status['result'];blob=urlopen(url+result['url']).read().decode()
        assert blob==result['html'] and result['page_count']==len(result['pages']) and '成绩' not in blob
        assert not call('export_cancel',dict(id='wrong'))['ok']
        assert not call('export_start',dict(format='preview',sections=['room_students'],revision=rev))['ok']
        copy=deepcopy(app.plan);copy['name']='虚构备份前标题';assert call('save',dict(plan=copy,revision=copy['revision']))['ok']
        disk=app.store.path(app.plan['id']);disk.write_text('damaged')
        state=call('state')['data'];assert next(r for r in state['recent'] if r['id']==app.plan['id'])['recoverable']
        preview=call('recovery_preview',dict(id=app.plan['id']))['data'];assert preview['available']
        restored=call('recover',dict(id=app.plan['id'],backup_revision=preview['revision']));assert restored['ok']
        assert app.store.load(app.plan['id'])['name']!=copy['name']
    finally:httpd.shutdown();httpd.server_close()


def test_http_parallel_static_resources_are_complete(tmp_path):
    """浏览器并发加载脚本时服务保持运行，不重试或忽略连接错误。"""
    app=App(tmp_path,License(tmp_path/'license',None))
    httpd,url,_=start(app)
    names=('style.css','appearance.js','controls.js','app.js',
           'numbering.js','rooms.js','workspace.js','export.js')
    expected={name:(paths.UI/name).read_bytes() for name in names}
    failures=[]
    try:
        for run in range(8):
            barrier=Barrier(16)
            def fetch(index):
                name=names[index%len(names)]
                barrier.wait(timeout=10)
                try:
                    with urlopen(url+name,timeout=10) as response:
                        data=response.read()
                        assert response.status==200
                        assert int(response.headers['Content-Length'])==len(expected[name])
                        assert data==expected[name]
                except Exception as exc:
                    return f'round {run} {name}: {exc!r}'
            with ThreadPoolExecutor(max_workers=16) as pool:
                failures.extend(result for result in pool.map(fetch,range(16)) if result)
        assert not failures,'并发静态资源加载失败：'+repr(failures)
    finally:
        httpd.shutdown();httpd.server_close()


def test_http_chinese_page_is_utf8_under_non_utf8_default(tmp_path,monkeypatch):
    original=Path.read_text
    def legacy_read(path,encoding=None,errors=None):
        return original(path,encoding=encoding or 'cp1252',errors=errors)
    monkeypatch.setattr(Path,'read_text',legacy_read)
    app=App(tmp_path,License(tmp_path/'license',None))
    httpd,url,_=start(app)
    try:
        with urlopen(url,timeout=5) as response:html=response.read().decode('utf-8')
        assert '考场编排' in html
    finally:httpd.shutdown();httpd.server_close()


def test_license_contact_is_utf8_under_non_utf8_default(tmp_path,monkeypatch):
    from exam_room import paths,licensing
    public=tmp_path/'public.json'
    public.write_text(json.dumps({'public_key':'A'*43,'contact':'虚构教务联系人'},ensure_ascii=False),encoding='utf-8')
    monkeypatch.setattr(paths,'PUBLIC',public)
    original=Path.read_text
    def legacy_read(path,encoding=None,errors=None):
        return original(path,encoding=encoding or 'cp1252',errors=errors)
    monkeypatch.setattr(Path,'read_text',legacy_read)
    assert licensing.configured().contact=='虚构教务联系人'
