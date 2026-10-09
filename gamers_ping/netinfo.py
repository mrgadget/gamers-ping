"""Network helpers: default gateway, local IP, admin check."""
import ctypes
import re
import socket
import subprocess

_NO_WINDOW = 0x08000000


def default_gateway() -> str | None:
    """Gateway of the lowest-metric IPv4 default route."""
    try:
        out = subprocess.run(["route", "print", "-4", "0.0.0.0"], capture_output=True, text=True,
                             timeout=5, creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_default_gateway(out)


def parse_default_gateway(text: str) -> str | None:
    best = None
    for line in text.splitlines():
        m = re.match(r"\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)\s+\S+\s+(\d+)\s*$", line)
        if m and (best is None or int(m.group(2)) < best[1]):
            best = (m.group(1), int(m.group(2)))
    return best[0] if best else None


def local_ip() -> str | None:
    """Local IPv4 address used to reach the internet (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False
