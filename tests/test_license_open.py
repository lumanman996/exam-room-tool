import json
import pytest


def test_source_without_module_is_unrestricted_and_keeps_contact(tmp_path,monkeypatch):
    from exam_room import licensing,paths
    public=tmp_path/'public.json'
    public.write_text(json.dumps({'public_key':'A'*43,'contact':'虚构教务联系人'},ensure_ascii=False),encoding='utf-8')
    monkeypatch.setattr(paths,'PUBLIC',public);monkeypatch.setattr(paths,'FROZEN',False)
    monkeypatch.setattr(licensing,'_impl',None)
    lic=licensing.configured();st=lic.status()
    assert st['state']=='open' and st['canExport'] and st['contact']=='虚构教务联系人'
    lic.require_export()
    assert licensing.License(tmp_path/'lic',None).status()['canExport']


def test_formal_package_without_module_locks_export_only(tmp_path,monkeypatch):
    from exam_room import licensing,paths
    from exam_room.server import App
    monkeypatch.setattr(paths,'FROZEN',True);monkeypatch.setattr(licensing,'_impl',None)
    lic=licensing.configured()
    assert lic.status()['broken'] and not lic.status()['canExport']
    app=App(tmp_path/'app',lic);app.api_new({'name':'虚构未激活考试','grades':['七年级']})
    assert app.store.load(app.plan['id'])
    with pytest.raises(PermissionError):lic.require_export()
