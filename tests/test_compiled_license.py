import importlib.util
from pathlib import Path
import subprocess
import pytest


def support():
    spec=importlib.util.spec_from_file_location('exam_compile_support',Path(__file__).parents[1]/'packaging/compile_license.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_compilation_stages_without_mutating_source_and_cleans_on_failure(tmp_path,monkeypatch):
    m=support();root=tmp_path/'source';package=root/'exam_room';package.mkdir(parents=True)
    (package/'__init__.py').write_text('pass');src=package/'_license_impl.py';src.write_text('import json\nPRODUCT="exam-room-tool"\n')
    (package/'_license_public.json').write_text('{"public_key":"'+('A'*43)+'"}')
    original=src.read_bytes();work=tmp_path/'work';work.mkdir()
    def compile(command,**kwargs):
        stage=Path(kwargs['cwd']);assert 'PUBLIC_KEY_SHA256' in (stage/'exam_room/_license_impl.py').read_text();native=stage/'exam_room/_license_impl.test.pyd';native.write_bytes(b'fictional native fixture')
        return subprocess.CompletedProcess(command,0)
    monkeypatch.setattr(m.subprocess,'run',compile)
    with pytest.raises(RuntimeError):
        with m.compiled_license(root,work) as item:
            assert item['native'].is_file() and not (item['stage']/'exam_room/_license_impl.py').exists()
            assert src.read_bytes()==original
            assert 'json' in item['hidden_imports']
            raise RuntimeError('模拟构建失败')
    assert src.read_bytes()==original and not list(work.rglob('*.pyd'))


def test_missing_implementation_cannot_build_unrestricted_candidate(tmp_path):
    m=support();(tmp_path/'exam_room').mkdir()
    with pytest.raises(ValueError):
        with m.compiled_license(tmp_path,tmp_path/'work'):pass
