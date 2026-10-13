"""检查新版本与一键更新。

只访问 GitHub 上本项目的发布页：查最新的版本号、下载对应系统的安装包。不上传任何考试数据。
更新过程：下载 → 校验 → 解压到临时文件夹 → 退出程序 → 由一个小脚本替换程序文件 → 重新打开。
数据文件夹（output、data、config）和激活状态原样保留：
  Windows 的数据就在程序文件夹里，替换时跳过这几个文件夹（config 里只补上新增的文件）；
  Mac 的数据在“文稿/考场编排”，激活状态在系统的资料库里，都不在程序包里。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path,PurePosixPath
import stat

from . import APP_NAME, REPO, VERSION as __version__, paths

API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"     # 只从本项目的发布页下载
FROZEN = bool(getattr(sys, "frozen", False))
LOG = paths.ROOT / "更新日志.txt"                                    # 更新过程的记录，出问题时用来查原因
KEEP = ("data", "output")              # Windows 程序文件夹里的这些文件夹整个不动
KEEP_EXISTING = ("config",)            # 这些文件夹里已有的文件不动，只补上新版本新增的文件


def log(msg: str):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def current_version() -> str:
    if not FROZEN and os.environ.get("EXAM_ROOM_VERSION_OVERRIDE"):   # 开发调试用；打包后的程序不认
        return os.environ["EXAM_ROOM_VERSION_OVERRIDE"]
    return __version__


def parse_version(text: str) -> tuple:
    nums = [int(n) for n in re.findall(r"\d+", str(text))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def asset_suffix() -> str | None:
    """安装包名字带版本号（exam-room-tool-v2.0.2-windows.zip），按结尾认。"""
    return {"win32": "-windows.zip", "darwin": "-mac.zip"}.get(sys.platform)


def pick_asset(assets: list) -> dict | None:
    suf = asset_suffix()
    if not suf:
        return None
    for a in assets or []:
        name = str(a.get("name") or "")
        url = str(a.get("browser_download_url") or "")
        if name.startswith("exam-room-tool-") and name.lower().endswith(suf) and url.startswith(DOWNLOAD_PREFIX):
            return a
    return None


def install_target():
    """返回 (可以自动替换的安装位置, 不能自动更新的原因)。两者必有一个为空。"""
    if not FROZEN:
        return None, "用源码运行的版本请到项目主页获取更新。"
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        target = exe.parents[2]                              # 考场编排.app
        if "AppTranslocation" in str(target):
            return None, "请先把「考场编排」拖进“应用程序”文件夹再打开，之后就可以一键更新了。"
        writable = os.access(target.parent, os.W_OK) and os.access(target, os.W_OK)
    elif sys.platform == "win32":
        target = exe.parent
        writable = os.access(target, os.W_OK)
    else:
        return None, "这个系统暂不支持一键更新。"
    if not writable:
        return None, "程序所在的文件夹不允许修改，没法一键更新，请到下载页面手动下载。"
    return target, ""


def _ssl_context():
    """打包后的程序（尤其是 Mac）不一定找得到系统的证书，带上 certifi 的证书一起用。"""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


def _open(url: str, timeout: float, accept: str = ""):
    headers = {"User-Agent": f"exam-room/{__version__}"}
    if accept:
        headers["Accept"] = accept
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout, context=_ssl_context())


def _changes(body: str) -> str:
    """发布说明里只取“更新内容”一段给使用者看，去掉后面固定的下载说明。"""
    text = body.split("## 下载")[0].replace("## 更新内容", "").strip()
    return re.sub(r"^- ", "· ", text, flags=re.M)


def check(timeout: float = 8) -> dict:
    """查最新版本。联不上网时 ok 为 False，由界面决定要不要提示。"""
    cur = current_version()
    base = {"ok": True, "current": cur, "latest": cur, "newer": False, "notes": "", "page": RELEASES_PAGE,
            "canAuto": False, "reason": "", "error": ""}
    if os.environ.get("EXAM_ROOM_NO_UPDATE_CHECK"):            # 自动测试时不联网
        return base
    try:
        with _open(API, timeout, "application/vnd.github+json") as r:
            rel = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        if getattr(e, "code", None) == 404:                  # 还没有发布过任何版本
            return base
        return {**base, "ok": False, "reason": "没有连上 GitHub，暂时没法检查更新。", "error": f"{type(e).__name__}: {e}"}
    latest = str(rel.get("tag_name", "")).lstrip("vV")
    if not latest or parse_version(latest) <= parse_version(cur):
        return {**base, "latest": latest or cur}
    asset = pick_asset(rel.get("assets", []))
    target, reason = install_target()
    if not reason and not asset:
        reason = "新版本还没有适用于这个系统的安装包。"
    return {**base, "latest": latest, "newer": True, "notes": _changes(str(rel.get("body") or "")),
            "canAuto": not reason, "reason": reason,
            "asset": {k: asset.get(k) for k in ("name", "browser_download_url", "size", "digest")} if asset else None}


def validate_archive(zip_path):
    """在任何解压程序运行前核验路径与符号链接，不写入安装目录。"""
    try:
        with zipfile.ZipFile(zip_path) as archive:
            links=set();members=archive.infolist()
            for member in members:
                name=member.filename;parts=PurePosixPath(name).parts
                if not parts or name.startswith('/') or '\\' in name or ':' in name or '..' in parts:raise ValueError('安装包包含不安全的文件路径，已停止更新。')
                if stat.S_ISLNK(member.external_attr>>16):
                    links.add(name.rstrip('/'))
                    target=archive.read(member).decode('utf-8');resolved=list(parts[:-1])
                    if not target or target.startswith('/') or '\\' in target or ':' in target:raise ValueError('安装包包含不安全的链接，已停止更新。')
                    for part in PurePosixPath(target).parts:
                        if part=='..':
                            if not resolved:raise ValueError('安装包链接越过解压目录，已停止更新。')
                            resolved.pop()
                        elif part!='.':resolved.append(part)
            for member in members:
                parts=PurePosixPath(member.filename).parts
                if any('/'.join(parts[:i]) in links for i in range(1,len(parts))):raise ValueError('安装包在符号链接内写入文件，已停止更新。')
    except (zipfile.BadZipFile,UnicodeError,OSError) as e:raise ValueError('安装包无法读取，请重新下载。') from e


class Updater:
    """下载和安装的状态。phase：idle / downloading / ready / error。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.phase, self.percent, self.error = "idle", 0, ""
        self.tmp: Path | None = None
        self.new_root: Path | None = None

    def status(self) -> dict:
        with self.lock:
            return {"phase": self.phase, "percent": self.percent, "error": self.error}

    def _set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def start(self, asset: dict):
        with self.lock:
            if self.phase in ("downloading", "ready"):
                return
            self.phase, self.percent, self.error = "downloading", 0, ""
        threading.Thread(target=self._download, args=(asset,), daemon=True).start()

    def _download(self, asset: dict):
        try:
            url = str(asset.get("browser_download_url", ""))
            if not url.startswith(DOWNLOAD_PREFIX):
                raise ValueError("下载地址不对，已停止。")
            log(f"开始下载 {asset.get('name')}")
            tmp = Path(tempfile.mkdtemp(prefix="exam-room-update-"))
            zip_path = tmp / "update.zip"
            total, done, sha = int(asset.get("size") or 0), 0, hashlib.sha256()
            with _open(url, 60) as r, open(zip_path, "wb") as f:
                while chunk := r.read(1 << 16):
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if total:
                        self._set(percent=min(99, int(done * 100 / total)))
            if total and done != total:
                raise ValueError("下载不完整，请重试。")
            digest = str(asset.get("digest") or "")
            if digest.startswith("sha256:") and digest[7:].lower() != sha.hexdigest():
                raise ValueError("下载的文件校验没有通过，请重试。")
            log(f"下载完成，{done} 字节，校验{'通过' if digest else '（发布页没有提供校验值）'}")
            self.prepare(zip_path, tmp)
        except Exception as e:
            log(f"下载没有完成：{type(e).__name__}: {e}")
            self._set(phase="error", error=str(e) if isinstance(e, ValueError) else
                      f"下载失败（{type(e).__name__}）。可以稍后再试，或到下载页面手动下载。")

    def prepare(self, zip_path: Path, tmp: Path | None = None):
        """解压安装包并确认里面有程序。成功后 phase 变为 ready。"""
        tmp = tmp or Path(tempfile.mkdtemp(prefix="exam-room-update-"))
        validate_archive(zip_path)
        new = tmp / "new"
        if sys.platform == "darwin":                         # ditto 能还原 .app 里的符号链接和可执行权限
            subprocess.run(["ditto", "-x", "-k", str(zip_path), str(new)], check=True)
            root = new / APP_NAME / f"{APP_NAME}.app"
            if not root.is_dir():
                root=next((x for x in new.glob(f'*/{APP_NAME}.app') if x.is_dir()),root)
            ok = (root / "Contents" / "MacOS" / APP_NAME).is_file()
        else:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(new)
            root = new / APP_NAME
            if not root.is_dir():
                root=next((x.parent for x in new.glob(f'*/{APP_NAME}.exe')),root)
            ok = (root / f"{APP_NAME}.exe").is_file()
        if not ok:
            raise ValueError("安装包里没有找到程序，请到下载页面手动下载。")
        self._set(tmp=tmp, new_root=root, phase="ready", percent=100)
        log(f"新版本已解压：{root}")

    def _keep_user_files(self, target: Path):
        """Windows：新版本里去掉数据文件夹，替换时就不会碰到使用者的数据。"""
        for name in KEEP:
            shutil.rmtree(self.new_root / name, ignore_errors=True)
        for name in KEEP_EXISTING:
            for f in list((self.new_root / name).rglob("*")) if (self.new_root / name).is_dir() else []:
                if f.is_file() and (target / f.relative_to(self.new_root)).exists():
                    f.unlink()
        log("已从新版本里去掉 data、output，config 里只保留新增的文件")

    def apply(self, relaunch_args: list[str] | None = None):
        """启动替换脚本。调用后程序应当立刻退出，脚本会等它退出再动手。"""
        target, reason = install_target()
        if reason:
            raise ValueError(reason)
        if self.phase != "ready" or not self.new_root:
            raise ValueError("新版本还没有准备好。")
        pid, args = os.getpid(), list(relaunch_args or [])
        log(f"开始更新：{current_version()} 的程序位于 {target}，进程 {pid}")
        if sys.platform == "darwin":
            q = shlex.quote
            old = str(target) + ".old"
            exe = target / "Contents" / "MacOS" / APP_NAME
            launch = " ".join([q(str(exe))] + [q(a) for a in args]) + " &" if args else f"open {q(str(target))}"
            script = self.tmp / "update.sh"
            script.write_text(f"""#!/bin/sh
LOG={q(str(LOG))}
log() {{ echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"; }}
log '替换脚本开始运行'
while kill -0 {pid} 2>/dev/null; do sleep 0.3; done
log '原程序已退出'
rm -rf {q(old)}
if mv {q(str(target))} {q(old)} && mv {q(str(self.new_root))} {q(str(target))}; then
  rm -rf {q(old)}
  log '程序已替换'
elif [ -d {q(old)} ] && [ ! -d {q(str(target))} ]; then
  mv {q(old)} {q(str(target))}
  log '替换没有成功，已换回原来的程序'
else
  log '替换没有成功'
fi
{launch}
log '已重新打开程序'
rm -rf {q(str(self.tmp))}
""", encoding="utf-8")
            subprocess.Popen(["/bin/sh", str(script)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log("已启动替换脚本")
        else:
            self._keep_user_files(target)
            p = lambda s: "'" + str(s).replace("'", "''") + "'"   # noqa: E731  PowerShell 单引号字符串
            exe = target / f"{APP_NAME}.exe"
            arg_part = f" -ArgumentList {','.join(p(a) for a in args)}" if args else ""
            script = self.tmp / "update.ps1"
            script.write_text(f"""$log = {p(LOG)}
function Log($m) {{ Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $m) -Encoding UTF8 }}
Log '替换脚本开始运行'
while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 300 }}
Log '原程序已退出'
$backup = Join-Path {p(self.tmp)} 'rollback'
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$manifest = @()
try {{
  foreach ($file in Get-ChildItem -LiteralPath {p(self.new_root)} -Recurse -File) {{
    $relative = $file.FullName.Substring({p(str(self.new_root))}.Length + 1)
    $destination = Join-Path {p(target)} $relative
    $original = Join-Path $backup $relative
    $existed = Test-Path -LiteralPath $destination
    if ($existed) {{
      New-Item -ItemType Directory -Path (Split-Path -Parent $original) -Force | Out-Null
      Copy-Item -LiteralPath $destination -Destination $original -Force -ErrorAction Stop
    }}
    $manifest += [PSCustomObject]@{{relative=$relative; existed=$existed}}
  }}
}} catch {{ Log ('保存原程序失败，未替换程序：' + $_.Exception.Message); exit 1 }}
$ok = $false
for ($i = 0; $i -lt 20; $i++) {{
  try {{
    Copy-Item -Path (Join-Path {p(self.new_root)} '*') -Destination {p(target)} -Recurse -Force -ErrorAction Stop
    $ok = $true
    break
  }} catch {{ Log ('复制没成功，稍后重试：' + $_.Exception.Message); Start-Sleep -Milliseconds 500 }}
}}
if (-not $ok) {{
  $restored = $true
  foreach ($item in $manifest) {{
    try {{
      $destination = Join-Path {p(target)} $item.relative
      if ($item.existed) {{ Copy-Item -LiteralPath (Join-Path $backup $item.relative) -Destination $destination -Force -ErrorAction Stop }}
      elseif (Test-Path -LiteralPath $destination) {{ Remove-Item -LiteralPath $destination -Force -ErrorAction Stop }}
    }} catch {{ $restored = $false; Log ('恢复原文件失败：' + $_.Exception.Message) }}
  }}
  Log ('替换失败，原程序恢复结果：' + $restored)
  if (-not $restored) {{ Log ('保留恢复文件：' + $backup); exit 1 }}
}}
Log ('程序文件替换完成：' + $ok)
try {{
  Start-Process -FilePath {p(exe)}{arg_part} -WorkingDirectory {p(target)} -ErrorAction Stop
  Log '已重新打开程序'
}} catch {{ Log ('重新打开失败：' + $_.Exception.Message) }}
Remove-Item -LiteralPath {p(self.tmp)} -Recurse -Force -ErrorAction SilentlyContinue
""", encoding="utf-8-sig")
            ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            cmd = [str(ps) if ps.is_file() else "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)]
            # 新进程组 + 不开黑窗口（匀班 v2.0.5 实测可行）。不能用“完全脱离控制台”的方式启动，那样脚本跑不起来。
            # 万一失败，再试一次“脱离本程序所在的作业”。
            base = 0x00000200 | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            for flags in (base, base | 0x01000000):
                try:
                    subprocess.Popen(cmd, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(self.tmp.parent))
                    log(f"已启动替换脚本（flags={flags:#x}）")
                    break
                except OSError as e:
                    log(f"启动替换脚本没成功（flags={flags:#x}）：{e}")
            else:
                raise ValueError("没能启动更新脚本，请到下载页面手动下载新版本。")

    def cleanup(self):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


def apply_from_command(source: str, relaunch_args: list) -> int:
    """命令行：--apply-update <安装包.zip | online> [--then-selftest]，不开界面直接更新（打包自检用）。"""
    up = Updater()
    try:
        if source == "online":
            info = check(timeout=20)
            if not info.get("newer") or not info.get("canAuto"):
                print("没有可以自动安装的新版本：", info.get("reason") or "已是最新", flush=True)
                return 2
            up.start(info["asset"])
            while up.status()["phase"] == "downloading":
                time.sleep(0.5)
        else:
            up.prepare(Path(source).resolve())
        if up.status()["phase"] != "ready":
            raise ValueError(up.status()["error"] or "新版本没有准备好")
        up.apply(relaunch_args)
    except Exception as e:                                   # 带窗口的程序没有控制台，原因记到更新日志里
        log(f"更新没有完成：{type(e).__name__}: {e}")
        print("更新没有完成：", e, flush=True)
        return 1
    return 0
