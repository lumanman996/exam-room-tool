"""本机发码：init 创建独立密钥；issue 签发一码一机激活码。私钥仅保存在 admin/。"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from exam_room.licensing import b64,sign_code
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(); p.add_argument('action',choices=['init','issue']); p.add_argument('--machine');p.add_argument('--expiry');p.add_argument('--contact',default='')
a=p.parse_args(); keypath=ROOT/'admin'/'private.pem'
if a.action=='init':
    if keypath.exists(): raise SystemExit('密钥已存在；不会覆盖。')
    key=Ed25519PrivateKey.generate(); keypath.parent.mkdir(exist_ok=True)
    keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())); keypath.chmod(0o600)
    (ROOT/'exam_room'/'_license_public.json').write_text(json.dumps({'public_key':b64(key.public_key().public_bytes_raw()),'contact':a.contact}),encoding='utf-8')
    print('已创建独立产品密钥。私钥在 admin/private.pem，请妥善备份；不要上传。')
else:
    if not a.machine: raise SystemExit('请指定 --machine 机器码。')
    if a.expiry:
        from datetime import date
        date.fromisoformat(a.expiry)
    key=serialization.load_pem_private_key(keypath.read_bytes(),password=None)
    print(sign_code(key,a.machine,a.expiry))
