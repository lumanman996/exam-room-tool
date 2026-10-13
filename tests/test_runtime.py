from pathlib import Path
from exam_room.server import App
from exam_room import updater


def test_runtime_home_and_key_isolation(tmp_path,monkeypatch):
    monkeypatch.setenv('EXAM_ROOM_HOME',str(tmp_path))
    a=App()
    assert a.root==tmp_path
    a.api_new({'name':'独立自检'})
    assert (tmp_path/'data'/'plans'/f'{a.plan["id"]}.json').exists()
    if hasattr(a.license,'dir'):assert a.license.dir==tmp_path/'license'


def test_update_finds_current_package_case_insensitively(monkeypatch):
    monkeypatch.setattr(updater.sys,'platform','darwin')
    asset={'name':'exam-room-tool-Mac.zip','browser_download_url':updater.DOWNLOAD_PREFIX+'v1.0.1/exam-room-tool-Mac.zip'}
    assert updater.pick_asset([asset])==asset
