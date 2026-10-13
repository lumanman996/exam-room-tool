import json
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

# 验证模块不在公开仓库里；没有它时（例如公开源码或 CI 测试阶段）跳过这些测试。
pytest.importorskip('exam_room._license_impl')
from exam_room.licensing import License, sign_code


def test_trial_expiry_machine_and_tamper(tmp_path):
    key=Ed25519PrivateKey.generate(); now=datetime(2026,10,4,tzinfo=timezone.utc)
    lic=License(tmp_path,key.public_key(),machine='TEST',clock=lambda:now)
    assert lic.status()['state']=='trial'
    later=License(tmp_path,key.public_key(),machine='TEST',clock=lambda:now+timedelta(days=4))
    assert not later.status()['canExport']
    code=sign_code(key,'TEST',None)
    assert later.activate(code)['canExport']
    other=License(tmp_path/'other',key.public_key(),machine='OTHER')
    import pytest
    with pytest.raises(ValueError): other.activate(code)
    with pytest.raises(ValueError): lic.activate(code+'x')


def test_clock_rollback_and_open_source(tmp_path):
    key=Ed25519PrivateKey.generate(); now=datetime(2026,10,4,tzinfo=timezone.utc)
    License(tmp_path,key.public_key(),machine='T',clock=lambda:now).status()
    old=License(tmp_path,key.public_key(),machine='T',clock=lambda:now-timedelta(days=1))
    assert not old.status()['canExport']
    assert License(tmp_path/'open',None).status()['state']=='open'


def test_frozen_missing_or_python_module_is_blocked_but_plan_save_works(tmp_path,monkeypatch):
    import exam_room.licensing as licensing
    from exam_room.server import App
    import pytest
    monkeypatch.setattr(licensing.paths,'FROZEN',True)
    for impl in (None,licensing._impl):
        monkeypatch.setattr(licensing,'_impl',impl)
        lic=licensing.configured()
        assert not lic.status()['canExport'] and lic.status()['broken']
        app=App(tmp_path/'app',lic);app.api_new({'name':'虚构未激活考试','grades':['七年级']})
        assert app.plan and app.store.load(app.plan['id'])
        with pytest.raises(PermissionError):lic.require_export()


def test_damaged_public_configuration_does_not_unlock_or_prevent_view(tmp_path,monkeypatch):
    import exam_room.licensing as licensing
    p=tmp_path/'public.json';p.write_text('{broken')
    monkeypatch.setattr(licensing.paths,'PUBLIC',p)
    assert licensing.configured().status()['broken']
    assert not licensing.configured().status()['canExport']


def test_signed_other_product_is_rejected_and_existing_code_format_kept(tmp_path):
    import pytest
    import json
    from exam_room.licensing import b64
    key=Ed25519PrivateKey.generate();lic=License(tmp_path,key.public_key(),machine='TEST')
    payload=json.dumps({'product':'other-product','machine':'TEST','expiry':None}).encode()
    with pytest.raises(ValueError):lic.activate(b64(payload)+'.'+b64(key.sign(payload)))
    code=sign_code(key,'TEST',None);assert lic.activate(code)['state']=='active'


def test_frozen_native_public_key_is_bound_to_compiled_product(tmp_path,monkeypatch):
    import hashlib
    from types import SimpleNamespace
    import exam_room.licensing as licensing
    key=Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
    raw=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    path=tmp_path/'public.json';path.write_text(json.dumps({'public_key':licensing.b64(raw),'contact':'虚构联系人'}))
    monkeypatch.setattr(licensing.paths,'PUBLIC',path);monkeypatch.setattr(licensing.paths,'FROZEN',True)
    original=licensing._impl
    monkeypatch.setattr(licensing,'_impl',SimpleNamespace(PRODUCT='exam-room-tool',PUBLIC_KEY_SHA256='bad',License=original.License,machine_code=lambda:'TEST'))
    monkeypatch.setattr(licensing,'module_kind',lambda:'native')
    assert licensing.configured().status()['broken']
    monkeypatch.setattr(licensing._impl,'PUBLIC_KEY_SHA256',hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(licensing.paths,'license_dir',lambda:tmp_path/'isolated-license')
    assert licensing.configured().status()['state']=='trial'
