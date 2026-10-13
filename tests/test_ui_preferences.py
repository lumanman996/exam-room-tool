import json
from copy import deepcopy
from urllib.request import Request,urlopen
import pytest
from exam_room.server import App,start
from exam_room.licensing import License
from exam_room import paths
from test_backend_hardening import ready


def call(url,app,body):
    request=Request(url+'api/ui_preferences_save',data=json.dumps(body).encode(),headers={'X-Token':app.token})
    return json.loads(urlopen(request).read())


def test_preferences_survive_different_port_restart_without_exam_revision_change(tmp_path,monkeypatch):
    ui=tmp_path/'mock-ui';ui.mkdir();(ui/'index.html').write_text('<html><script type="application/json" id="uiPreferences">__UI_PREFS__</script></html>');monkeypatch.setattr(paths,'UI',ui)
    app=App(tmp_path,License(tmp_path/'lic',None));app.commit(ready());before=deepcopy(app.plan);h1,u1,_=start(app);h2=None
    try:
        assert '>null<' in urlopen(u1).read().decode()
        prefs=dict(theme='dark',fontScale=1.3,density='compact');result=call(u1,app,{'preferences':prefs});assert result['ok'] and result['data']==prefs
        assert app.plan==before and app.store.load(before['id'])['revision']==before['revision']
        h1.shutdown()
        # Retain the old bound socket until the new service starts, guaranteeing
        # a different origin while recreating App from saved files.
        other=App(tmp_path,License(tmp_path/'lic',None));h2,u2,_=start(other);assert u1!=u2
        assert other.ui_preferences==prefs and other.view()['ui_preferences']==prefs
        html=urlopen(u2).read().decode();assert '__UI_PREFS__' not in html and '"dark"' in html and '1.3' in html
    finally:
        h1.server_close()
        if h2:h2.shutdown();h2.server_close()


@pytest.mark.parametrize('prefs',[{'theme':'evil','fontScale':1,'density':'standard'},{'theme':'system','fontScale':0.8,'density':'standard'},{'theme':'light','fontScale':True,'density':'standard'},{'theme':'light','fontScale':1,'density':'wide'}])
def test_invalid_preferences_do_not_overwrite_saved_file(tmp_path,prefs):
    app=App(tmp_path,License(tmp_path/'lic',None));valid=dict(theme='system',fontScale=1,density='standard');app.api_ui_preferences_save({'preferences':valid});before=(tmp_path/'ui-preferences.json').read_bytes()
    with pytest.raises(ValueError):app.api_ui_preferences_save({'preferences':prefs})
    assert (tmp_path/'ui-preferences.json').read_bytes()==before


def test_damaged_preferences_fall_back_without_harming_exams(tmp_path):
    app=App(tmp_path,License(tmp_path/'lic',None));app.commit(ready());(tmp_path/'ui-preferences.json').write_text('bad')
    other=App(tmp_path,License(tmp_path/'lic',None));assert other.ui_preferences is None
    assert other.store.load(app.plan['id'])['students']==app.plan['students']
