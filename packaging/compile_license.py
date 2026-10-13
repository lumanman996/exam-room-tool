"""在隔离暂存目录编译本产品许可；原始源码、公钥和用户数据不改动。"""
import ast
from contextlib import contextmanager
import importlib.util
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def hidden_imports(source):
    names={'exam_room.paths','exam_room.model'}
    for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
        if isinstance(node,ast.Import):names.update(a.name for a in node.names)
        elif isinstance(node,ast.ImportFrom) and not node.level and node.module:names.add(node.module)
    result=[]
    for name in sorted(names-{'__future__'}):
        try:
            if importlib.util.find_spec(name):result.append(name)
        except (ImportError,ValueError):pass
    return result


@contextmanager
def compiled_license(root,work):
    root=Path(root);source=root/'exam_room/_license_impl.py'
    if not source.is_file():raise ValueError('缺少本产品许可验证源码，不能生成正式候选包。')
    config=json.loads((root/'exam_room/_license_public.json').read_text(encoding='utf-8'))
    raw=base64.urlsafe_b64decode(config['public_key']+'='*(-len(config['public_key'])%4))
    if len(raw)!=32:raise ValueError('本产品公钥格式不正确。')
    fingerprint=hashlib.sha256(raw).hexdigest()
    imports=hidden_imports(source);Path(work).mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='license-stage-',dir=work) as temp:
        stage=Path(temp);pkg=stage/'exam_room';pkg.mkdir()
        for p in (root/'exam_room').glob('*.py'):shutil.copyfile(p,pkg/p.name)
        with (pkg/'_license_impl.py').open('a',encoding='utf-8') as stream:
            stream.write('\nPUBLIC_KEY_SHA256='+repr(fingerprint)+'\n')
        setup=stage/'compile.py'
        setup.write_text('''from setuptools import setup,Extension
from Cython.Build import cythonize
setup(name='exam-room-license',script_args=['build_ext','--inplace','--build-temp','temp','-q'],
 ext_modules=cythonize([Extension('exam_room._license_impl',['exam_room/_license_impl.py'])],
 compiler_directives={'language_level':3,'annotation_typing':False,'binding':False,'emit_code_comments':False,'embedsignature':False},quiet=True,build_dir='generated'))
''',encoding='utf-8')
        subprocess.run([sys.executable,str(setup)],cwd=stage,check=True)
        outputs=[p for p in pkg.glob('_license_impl.*') if p.suffix in ('.pyd','.so')]
        if len(outputs)!=1:raise ValueError('本产品许可验证模块没有正确编译。')
        (pkg/'_license_impl.py').unlink()
        (pkg/'_build_info.py').write_text("LICENSED=True\nPRODUCT='exam-room-tool'\n",encoding='utf-8')
        yield dict(native=outputs[0],stage=stage,hidden_imports=imports)
