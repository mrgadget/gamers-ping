"""Self-update from the latest GitHub Release.

Flow: query the releases API -> if the tag is newer than __version__, download the
exe asset next to the running exe, verify it, then swap it in. Windows lets a running
exe be renamed (not overwritten), so we move it to *.old and put the new one in its
place; the *.old is deleted on the next start.
"""
import hashlib
import json
import os
import sys
import urllib.request

from . import __version__

REPO = "mrgadget/gamers-ping"
ASSET = "GamersPing.exe"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
_HEADERS = {"User-Agent": f"gamers-ping/{__version__}", "Accept": "application/vnd.github+json"}


def parse_version(tag: str) -> tuple[int, ...]:
    parts = []
    for p in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(tag: str, current: str = __version__) -> bool:
    a, b = parse_version(tag), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def can_self_update() -> bool:
    return bool(getattr(sys, "frozen", False))


def cleanup_old() -> None:
    """Remove the previous exe left behind by an update."""
    if can_self_update():
        try:
            os.remove(sys.executable + ".old")
        except OSError:
            pass


def check_latest(opener=urllib.request.urlopen) -> dict | None:
    """-> {'version', 'url', 'size', 'sha256'} for a newer release, else None."""
    req = urllib.request.Request(API, headers=_HEADERS)
    with opener(req, timeout=15) as r:
        data = json.load(r)
    tag = data.get("tag_name", "")
    if not is_newer(tag):
        return None
    for a in data.get("assets", []):
        url = a.get("browser_download_url", "")
        if a.get("name") == ASSET and url.startswith(f"https://github.com/{REPO}/releases/download/"):
            digest = a.get("digest") or ""
            return {"version": tag.lstrip("vV"), "url": url, "size": a.get("size"),
                    "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None}
    return None


def download(release: dict, dest: str, opener=urllib.request.urlopen) -> None:
    """Download + verify into `dest`; raises on any mismatch (and leaves nothing behind)."""
    req = urllib.request.Request(release["url"], headers={"User-Agent": _HEADERS["User-Agent"]})
    h = hashlib.sha256()
    total = 0
    try:
        with opener(req, timeout=60) as r, open(dest, "wb") as f:
            first = True
            while chunk := r.read(1 << 16):
                if first and chunk[:2] != b"MZ":
                    raise ValueError("download is not a Windows executable")
                first = False
                h.update(chunk)
                total += len(chunk)
                f.write(chunk)
        if release.get("size") and total != release["size"]:
            raise ValueError(f"size mismatch ({total} != {release['size']})")
        if release.get("sha256") and h.hexdigest() != release["sha256"]:
            raise ValueError("checksum mismatch")
    except BaseException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise


def swap_in(new_path: str, exe_path: str) -> None:
    """Replace exe_path with new_path; the old file is kept as exe_path + '.old'."""
    old = exe_path + ".old"
    try:
        os.remove(old)
    except OSError:
        pass
    os.replace(exe_path, old)
    try:
        os.replace(new_path, exe_path)
    except OSError:
        os.replace(old, exe_path)  # roll back
        raise


def update_if_available() -> str | None:
    """Check, download and install. Returns the new version string, or None if nothing changed."""
    if not can_self_update():
        return None
    release = check_latest()
    if not release:
        return None
    exe = sys.executable
    new = exe + ".new"
    download(release, new)
    swap_in(new, exe)
    return release["version"]


def restart() -> None:
    """Launch the (now updated) exe and let the caller exit."""
    import subprocess
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")  # don't reuse our onefile temp dir
    subprocess.Popen([sys.executable], env=env, close_fds=True)
