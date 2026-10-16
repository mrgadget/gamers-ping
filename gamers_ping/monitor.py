"""Ping targets, their sample history, and the threads that drive them."""
import threading
import time
from collections import deque

from .icmp import Pinger
from .netinfo import default_gateway

MAX_SAMPLES = 3600


class Target:
    def __init__(self, name: str, host: str | None, kind: str):
        self.name = name
        self.host = host
        self.kind = kind  # "gateway" | "custom" | "game"
        self.samples: deque[tuple[float, float | None]] = deque(maxlen=MAX_SAMPLES)
        self.stop = threading.Event()
        # Fallback when the host drops ICMP: ping the last router that answers instead.
        self.via: str | None = None
        self.via_hop: int | None = None
        self.hops: list[tuple[int, str]] = []  # candidate routers, nearest first

    def recent(self, n: int) -> list[float | None]:
        return [rtt for _, rtt in list(self.samples)[-n:]]


def compute_stats(values: list[float | None]) -> dict:
    ok = [v for v in values if v is not None]
    stats = {
        "count": len(values),
        "last": values[-1] if values else None,
        "loss": 100.0 * (len(values) - len(ok)) / len(values) if values else 0.0,
        "avg": sum(ok) / len(ok) if ok else None,
        "min": min(ok) if ok else None,
        "max": max(ok) if ok else None,
        "jitter": None,
    }
    if len(ok) > 1:
        stats["jitter"] = sum(abs(a - b) for a, b in zip(ok, ok[1:])) / (len(ok) - 1)
    return stats


class Monitor:
    def __init__(self, settings: dict):
        self.settings = settings
        self._lock = threading.Lock()
        self._targets: list[Target] = []
        self._closed = threading.Event()
        self._gateway = self.add("Local gateway", None, "gateway")
        threading.Thread(target=self._watch_gateway, daemon=True).start()

    def targets(self) -> list[Target]:
        with self._lock:
            return list(self._targets)

    def add(self, name: str, host: str | None, kind: str = "custom") -> Target:
        t = Target(name, host, kind)
        with self._lock:
            self._targets.append(t)
        threading.Thread(target=self._run, args=(t,), daemon=True).start()
        return t

    def remove(self, t: Target) -> None:
        t.stop.set()
        with self._lock:
            if t in self._targets:
                self._targets.remove(t)

    def sync_game(self, ips: list[str]) -> None:
        """Make the set of 'game' targets match `ips`."""
        with self._lock:
            current = {t.host: t for t in self._targets if t.kind == "game"}
        for ip, t in current.items():
            if ip not in ips:
                self.remove(t)
        for ip in ips:
            if ip not in current:
                self.add(f"Game server", ip, "game")

    def close(self) -> None:
        self._closed.set()
        for t in self.targets():
            t.stop.set()

    def _watch_gateway(self) -> None:
        while not self._closed.is_set():
            self._gateway.host = default_gateway()
            self._closed.wait(15)

    def _use_farthest_answering(self, t: Target, pinger: Pinger) -> bool:
        """Walk back along t.hops from the far end until a router answers a real ping."""
        timeout = self.settings["timeout_ms"]
        while t.hops:
            ttl, ip = t.hops[-1]
            if any(pinger.ping(ip, timeout) is not None for _ in range(2)):
                t.via_hop, t.via = ttl, ip
                return True
            t.hops.pop()  # this router won't answer pings: go up a level
        t.via = t.via_hop = None
        return False

    def _run(self, t: Target) -> None:
        pinger = Pinger()
        misses, last_direct = 0, 0.0
        try:
            while not t.stop.is_set():
                start = time.monotonic()
                host = t.host
                if host is None:  # e.g. gateway not resolved yet: don't count it as loss
                    t.stop.wait(0.2)
                    continue
                if t.via and start - last_direct > 30:  # periodically see if the host answers directly now
                    last_direct = start
                    if pinger.ping(host, self.settings["timeout_ms"]) is not None:
                        t.via = t.via_hop = None
                        t.hops = []
                target = t.via or host
                rtt = pinger.ping(target, self.settings["timeout_ms"])
                t.samples.append((time.time(), rtt))
                misses = 0 if rtt is not None else misses + 1
                if t.kind == "game" and misses >= 5:
                    if t.via:  # chosen router went quiet: step back up the path
                        if t.hops:
                            t.hops.pop()
                        self._use_farthest_answering(t, pinger)
                        misses = 0
                    elif not any(v for _, v in t.samples):  # never answered: trace the path
                        t.hops = pinger.trace_hops(host)
                        if self._use_farthest_answering(t, pinger):
                            last_direct = time.monotonic()
                            t.samples.clear()
                        misses = 0
                t.stop.wait(max(0.05, self.settings["interval_ms"] / 1000 - (time.monotonic() - start)))
        finally:
            pinger.close()
