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

    def _run(self, t: Target) -> None:
        pinger = Pinger()
        try:
            while not t.stop.is_set():
                start = time.monotonic()
                host = t.host
                rtt = pinger.ping(host, self.settings["timeout_ms"]) if host else None
                t.samples.append((time.time(), rtt))
                t.stop.wait(max(0.05, self.settings["interval_ms"] / 1000 - (time.monotonic() - start)))
        finally:
            pinger.close()
