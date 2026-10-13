"""许可公开入口。

试用与激活的实现在 _license_impl.py，不在公开仓库里，只在打包正式安装包时编译成机器码放进去。
源码运行缺少它时不做限制；正式包里缺少或换成源码则锁住导出，查看、编排和保存仍可使用。
"""
import base64
import importlib
import hashlib
import importlib.machinery
import json
from . import paths
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PRODUCT='exam-room-tool'
BROKEN='程序的试用与激活文件缺失或损坏，导出与打印已锁定。查看、编排和保存仍可使用，请重新下载安装包。'
try:
    from . import _license_impl as _impl
except Exception:
    _impl=None


def module_kind():
    if _impl is None:return 'none'
    filename=str(getattr(_impl,'__file__',''))
    return 'native' if any(filename.endswith(s) for s in importlib.machinery.EXTENSION_SUFFIXES) else 'python'


def b64(b):return base64.urlsafe_b64encode(b).decode().rstrip('=')
def unb64(s):return base64.urlsafe_b64decode(s+'='*(-len(s)%4))
def machine_code():return _impl.machine_code() if _impl is not None else ''
def sign_code(key,machine,expiry):
    if _impl is None:raise ValueError(BROKEN)
    return _impl.sign_code(key,machine,expiry)


class BlockedLicense:
    def __init__(self,message=BROKEN,contact=''):
        self.message=message;self.contact=contact
    def status(self):
        return dict(state='expired',canExport=False,daysLeft=0,expiry=None,machine=machine_code(),
                    contact=self.contact,message=self.message,broken=True,module_kind=module_kind())
    def activate(self,code):raise ValueError(self.message)
    def require_export(self):raise PermissionError(self.message)


class OpenLicense:
    """公开源码运行且没有验证模块：不做限制。"""
    def __init__(self,contact=''):self.contact=contact
    def status(self):
        return dict(state='open',canExport=True,daysLeft=0,expiry=None,machine='',contact=self.contact,message='源码开发版')
    def activate(self,code):raise ValueError('源码开发版不需要激活。')
    def require_export(self):pass


class License:
    """Compatible constructor for fictional tests and existing offline licence state."""
    def __init__(self,directory,public_key,machine=None,clock=None,contact=''):
        if _impl is None and not paths.FROZEN:
            self.delegate=OpenLicense(contact);return
        broken=_impl is None or (paths.FROZEN and (module_kind()!='native' or public_key is None))
        self.delegate=BlockedLicense(contact=contact) if broken else _impl.License(directory,public_key,machine,clock,contact)
    def __getattr__(self,name):return getattr(self.delegate,name)
    def status(self):
        if paths.FROZEN and module_kind()!='native':return BlockedLicense().status()
        return self.delegate.status()
    def activate(self,code):
        if paths.FROZEN and module_kind()!='native':raise ValueError(BROKEN)
        return self.delegate.activate(code)
    def require_export(self):
        status=self.status()
        if not status['canExport']:raise PermissionError(status['message'])


def _contact():
    try:
        value=json.loads(paths.PUBLIC.read_text(encoding='utf-8')).get('contact','')
        return value if isinstance(value,str) else ''
    except (OSError,ValueError,AttributeError):return ''


def configured():
    if _impl is None and not paths.FROZEN:return OpenLicense(_contact())
    if _impl is None or (paths.FROZEN and module_kind()!='native'):return BlockedLicense()
    public=None;contact=''
    if paths.PUBLIC.exists():
        try:
            cfg=json.loads(paths.PUBLIC.read_text(encoding='utf-8'))
            if not isinstance(cfg,dict) or set(cfg)-{'public_key','contact'} or not isinstance(cfg.get('contact',''),str):raise ValueError()
            raw=unb64(cfg['public_key']);public=Ed25519PublicKey.from_public_bytes(raw);contact=cfg.get('contact','')
            if paths.FROZEN and (getattr(_impl,'PRODUCT',None)!=PRODUCT or getattr(_impl,'PUBLIC_KEY_SHA256',None)!=hashlib.sha256(raw).hexdigest()):return BlockedLicense(contact=contact)
        except (OSError,ValueError,TypeError,KeyError):return BlockedLicense()
    elif paths.FROZEN:return BlockedLicense()
    return License(paths.license_dir(),public,contact=contact)
