"""Persistent settings stored in %APPDATA%\\gamers-ping\\config.json."""
import copy
import json
import os

# exe name (lower-case) -> display name
KNOWN_GAMES = {
    # Call of Duty
    "cod.exe": "Call of Duty", "modernwarfare.exe": "Call of Duty", "blackopscoldwar.exe": "Call of Duty",
    "blackops6.exe": "Call of Duty", "blackops7.exe": "Call of Duty", "cod22-cod.exe": "Call of Duty",
    "cod23-cod.exe": "Call of Duty", "s2_mp64_ship.exe": "Call of Duty", "s2_sp64_ship.exe": "Call of Duty",
    "h1_mp64_ship.exe": "Call of Duty", "iw7_ship.exe": "Call of Duty", "bo3.exe": "Call of Duty",
    # Others
    "fortniteclient-win64-shipping.exe": "Fortnite",
    "rustclient.exe": "Rust",
    "cs2.exe": "Counter-Strike 2",
    "valorant-win64-shipping.exe": "Valorant",
    "r5apex.exe": "Apex Legends", "r5apex_dx12.exe": "Apex Legends",
    "overwatch.exe": "Overwatch 2",
    "rocketleague.exe": "Rocket League",
    "rainbowsix.exe": "Rainbow Six Siege", "rainbowsix_vulkan.exe": "Rainbow Six Siege",
    "tslgame.exe": "PUBG",
    "marvel-win64-shipping.exe": "Marvel Rivals",
    "dota2.exe": "Dota 2",
    "league of legends.exe": "League of Legends",
    "bf2042.exe": "Battlefield 2042",
    "destiny2.exe": "Destiny 2",
    "escapefromtarkov.exe": "Escape from Tarkov",
    "gta5.exe": "GTA V", "gta5_enhanced.exe": "GTA V",
    "haloinfinite.exe": "Halo Infinite",
    "helldivers2.exe": "Helldivers 2",
    "project8.exe": "Deadlock",
    "tf_win64.exe": "Team Fortress 2",
    "deltaforceclient-win64-shipping.exe": "Delta Force",
}

DEFAULTS = {
    "interval_ms": 1000,
    "timeout_ms": 1000,
    "window": 120,  # samples shown in each graph
    "targets": [{"name": "Google DNS", "host": "8.8.8.8"}],
    # Extra process names (exe) to treat as games, on top of KNOWN_GAMES.
    "games": [],
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
