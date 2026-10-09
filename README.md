# Gamers Ping

A small Windows desktop app that graphs your connection quality in real time.

- **Local gateway** (auto-detected, follows network changes)
- **Custom targets** – 8.8.8.8 by default; add/remove any IP or hostname (saved to `%APPDATA%\gamers-ping\config.json`)
- **Game detection** – when Call of Duty (or another configured game) is running, the servers it is talking to are added automatically and pinged. Stats per target: latest, avg/min/max, jitter, packet loss, live graph.

## Run

Portable exe: `powershell -File build.ps1` produces `dist\GamersPing.exe` (single file, no install).
From source: `pip install -r requirements.txt` then `python -m gamers_ping`.

## Game server detection

CoD uses UDP, and Windows doesn't reveal the remote end of UDP sockets. With **administrator** rights the app
sniffs inbound UDP via a raw socket (no Npcap/driver needed) on the ports the game process owns and tracks the
busiest public IPs. Use the "Restart as admin" button. Without admin it falls back to the game's TCP peers
(mostly Activision services, not the match server).

Caveat: many game servers drop ICMP. If a game server never answers, the app traces the path and pings the last router that does answer (the card says "blocks ping; showing hop N"). That measures your route up to the server's network, not the server itself. It re-checks direct ping every 30s.

Built-in games: Call of Duty, Fortnite, Rust, CS2, Valorant, Apex, Overwatch 2, Rocket League, R6 Siege, PUBG, Marvel Rivals, Dota 2, LoL, Battlefield 2042, Destiny 2, Tarkov, GTA V, Halo Infinite, Helldivers 2, Deadlock, TF2, Delta Force. Add others by listing exe names under `games` in the config file.

## Tests

`python -m unittest discover -s tests`
