import base64, json, urllib.request
from exam_room.server import start

def call(url, token, name, body=None):
    req=urllib.request.Request(url+'api/'+name,data=json.dumps(body or {}).encode(),headers={'X-Token':token,'Content-Type':'application/json'})
    return json.loads(urllib.request.urlopen(req).read())

def test_service_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv('EXAM_ROOM_HOME',str(tmp_path))
    httpd,url,app=start();
    try:
        assert call(url,app.token,'new',{'name':'接口测试','grades':['七年级']})['ok']
        state=call(url,app.token,'state')['data']; assert state['plan']['name']=='接口测试'
        tpl=call(url,app.token,'template',{'kind':'students'})['data']; assert tpl['url'].startswith('/download/')
        plan=state['plan']; rev=plan['revision']; plan['students']=[{'name':'学生甲','grade':'七年级','class_name':'七1','number':'00001'}]
        saved=call(url,app.token,'save',{'plan':plan,'revision':rev}); assert saved['ok']
        export=call(url,app.token,'export',{'format':'xlsx','sections':['students'],'draft':True})
        assert export['ok'] and export['data']['name'].endswith('.xlsx')
    finally: httpd.shutdown()

def test_token_required(tmp_path, monkeypatch):
    monkeypatch.setenv('EXAM_ROOM_HOME',str(tmp_path)); httpd,url,app=start()
    try:
        req=urllib.request.Request(url+'api/state',data=b'{}',headers={'X-Token':'wrong','Content-Type':'application/json'})
        try: urllib.request.urlopen(req)
        except urllib.error.HTTPError as e: assert e.code==403
        else: assert False
    finally: httpd.shutdown()


def test_settings_scripts_are_served(tmp_path,monkeypatch):
    monkeypatch.setenv('EXAM_ROOM_HOME',str(tmp_path));httpd,url,app=start()
    try:
        for script in ('numbering.js','rooms.js','controls.js'):
            with urllib.request.urlopen(url+script) as response:
                assert response.headers['Content-Type'].startswith('text/javascript')
                assert 'use strict' in response.read().decode()
    finally:httpd.shutdown()


def test_expired_trial_keeps_plan_operations_but_blocks_export(tmp_path):
    from datetime import datetime,timedelta,timezone
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from exam_room.licensing import License,sign_code
    from exam_room.server import App
    from exam_room.model import demo_plan
    import pytest
    key=Ed25519PrivateKey.generate();now=datetime(2026,10,5,tzinfo=timezone.utc)
    License(tmp_path/'lic',key.public_key(),machine='T',clock=lambda:now).status()
    lic=License(tmp_path/'lic',key.public_key(),machine='T',clock=lambda:now+timedelta(days=4))
    app=App(root=tmp_path,license=lic);app.commit(demo_plan())
    assert app.api_plan_export({})['name'].endswith('.json')
    assert app.api_clone({'id':app.plan['id']})['plan']
    with pytest.raises(PermissionError):app.api_export({'format':'xlsx','sections':['students'],'draft':True})
    app.api_activate({'code':sign_code(key,'T',None)})
    assert app.api_export({'format':'xlsx','sections':['students'],'draft':True})['url']


def test_subject_edit_marks_results_stale_and_undo_restores_special_flag(tmp_path):
    from copy import deepcopy
    from exam_room.server import App
    from exam_room.licensing import License
    from exam_room.model import demo_plan
    from exam_room import engine
    app=App(root=tmp_path,license=License(tmp_path/'lic',None))
    p=engine.assign_seats(demo_plan())['plan'];p=engine.assign_invigilators(p)['plan'];app.commit(p)
    students=engine.participants(app.plan,app.plan['exams'][0]);a=app.plan['seats']['base'][students[0]['id']]
    other=next(s for s in students[1:] if app.plan['seats']['base'][s['id']]['room_id']==a['room_id']);pos=app.plan['seats']['base'][other['id']]
    eid=app.plan['exams'][0]['id']
    app.api_adjust_seat(dict(student_id=students[0]['id'],room_id=pos['room_id'],seat=pos['seat'],exam_id=eid,swap=True))
    assert app.plan['exams'][0]['special_seating']
    app.api_undo({})
    assert not app.plan['exams'][0]['special_seating'] and not app.plan.get('stale')
    p=deepcopy(app.plan);p['exams'][0]['subject']='语文修改'
    app.api_save({'plan':p,'revision':p['revision']})
    assert 'seats' in app.plan['stale']
