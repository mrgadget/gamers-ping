"""Detect a running game and find the remote server(s) it is talking to.

Games like Call of Duty talk to servers over UDP, and Windows does not expose
the remote end of unconnected UDP sockets. So we:
  1. find the game's process ids (by exe name),
  2. find the local UDP ports those processes own (psutil),
  3. sniff inbound IPv4 UDP with a raw socket (SIO_RCVALL, needs admin, no
     driver install) and rank remote public IPs hitting those ports by bytes.
Without admin we fall back to the game's established public TCP peers.
"""
import ipaddress
import re
import socket
import struct
import threading
import time

import psutil

from .netinfo import local_ip

# Call of Duty's exe is renamed every year (cod22-cod.exe, cod25-cod.exe ...)
PATTERNS = [(re.compile(r"^cod\d+-cod\.exe$"), "Call of Duty")]

MAX_SERVERS = 3
MIN_BYTES = 3000      # decayed byte score a peer needs to count as a server
HOLD_SECONDS = 20     # keep a server this long after traffic stops
POLL_SECONDS = 2.0


def is_public(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def parse_ipv4_udp(pkt: bytes):
    """-> (src_ip, dst_ip, sport, dport, length) for an IPv4/UDP packet, else None."""
    if len(pkt) < 28 or pkt[0] >> 4 != 4 or pkt[9] != 17:
        return None
    ihl = (pkt[0] & 0x0F) * 4
    if len(pkt) < ihl + 8:
        return None
    sport, dport, length = struct.unpack("!HHH", pkt[ihl:ihl + 6])
    return socket.inet_ntoa(pkt[12:16]), socket.inet_ntoa(pkt[16:20]), sport, dport, length


class UdpSniffer:
    """Accumulates per-remote-IP UDP byte scores for traffic touching `ports`."""

    def __init__(self):
        self.ports: frozenset[int] = frozenset()
        self.scores: dict[str, float] = {}
        self._lock = threading.Lock()
        self.active = False
        self.error: str | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def decay(self, factor: float = 0.6) -> dict[str, float]:
        with self._lock:
            snap = dict(self.scores)
            self.scores = {k: v * factor for k, v in self.scores.items() if v * factor > 50}
        return snap

    def feed(self, pkt: bytes) -> None:
        p = parse_ipv4_udp(pkt)
        if not p:
            return
        src, dst, sport, dport, length = p
        if dport in self.ports and is_public(src):
            remote = src
        elif sport in self.ports and is_public(dst):
            remote = dst
        else:
            return
        with self._lock:
            self.scores[remote] = self.scores.get(remote, 0.0) + length

    def _run(self) -> None:
        ip = local_ip()
        if not ip:
            self.error = "no network"
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
            s.bind((ip, 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
            s.settimeout(1.0)
        except OSError as e:
            self.error = "needs administrator" if getattr(e, "winerror", 0) == 10013 else str(e)
            return
        self.active = True
        try:
            while not self._stop.is_set():
                try:
                    self.feed(s.recv(65535))
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            self.active = False
            try:
                s.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            except OSError:
                pass
            s.close()


class GameDetector(threading.Thread):
    def __init__(self, games: dict[str, str], on_servers):
        super().__init__(daemon=True)
        self.games = {k.lower(): v for k, v in games.items()}  # exe -> display name
        self.on_servers = on_servers  # callback(list[str])
        self.game: str | None = None
        self.mode = "idle"            # idle | udp | tcp
        self.sniffer = UdpSniffer()
        self._held: dict[str, float] = {}
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        self.sniffer.stop()

    def run(self) -> None:
        self.sniffer.start()
        last: list[str] | None = None
        while not self._stop.is_set():
            try:
                servers = self._poll()
            except psutil.Error:
                servers = []
            if servers != last:
                last = servers
                self.on_servers(servers)
            self._stop.wait(POLL_SECONDS)

    def _label(self, exe: str) -> str | None:
        if exe in self.games:
            return self.games[exe]
        return next((label for rx, label in PATTERNS if rx.match(exe)), None)

    def _poll(self) -> list[str]:
        pids: dict[int, str] = {}
        for p in psutil.process_iter(["name"]):
            label = self._label((p.info["name"] or "").lower())
            if label:
                pids[p.pid] = label
        if not pids:
            self.game, self.mode = None, "idle"
            self.sniffer.ports = frozenset()
            self._held.clear()
            return []
        self.game = next(iter(pids.values()))

        conns = [c for c in psutil.net_connections("inet") if c.pid in pids]
        self.sniffer.ports = frozenset(c.laddr.port for c in conns if c.type == socket.SOCK_DGRAM)

        now = time.monotonic()
        if self.sniffer.active:
            self.mode = "udp"
            # connected UDP sockets expose their peer directly
            fresh = {c.raddr.ip: MIN_BYTES for c in conns
                     if c.type == socket.SOCK_DGRAM and c.raddr and is_public(c.raddr.ip)}
            for ip, score in self.sniffer.decay().items():
                fresh[ip] = max(fresh.get(ip, 0), score)
        else:
            self.mode = "tcp"
            fresh = {c.raddr.ip: MIN_BYTES for c in conns
                     if c.type == socket.SOCK_STREAM and c.status == psutil.CONN_ESTABLISHED
                     and c.raddr and is_public(c.raddr.ip)}

        for ip, score in sorted(fresh.items(), key=lambda kv: -kv[1])[:MAX_SERVERS]:
            if score >= MIN_BYTES:
                self._held[ip] = now
        self._held = {ip: t for ip, t in self._held.items() if now - t < HOLD_SECONDS}
        newest = sorted(self._held, key=lambda ip: -self._held[ip])[:MAX_SERVERS]
        return sorted(newest)  # stable order so the UI doesn't churn
