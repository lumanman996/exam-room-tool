"""把 HTML 打印成 PDF：调用电脑上已有的 Edge / Chrome（不联网，不另装东西）。找不到浏览器时返回 None。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def find_browser() -> str | None:
    if os.environ.get("EXAM_ROOM_BROWSER"):
        return os.environ["EXAM_ROOM_BROWSER"]
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        tails = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"]
        cands = [os.path.join(r, t) for t in tails for r in roots if r]
    elif sys.platform == "darwin":
        cands = [f"/Applications/{n}.app/Contents/MacOS/{n}" for n in ("Google Chrome", "Microsoft Edge", "Chromium")]
    else:
        cands = [shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def page_count(out: Path) -> int:
    try:return len(re.findall(rb'/Type\s*/Page\b',out.read_bytes()))
    except OSError:return 0


def complete(out: Path) -> bool:
    try:
        blob=out.read_bytes();return blob.startswith(b'%PDF-') and b'%%EOF' in blob[-1024:] and page_count(out)>0
    except OSError:return False


def html_to_pdf(html: str, out: Path, cancel=None, timeout=90) -> bool:
    """仅发布完整 PDF；超时/取消终止本次专用浏览器，保留用户浏览器。"""
    exe=find_browser()
    if not exe or (cancel is not None and cancel.is_set()):return False
    out=Path(out);out.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        src=Path(tmp)/'doc.html';src.write_text(html,encoding='utf-8')
        cmd=[exe,'--headless','--disable-gpu','--no-first-run','--no-pdf-header-footer','--print-to-pdf-no-header',f'--user-data-dir={Path(tmp)/"profile"}',f'--print-to-pdf={out}',src.as_uri()]
        proc=None;cancelled=False
        try:
            proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline=time.monotonic()+timeout;last=-1;stable=0
            while time.monotonic()<deadline:
                if cancel is not None and cancel.is_set():cancelled=True;break
                size=out.stat().st_size if out.is_file() else 0
                stable=stable+1 if size>0 and size==last else 0;last=size
                if stable>=4 and complete(out):break
                if proc.poll() is not None:break
                time.sleep(.1)
            valid=not cancelled and complete(out)
        except (OSError,ValueError):valid=False
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait(timeout=3)
        if cancel is not None and cancel.is_set():valid=False
        if not valid:out.unlink(missing_ok=True)
        return valid
