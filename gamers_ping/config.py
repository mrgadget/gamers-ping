"""Persistent settings stored in %APPDATA%\\gamers-ping\\config.json."""
import copy
import json
import os

DEFAULTS = {
    "interval_ms": 1000,
    "timeout_ms": 1000,
    "window": 120,  # samples shown in each graph
    "targets": [{"name": "Google DNS", "host": "8.8.8.8"}],
    # Process names (lower-case) that trigger game-server detection.
    "games": [
        "cod.exe",  # Warzone / MW (2019+) / MW2 / MW3
        "modernwarfare.exe",
        "blackopscoldwar.exe",
        "blackops6.exe",
        "blackops7.exe",
        "cod22-cod.exe",
        "cod23-cod.exe",
        "s2_mp64_ship.exe",
        "s2_sp64_ship.exe",
        "h1_mp64_ship.exe",
        "iw7_ship.exe",
        "bo3.exe",
    ],
}


def config_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "gamers-ping", "config.json")


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg: dict) -> None:
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass
