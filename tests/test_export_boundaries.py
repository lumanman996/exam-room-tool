from datetime import datetime,timedelta,timezone
import io,json,zipfile
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exam_room.licensing import License,sign_code,b64
from exam_room.server import App
from exam_room import updater,pdf,engine
from test_backend_hardening import ready


def test_exact_three_day_boundary_blocks_print_but_not_edit_and_save(tmp_path):
    key=Ed25519PrivateKey.generate();now=datetime(2026,10,7,tzinfo=timezone.utc)
    lic=License(tmp_path/'lic',key.public_key(),machine='SYNTHETIC',clock=lambda:now)
    app=App(tmp_path/'app',lic);app.commit(ready());assert lic.status()['canExport']
    now+=timedelta(days=3)-timedelta(seconds=1);assert lic.status()['canExport']
    now+=timedelta(seconds=1);assert not lic.status()['canExport']
    with pytest.raises(PermissionError):app.api_export({'sections':['schedule'],'format':'preview'})
    with pytest.raises(PermissionError):app.api_export_start({'sections':['schedule'],'format':'pdf'})
    app.api_new({'name':'到期仍可保存虚构考试'});assert app.store.load(app.plan['id'])['name']==app.plan['name']
    app.api_demo({});assert engine.assign_seats(app.plan)['status'] in ('optimal','feasible')


@pytest.mark.parametrize('contents',['[]','[1]','"wrong"','null','1','{"first":"wrong"}'])
def test_corrupt_license_never_restarts_free_trial(tmp_path,contents):
    key=Ed25519PrivateKey.generate();tmp_path.mkdir(exist_ok=True);(tmp_path/'license.json').write_text(contents)
    lic=License(tmp_path,key.public_key(),machine='TEST')
    assert not lic.status()['canExport']
    assert not lic.status()['canExport']


def test_wrong_product_and_expiry_and_upgraded_license_persists(tmp_path):
    key=Ed25519PrivateKey.generate();now=datetime(2026,10,7,tzinfo=timezone.utc);clock=lambda:now
    lic=License(tmp_path,key.public_key(),machine='TEST',clock=clock)
    payload=json.dumps(dict(product='chengji-tool',machine='TEST',expiry=None)).encode();code=b64(payload)+'.'+b64(key.sign(payload))
    with pytest.raises(ValueError):lic.activate(code)
    code=sign_code(key,'TEST','2026-10-07');assert lic.activate(code)['state']=='active'
    assert License(tmp_path,key.public_key(),machine='TEST',clock=clock).status()['state']=='active'
    now+=timedelta(days=4);assert not lic.status()['canExport']
    assert lic.activate(sign_code(key,'TEST',None))['canExport']


@pytest.mark.parametrize('name',['../escape','/absolute','C:/escape','folder/../../escape','folder\\..\\escape'])
def test_update_rejects_unsafe_archive_before_extracting(tmp_path,monkeypatch,name):
    monkeypatch.setattr(updater.sys,'platform','win32');monkeypatch.setattr(updater,'LOG',tmp_path/'update.log')
    zpath=tmp_path/'update.zip'
    with zipfile.ZipFile(zpath,'w') as z:z.writestr(name,b'wrong')
    with pytest.raises(ValueError,match='安装包'):updater.Updater().prepare(zpath,tmp_path/'stage')
    assert not (tmp_path/'escape').exists()


def test_update_hash_failure_and_keep_user_data(tmp_path,monkeypatch):
    monkeypatch.setattr(updater,'LOG',tmp_path/'update.log')
    class Response(io.BytesIO):pass
    monkeypatch.setattr(updater,'_open',lambda *args:Response(b'not zip'))
    up=updater.Updater();up._download({'browser_download_url':updater.DOWNLOAD_PREFIX+'v2/file.zip','digest':'sha256:'+'0'*64,'size':7})
    assert up.status()['phase']=='error' and '校验' in up.status()['error']
    target=tmp_path/'old';new=tmp_path/'new'
    for root in (target,new):
        for folder in ('data','output','config'):(root/folder).mkdir(parents=True)
        (root/'config'/'license.json').write_text('old' if root==target else 'new')
    (target/'data'/'exam.json').write_text('虚构保留');(new/'config'/'added.json').write_text('added')
    up.new_root=new;up._keep_user_files(target)
    assert (target/'data'/'exam.json').read_text()=='虚构保留'
    assert (target/'config'/'license.json').read_text()=='old'
    assert not (new/'config'/'license.json').exists() and (new/'config'/'added.json').exists()


def test_pdf_failure_and_cancellation_remove_incomplete_output(tmp_path,monkeypatch):
    from threading import Event
    out=tmp_path/'invalid.pdf';out.write_bytes(b'%PDF- incomplete')
    assert not pdf.complete(out)
    monkeypatch.setattr(pdf,'find_browser',lambda:None)
    assert not pdf.html_to_pdf('<p>虚构</p>',out)
    cancel=Event();cancel.set();monkeypatch.setattr(pdf,'find_browser',lambda:'dummy')
    assert not pdf.html_to_pdf('<p>虚构</p>',out,cancel=cancel)
