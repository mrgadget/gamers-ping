"""Windows-native ICMP echo via iphlpapi (no console windows, no admin needed)."""
import ctypes
import socket
import struct
import time
from ctypes import wintypes

_PAYLOAD = b"gamers-ping"


class _IpOptionInformation(ctypes.Structure):
    _fields_ = [
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.c_void_p),
    ]


class _IcmpEchoReply(ctypes.Structure):
    _fields_ = [
        ("Address", ctypes.c_uint32),
        ("Status", ctypes.c_uint32),
        ("RoundTripTime", ctypes.c_uint32),
        ("DataSize", ctypes.c_uint16),
        ("Reserved", ctypes.c_uint16),
        ("Data", ctypes.c_void_p),
        ("Options", _IpOptionInformation),
    ]


_lib = ctypes.WinDLL("iphlpapi", use_last_error=True)
_lib.IcmpCreateFile.restype = ctypes.c_void_p
_lib.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
_lib.IcmpSendEcho.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, wintypes.WORD,
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
]
_lib.IcmpSendEcho.restype = wintypes.DWORD

_RESOLVE_TTL = 60.0
_TTL_EXPIRED = 11013


class Pinger:
    """One instance per thread (the ICMP handle is not shared)."""

    def __init__(self):
        self._handle = _lib.IcmpCreateFile()
        self._cache: dict[str, tuple[float, int]] = {}
        self._buf = ctypes.create_string_buffer(ctypes.sizeof(_IcmpEchoReply) + len(_PAYLOAD) + 64)

    def close(self):
        if self._handle:
            _lib.IcmpCloseHandle(self._handle)
            self._handle = None

    def _resolve(self, host: str) -> int | None:
        now = time.monotonic()
        hit = self._cache.get(host)
        if hit and now - hit[0] < _RESOLVE_TTL:
            return hit[1]
        try:
            addr = struct.unpack("<L", socket.inet_aton(socket.gethostbyname(host)))[0]
        except (OSError, UnicodeError):
            return None
        self._cache[host] = (now, addr)
        return addr

    def probe(self, host: str, ttl: int = 128, timeout_ms: int = 1000):
        """One echo with a given TTL -> (rtt_ms, responder_ip, status); Nones on silence.

        status 0 = echo reply from the target, 11013 = TTL expired at a router on the way.
        """
        addr = self._resolve(host)
        if addr is None or not self._handle:
            return None, None, None
        opts = _IpOptionInformation(ttl, 0, 0, 0, None)
        t0 = time.perf_counter()
        n = _lib.IcmpSendEcho(self._handle, addr, _PAYLOAD, len(_PAYLOAD), ctypes.addressof(opts),
                              self._buf, len(self._buf), timeout_ms)
        elapsed = (time.perf_counter() - t0) * 1000.0
        if n == 0:
            return None, None, None
        reply = _IcmpEchoReply.from_buffer(self._buf)
        who = socket.inet_ntoa(struct.pack("<L", reply.Address))
        return max(0.1, min(elapsed, float(timeout_ms))), who, reply.Status

    def ping(self, host: str, timeout_ms: int = 1000) -> float | None:
        """Round-trip time in ms, or None on timeout / unreachable / bad host."""
        rtt, _, status = self.probe(host, 128, timeout_ms)
        return rtt if status == 0 else None

    def last_responding_hop(self, host: str, max_ttl: int = 30, timeout_ms: int = 800):
        """Traceroute; -> (hop_number, ip) of the farthest router that answers, or None.

        Stops early if the target itself answers (then no fallback is needed) or after
        several silent hops in a row (the path is being filtered from here on).
        """
        best, silent = None, 0
        for ttl in range(1, max_ttl + 1):
            _, who, status = self.probe(host, ttl, timeout_ms)
            if status == 0:
                return None
            if status == _TTL_EXPIRED:
                best, silent = (ttl, who), 0
            else:
                silent += 1
                if silent >= 6:
                    break
        return best
