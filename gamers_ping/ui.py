"""tkinter front-end."""
import ctypes
import math
import sys
import tkinter as tk

from . import config
from .gamedetect import GameDetector
from .monitor import Monitor, Target, compute_stats
from .netinfo import is_admin

BG, CARD, FG, MUTED = "#14161a", "#1e2127", "#e6e6e6", "#8b93a1"
GOOD, WARN, BAD, ACCENT = "#3fb950", "#d29922", "#f85149", "#58a6ff"
GAME = "#bc8cff"

MIN_CARD_W = 400   # narrowest a card gets before we drop a column
MIN_GRAPH = 36
CARD_H = 110       # card height with a minimal graph


def latency_color(ms: float | None) -> str:
    if ms is None:
        return BAD
    return GOOD if ms < 50 else WARN if ms < 100 else BAD


def fmt(v, suffix="", digits=0):
    return "–" if v is None else f"{v:.{digits}f}{suffix}"


class Card(tk.Frame):
    def __init__(self, parent, target: Target, on_remove):
        super().__init__(parent, bg=CARD, padx=12, pady=8)
        self.target = target
        top = tk.Frame(self, bg=CARD)
        top.pack(fill="x")
        self.title = tk.Label(top, bg=CARD, fg=FG, font=("Segoe UI", 11, "bold"), anchor="w")
        self.title.pack(side="left")
        self.sub = tk.Label(top, bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.sub.pack(side="left", padx=8)
        if target.kind in ("custom", "game"):
            x = tk.Label(top, text="✕", bg=CARD, fg=MUTED, cursor="hand2")
            x.pack(side="right")
            x.bind("<Button-1>", lambda _e: on_remove(target))
        self.big = tk.Label(top, bg=CARD, font=("Segoe UI", 16, "bold"))
        self.big.pack(side="right", padx=12)
        self.canvas = tk.Canvas(self, height=MIN_GRAPH, bg="#171a1f", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(6, 4))
        self.stats = tk.Label(self, bg=CARD, fg=MUTED, font=("Consolas", 9), anchor="w")
        self.stats.pack(fill="x")
        self.bind("<Configure>", lambda e: self.stats.config(wraplength=max(e.width - 24, 100)))

    def refresh(self, window: int):
        t = self.target
        icon = {"gateway": "🏠 ", "game": "🎮 "}.get(t.kind, "🌐 ")
        self.title.config(text=icon + t.name, fg=GAME if t.kind == "game" else FG)
        sub = t.host or "(no gateway found)"
        if t.via:
            sub += f"  – blocks ping; showing hop {t.via_hop} ({t.via})"
        self.sub.config(text=sub)
        values = t.recent(window)
        s = compute_stats(values)
        if not values:
            self.big.config(text="…", fg=MUTED)
        elif s["last"] is None:
            self.big.config(text="timeout", fg=BAD)
        else:
            self.big.config(text=f"{s['last']:.0f} ms", fg=latency_color(s["last"]))
        self.stats.config(text=(
            f"avg {fmt(s['avg'])}  min {fmt(s['min'])}  max {fmt(s['max'])} ms   "
            f"jitter {fmt(s['jitter'], digits=1)} ms   loss {s['loss']:.1f}%   ({s['count']} samples)"))
        self._draw(values, window)

    def _draw(self, values, window):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        ok = [v for v in values if v is not None]
        ymax = max(60.0, (max(ok) if ok else 0) * 1.15)
        step = w / max(window - 1, 1)

        def y(ms):
            return h - 4 - (h - 8) * min(ms, ymax) / ymax

        for ms in (50, 100, 200):
            if ms < ymax:
                c.create_line(0, y(ms), w, y(ms), fill="#2a2f37", dash=(2, 4))
                c.create_text(4, y(ms) - 6, text=str(ms), fill="#4a515c", anchor="w", font=("Segoe UI", 7))
        n = len(values)
        seg: list[float] = []
        for i, v in enumerate(values):
            x = w - (n - 1 - i) * step
            if v is None:
                if len(seg) >= 4:
                    c.create_line(*seg, fill=ACCENT, width=2)
                seg = []
                c.create_rectangle(x - 1, 0, x + 1, h, fill=BAD, outline="")
            else:
                seg += [x, y(v)]
        if len(seg) >= 4:
            c.create_line(*seg, fill=ACCENT, width=2)
        elif len(seg) == 2:
            c.create_oval(seg[0] - 2, seg[1] - 2, seg[0] + 2, seg[1] + 2, fill=ACCENT, outline="")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gamers Ping")
        self.configure(bg=BG)
        self.geometry("760x820")
        self.minsize(560, 400)
        self.cfg = config.load()
        self.monitor = Monitor(self.cfg)
        for t in self.cfg["targets"]:
            self.monitor.add(t["name"], t["host"], "custom")
        self._game_ips: list[str] = []
        self.detector = GameDetector(self._games(), self._on_servers)
        self.detector.start()
        self.cards: dict[Target, Card] = {}
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(300, self._tick)

    # --- layout ---------------------------------------------------------
    def _build(self):
        banner = tk.Frame(self, bg=BG, padx=12, pady=4)
        banner.pack(fill="x")
        self.game_lbl = tk.Label(banner, bg=BG, fg=MUTED, font=("Segoe UI", 10, "bold"), anchor="w")
        self.game_lbl.pack(side="left")
        if not is_admin():
            b = tk.Button(banner, text="Restart as admin (enables UDP server detection)", command=self._elevate,
                          bg=CARD, fg=FG, relief="flat", padx=8)
            b.pack(side="right")

        # Cards live in a grid that reflows to fit the window, so there is no scrolling.
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=(12, 4))
        self._layout_key = None

        bar = tk.Frame(self, bg=CARD, padx=12, pady=8)
        bar.pack(fill="x", side="bottom")
        self.name_var, self.host_var = tk.StringVar(), tk.StringVar()
        tk.Label(bar, text="Add target:", bg=CARD, fg=MUTED).pack(side="left")
        for var, width, hint in ((self.name_var, 14, "name"), (self.host_var, 20, "IP / hostname")):
            e = tk.Entry(bar, textvariable=var, width=width, bg=BG, fg=FG, insertbackground=FG, relief="flat")
            e.pack(side="left", padx=4, ipady=3)
            e.bind("<Return>", lambda _e: self._add())
        tk.Button(bar, text="Add", command=self._add, bg=ACCENT, fg="#0b0d10", relief="flat", padx=10).pack(side="left")
        self.interval_var = tk.IntVar(value=self.cfg["interval_ms"])
        tk.Spinbox(bar, from_=100, to=10000, increment=100, width=6, textvariable=self.interval_var,
                   command=self._interval_changed, bg=BG, fg=FG, relief="flat").pack(side="right")
        tk.Label(bar, text="Interval (ms):", bg=CARD, fg=MUTED).pack(side="right", padx=4)

    # --- actions --------------------------------------------------------
    def _add(self):
        host = self.host_var.get().strip()
        if not host:
            return
        name = self.name_var.get().strip() or host
        self.monitor.add(name, host, "custom")
        self.cfg["targets"].append({"name": name, "host": host})
        config.save(self.cfg)
        self.name_var.set("")
        self.host_var.set("")

    def _remove(self, target: Target):
        self.monitor.remove(target)
        if target.kind == "custom":
            self.cfg["targets"] = [t for t in self.cfg["targets"]
                                   if not (t["host"] == target.host and t["name"] == target.name)]
            config.save(self.cfg)

    def _interval_changed(self):
        try:
            self.cfg["interval_ms"] = max(100, int(self.interval_var.get()))
            config.save(self.cfg)
        except (tk.TclError, ValueError):
            pass

    def _elevate(self):
        if getattr(sys, "frozen", False):
            exe, args = sys.executable, ""
        else:
            exe, args = sys.executable, "-m gamers_ping"
        if ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1) > 32:
            self._close()

    def _games(self) -> dict[str, str]:
        games = dict(config.KNOWN_GAMES)
        for exe in self.cfg.get("games", []):
            games.setdefault(exe.lower(), exe)
        return games

    def _on_servers(self, ips: list[str]):
        self.monitor.sync_game(ips)  # called from detector thread; Monitor is thread-safe

    def _close(self):
        self.detector.stop()
        self.monitor.close()
        self.destroy()

    # --- refresh loop ---------------------------------------------------
    def _arrange(self, live: list[Target]):
        """Pick the column count: as many as fit the width, more if rows wouldn't fit the height."""
        n = len(live)
        if not n:
            return
        w, h = max(self.body.winfo_width(), 1), max(self.body.winfo_height(), 1)
        cols = max(1, min(n, w // MIN_CARD_W))
        while cols < n and math.ceil(n / cols) * CARD_H > h:
            cols += 1
        key = (cols, tuple(id(t) for t in live))
        if key == self._layout_key:
            return
        self._layout_key = key
        rows = math.ceil(n / cols)
        for i in range(max(cols, 8)):
            self.body.columnconfigure(i, weight=1 if i < cols else 0)
        for i in range(max(rows, 20)):
            self.body.rowconfigure(i, weight=1 if i < rows else 0)
        for i, t in enumerate(live):
            self.cards[t].grid(row=i // cols, column=i % cols, sticky="nsew", padx=(0, 8), pady=(0, 8))

    def _tick(self):
        live = self.monitor.targets()
        order = {"gateway": 0, "custom": 1, "game": 2}
        live.sort(key=lambda t: order[t.kind])
        for t in list(self.cards):
            if t not in live:
                self.cards.pop(t).destroy()
        for t in live:
            if t not in self.cards:
                self.cards[t] = Card(self.body, t, self._remove)
        self._arrange(live)
        for t in live:
            self.cards[t].refresh(self.cfg["window"])

        d = self.detector
        if d.game is None:
            self.game_lbl.config(text="")
        elif d.mode == "udp":
            self.game_lbl.config(text=f"🎮 {d.game} running – tracking game servers (UDP)", fg=GAME)
        else:
            why = d.sniffer.error or "starting"
            self.game_lbl.config(
                text=f"🎮 {d.game} running – TCP peers only (UDP sniffing off: {why})", fg=WARN)
        self.after(500, self._tick)


def main():
    App().mainloop()
