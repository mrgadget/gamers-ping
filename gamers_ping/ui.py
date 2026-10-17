"""tkinter front-end: custom-drawn dark UI (rounded cards, filled graphs, status pills)."""
import ctypes
import math
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

from . import __version__, config, updater
from .gamedetect import GameDetector
from .monitor import Monitor, Target, compute_stats
from .netinfo import is_admin

# --- palette ------------------------------------------------------------
BG, SURF, SURF2, GRAPH = "#0a0d14", "#111622", "#182032", "#0d121c"
BORDER, GRID = "#1d2536", "#1a2232"
FG, MUTED, DIM = "#e8ecf4", "#8a93a8", "#4d576c"
GOOD, WARN, BAD, ACCENT, GAME = "#34d399", "#fbbf24", "#f87171", "#38bdf8", "#a78bfa"

SCALE = 1.0  # set from the display DPI in App.__init__
FONTS: dict[str, tkfont.Font] = {}


def px(n: float) -> int:
    return int(round(n * SCALE))


def blend(a: str, b: str, t: float) -> str:
    """Colour a mixed with b (t = share of a)."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02x}" for x, y in zip(ca, cb))


def status(values: list, last) -> tuple[str, str]:
    """-> (label, colour) for the newest sample."""
    if not values:
        return "STARTING", MUTED
    if last is None:
        return "NO REPLY", BAD
    if last < 30:
        return "EXCELLENT", GOOD
    if last < 60:
        return "GOOD", GOOD
    if last < 100:
        return "FAIR", WARN
    return "POOR", BAD


def fmt(v, digits=0) -> str:
    return "–" if v is None else f"{v:.{digits}f}"


def rrect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def clip_run(run, xl, xr):
    """Clip a left-to-right polyline of (x, y, value) to xl..xr, interpolating at the cut edges."""
    if len(run) == 1:
        return run if xl <= run[0][0] <= xr else []
    out = []
    for a, b in zip(run, run[1:]):
        if b[0] < xl or a[0] > xr or b[0] == a[0]:
            continue

        def at(x, a=a, b=b):
            f = (x - a[0]) / (b[0] - a[0])
            return (x, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)

        p = a if a[0] >= xl else at(xl)
        q = b if b[0] <= xr else at(xr)
        if not out or out[-1] != p:
            out.append(p)
        out.append(q)
    return out


def make_fonts(root: tk.Tk) -> None:
    fams = set(tkfont.families(root))
    fam = next((f for f in ("Segoe UI Variable Display", "Segoe UI") if f in fams), "TkDefaultFont")

    def f(size, weight="normal"):
        return tkfont.Font(root=root, family=fam, size=-px(size), weight=weight)

    FONTS.update(name=f(15, "bold"), host=f(12), big=f(40, "bold"), unit=f(14), big2=f(54, "bold"), unit2=f(18), big3=f(70, "bold"), unit3=f(22), tag=f(10, "bold"),
                 cap=f(10, "bold"), val=f(13, "bold"), tiny=f(10), ui=f(13), ui_b=f(13, "bold"))


class Card(tk.Canvas):
    """One target: header, live readout + status pill, filled graph, stats footer."""

    def __init__(self, parent, target: Target, on_remove):
        super().__init__(parent, bg=BG, highlightthickness=0, width=px(100), height=px(140))
        self.target, self.on_remove = target, on_remove
        self.hover = False
        self._last = (120, 0, 1.0)
        self.window, self.interval = 120, 1.0
        self._geo: dict | None = None
        self._ymax = 60.0
        self.removable = target.kind in ("custom", "game")
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Motion>", self._motion)
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda _e: self.draw())

    def _set_hover(self, on: bool):
        self.hover = on
        self.draw()

    def _on_x(self, e) -> bool:
        return self.removable and e.x > self.winfo_width() - px(44) and e.y < px(44)

    def _motion(self, e):
        self.config(cursor="hand2" if self._on_x(e) else "")

    def _click(self, e):
        if self._on_x(e):
            self.on_remove(self.target)

    def draw(self, window=None, phase=0, interval=None):
        if window is None:
            window, phase, interval = self._last
        self._last = (window, phase, interval)
        self.window, self.interval = window, interval
        c, t = self, self.target
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < px(80) or h < px(60):
            return
        values = t.recent(window)
        st = compute_stats(values)
        last = st["last"]
        label, col = status(values, last)
        is_game = t.kind == "game"
        accent = GAME if is_game else col

        # card surface
        edge = blend(GAME, BORDER, 0.35) if is_game else BORDER
        if self.hover:
            edge = blend(FG, edge, 0.25)
        rrect(c, 1, 1, w - 1, h - 1, px(14), fill=SURF, outline=edge)

        # header: status dot, name, host
        cy = px(24)
        pulse = (math.sin(phase * 0.9) + 1) / 2 if is_game else 0
        if is_game:
            r = px(4 + 4 * pulse)
            c.create_oval(px(22) - r, cy - r, px(22) + r, cy + r, fill=blend(GAME, SURF, 0.25 * (1 - pulse) + 0.1), outline="")
        c.create_oval(px(22) - px(4), cy - px(4), px(22) + px(4), cy + px(4), fill=accent, outline="")
        nx = px(36)
        c.create_text(nx, cy, text=t.name, anchor="w", fill=FG, font=FONTS["name"])
        nx += FONTS["name"].measure(t.name) + px(10)
        c.create_text(nx, cy + px(1), text=t.host or "no gateway found", anchor="w", fill=MUTED, font=FONTS["host"])
        tag = {"gateway": "GATEWAY", "game": "GAME SERVER"}.get(t.kind, "")
        if self.hover and self.removable:
            c.create_text(w - px(20), cy, text="✕", fill=MUTED, font=FONTS["ui_b"])
        elif tag:
            c.create_text(w - px(18), cy, text=tag, anchor="e", fill=GAME if is_game else DIM, font=FONTS["tag"])
        top = px(46)
        if t.via:
            # We never learn the true hop count (the server is silent), only how far back from the
            # farthest answering router we are, so this is a lower bound.
            away = max(1, (t.far_hop or t.via_hop) - t.via_hop + 1)
            c.create_text(px(22), px(43), anchor="w", fill=WARN, font=FONTS["tiny"],
                          text=f"Server blocks ping – router ≥{away} hop(s) from target ({t.via})")
            top = px(58)

        # geometry
        foot_y = h - px(19)
        gb = h - px(36)
        lw = px(124) if w >= px(340) else px(96)
        if h > px(170) and w >= px(420):
            lw = px(176)
        gx1, gx2 = px(16) + lw, w - px(16)

        # left: readout + pill
        mid = (top + gb) / 2
        roomy = gb - top >= px(56)
        ny = mid - px(12) if roomy else mid
        size = "3" if gb - top > px(260) else "2" if gb - top > px(170) else ""
        fbig, funit = FONTS["big" + size], FONTS["unit" + size]
        if size:
            ny = mid - px(16 if size == "2" else 24)
        if last is None:
            c.create_text(px(18), ny, text="–" if not values else "×", anchor="w", fill=col, font=fbig)
        else:
            num = f"{last:.0f}"
            c.create_text(px(18), ny, text=num, anchor="w", fill=FG, font=fbig)
            c.create_text(px(18) + fbig.measure(num) + px(4), ny + fbig.metrics("linespace") * 0.2, text="ms", anchor="w",
                          fill=MUTED, font=funit)
        if roomy:
            py = mid + px(24 if not size else 34 if size == "2" else 48)
            pw = FONTS["tag"].measure(label) + px(18)
            rrect(c, px(18), py - px(10), px(18) + pw, py + px(10), px(10), fill=blend(col, SURF, 0.16), outline="")
            c.create_text(px(18) + pw / 2, py, text=label, fill=col, font=FONTS["tag"])

        # graph backdrop (the moving plot is drawn by plot(), ~30 fps)
        rrect(c, gx1, top, gx2, gb, px(10), fill=GRAPH, outline="")
        self._geo = dict(x0=gx1 + px(8), x1=gx2 - px(8), y0=top + px(10), y1=gb - px(10),
                         accent=accent, col=col)
        self.plot()

        # footer stats
        cells = [("AVG", fmt(st["avg"]), FG), ("MIN", fmt(st["min"]), FG), ("MAX", fmt(st["max"]), FG),
                 ("JITTER", fmt(st["jitter"], 1), WARN if (st["jitter"] or 0) > 15 else FG),
                 ("LOSS", f"{st['loss']:.1f}%", BAD if st["loss"] > 2 else WARN if st["loss"] > 0 else GOOD)]
        if w < px(400):
            cells.pop(1)
        cw = (w - px(36)) / len(cells)
        for i, (cap, val, vcol) in enumerate(cells):
            x = px(18) + i * cw
            c.create_text(x, foot_y, text=cap, anchor="w", fill=DIM, font=FONTS["cap"])
            c.create_text(x + FONTS["cap"].measure(cap) + px(6), foot_y, text=val, anchor="w", fill=vcol, font=FONTS["val"])

    def plot(self, now: float | None = None, ease: bool = False):
        """Draw the scrolling graph from timestamps, so it glides instead of stepping.

        The right edge shows time `now - interval`: the newest sample is always already
        in hand and the final segment slides in from the edge.
        """
        g = self._geo
        if not g:
            return
        c = self
        c.delete("g")
        now = now or time.time()
        x0, x1, y0, y1, accent, col = g["x0"], g["x1"], g["y0"], g["y1"], g["accent"], g["col"]
        interval = max(self.interval, 0.05)
        span = max(self.window - 1, 1) * interval
        edge = now - interval
        pps = (x1 - x0) / span

        pts: list[tuple[float, float | None]] = []
        cutoff = edge - span - interval
        for ts, v in reversed(self.target.samples):
            if ts < cutoff:
                break
            pts.append((ts, v))
        pts.reverse()
        ok = [v for _, v in pts if v is not None]
        want = max(60.0, (max(ok) if ok else 0) * 1.2)
        self._ymax += (want - self._ymax) * (0.12 if ease else 1.0)
        ymax = self._ymax

        def Y(ms):
            return y1 - (y1 - y0) * min(ms, ymax) / ymax

        for ms in (50, 100, 200, 400):
            if ms < ymax * 0.97:
                c.create_line(x0, Y(ms), x1, Y(ms), fill=GRID, dash=(2, 5), tags="g")
                c.create_text(x0, Y(ms) - px(7), text=f"{ms}", anchor="w", fill=DIM, font=FONTS["tiny"], tags="g")

        runs: list[list[tuple[float, float, float]]] = []
        cur: list[tuple[float, float, float]] = []
        for ts, v in pts:
            x = x1 - (edge - ts) * pps
            if v is None:
                if cur:
                    runs.append(cur)
                cur = []
                if x0 <= x <= x1:
                    c.create_rectangle(x - px(1), y0 - px(4), x + px(1), y1 + px(4),
                                       fill=blend(BAD, GRAPH, 0.7), outline="", tags="g")
            else:
                cur.append((x, Y(v), v))
        if cur:
            runs.append(cur)
        runs = [r for r in (clip_run(r, x0, x1) for r in runs) if r]
        for run in runs:
            if len(run) > 1:  # soft area fill under the line
                flat = [p for x, y, _ in run for p in (x, y)]
                c.create_polygon(*flat, run[-1][0], y1 + px(10), run[0][0], y1 + px(10),
                                 fill=blend(accent, GRAPH, 0.13), outline="", tags="g")
        for run in runs:
            seg = [run[0]]
            for p in run[1:]:
                seg.append(p)
                if status([1], p[2])[1] != status([1], seg[0][2])[1] or len(seg) > 40:
                    self._line(seg)
                    seg = [p]
            self._line(seg)
        if runs and pts and pts[-1][1] is not None and abs(runs[-1][-1][0] - x1) < px(2):
            lx, ly, _ = runs[-1][-1]
            c.create_oval(lx - px(6), ly - px(6), lx + px(6), ly + px(6), fill=blend(col, GRAPH, 0.28),
                          outline="", tags="g")
            c.create_oval(lx - px(3), ly - px(3), lx + px(3), ly + px(3), fill=col, outline="", tags="g")

    def _line(self, seg):
        if len(seg) == 1:
            x, y, ms = seg[0]
            self.create_oval(x - px(1.5), y - px(1.5), x + px(1.5), y + px(1.5), fill=status([1], ms)[1],
                             outline="", tags="g")
            return
        flat = [p for x, y, _ in seg for p in (x, y)]
        self.create_line(*flat, fill=status([1], seg[-1][2])[1], width=px(2), capstyle="round",
                         joinstyle="round", tags="g")


class FlatButton(tk.Label):
    def __init__(self, parent, text, command, bg=SURF2, fg=FG, hover=None, font=None, padx=14, pady=6):
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font or FONTS["ui_b"], padx=px(padx), pady=px(pady),
                         cursor="hand2")
        hover = hover or blend(FG, bg, 0.12)
        self.bind("<Enter>", lambda _e: self.config(bg=hover))
        self.bind("<Leave>", lambda _e: self.config(bg=bg))
        self.bind("<Button-1>", lambda _e: command())


class HintEntry(tk.Entry):
    def __init__(self, parent, hint, width, on_return):
        super().__init__(parent, width=width, bg=SURF2, fg=DIM, insertbackground=FG, relief="flat",
                         font=FONTS["ui"], highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        self.hint, self.showing = hint, False
        self.bind("<FocusIn>", self._in)
        self.bind("<FocusOut>", self._out)
        self.bind("<Return>", lambda _e: on_return())
        self._out()

    def _in(self, _e=None):
        if self.showing:
            self.delete(0, "end")
            self.config(fg=FG)
            self.showing = False

    def _out(self, _e=None):
        if not self.get():
            self.insert(0, self.hint)
            self.config(fg=DIM)
            self.showing = True

    def value(self) -> str:
        return "" if self.showing else self.get().strip()

    def clear(self):
        self.delete(0, "end")
        self.showing = False
        if self.focus_get() is not self:
            self._out()


class App(tk.Tk):
    def __init__(self):
        global SCALE
        super().__init__()
        SCALE = max(1.0, self.winfo_fpixels("1i") / 96.0)
        make_fonts(self)
        self.title("Gamers Ping")
        self.configure(bg=BG)
        self.geometry(f"{px(1000)}x{px(620)}")
        self.minsize(px(480), px(360))
        self.cfg = config.load()
        self.monitor = Monitor(self.cfg)
        for t in self.cfg["targets"]:
            self.monitor.add(t["name"], t["host"], "custom")
        self.detector = GameDetector(self._games(), self._on_servers)
        self.detector.start()
        self.cards: dict[Target, Card] = {}
        self._frame = 0
        self._updated_to: str | None = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self._style_titlebar)
        self.after(300, self._tick)
        self.after(300, self._animate)
        updater.cleanup_old()
        if self.cfg.get("auto_update", True) and updater.can_self_update():
            threading.Thread(target=self._update_loop, daemon=True).start()

    def _style_titlebar(self):
        """Dark caption bar on Windows 10 20H1+/11."""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            dwm = ctypes.windll.dwmapi
            one = ctypes.c_int(1)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(one), 4)
            rgb = int(BG[1:3], 16) | int(BG[3:5], 16) << 8 | int(BG[5:7], 16) << 16
            for attr in (34, 35):  # border / caption colour (Windows 11)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ctypes.c_int(rgb)), 4)
        except (AttributeError, OSError):
            pass

    # --- layout ---------------------------------------------------------
    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=px(16), pady=(px(10), px(2)))
        self.update_btn = FlatButton(top, "", self._restart_for_update, bg=ACCENT, fg="#06121c",
                                     hover=blend("#ffffff", ACCENT, 0.2), font=FONTS["ui_b"], padx=12, pady=4)
        self.chip = tk.Label(top, bg=BG, fg=GAME, font=FONTS["ui_b"], padx=px(12), pady=px(4))
        if not is_admin():
            FlatButton(top, "Run as admin for UDP game-server detection", self._elevate, bg=SURF, fg=MUTED,
                       font=FONTS["tiny"], padx=12, pady=4).pack(side="right")

        # Cards live in a grid that reflows to fit the window, so there is no scrolling.
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=(px(16), px(6)), pady=(px(6), 0))
        self._layout_key = None

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="x", side="bottom", padx=px(16), pady=(px(4), px(14)))
        bar = tk.Frame(outer, bg=SURF, highlightthickness=1, highlightbackground=BORDER, padx=px(10), pady=px(8))
        bar.pack(fill="x")
        self.name_in = HintEntry(bar, "Name", 14, self._add)
        self.host_in = HintEntry(bar, "IP or hostname", 22, self._add)
        self.name_in.pack(side="left", ipady=px(4))
        self.host_in.pack(side="left", padx=px(8), ipady=px(4))
        FlatButton(bar, "+  Add target", self._add, bg=ACCENT, fg="#06121c", hover=blend("#ffffff", ACCENT, 0.2)).pack(side="left")

        tk.Label(bar, text=f"v{__version__}", bg=SURF, fg=DIM, font=FONTS["tiny"]).pack(side="left", padx=(px(14), 0))
        self.interval_lbl = tk.Label(bar, bg=SURF, fg=FG, font=FONTS["ui_b"], width=8)
        FlatButton(bar, "+", lambda: self._step(+1), padx=10, pady=3).pack(side="right")
        self.interval_lbl.pack(side="right")
        FlatButton(bar, "–", lambda: self._step(-1), padx=10, pady=3).pack(side="right")
        tk.Label(bar, text="PING EVERY", bg=SURF, fg=DIM, font=FONTS["cap"]).pack(side="right", padx=(0, px(10)))
        self._show_interval()

    # --- actions --------------------------------------------------------
    def _add(self):
        host = self.host_in.value()
        if not host:
            return
        name = self.name_in.value() or host
        self.monitor.add(name, host, "custom")
        self.cfg["targets"].append({"name": name, "host": host})
        config.save(self.cfg)
        self.name_in.clear()
        self.host_in.clear()

    def _remove(self, target: Target):
        self.monitor.remove(target)
        if target.kind == "custom":
            self.cfg["targets"] = [t for t in self.cfg["targets"]
                                   if not (t["host"] == target.host and t["name"] == target.name)]
            config.save(self.cfg)

    def _step(self, direction: int):
        ms = self.cfg["interval_ms"]
        inc = 100 if (ms < 1000 or (ms == 1000 and direction < 0)) else 250
        self.cfg["interval_ms"] = max(100, min(10000, ms + direction * inc))
        config.save(self.cfg)
        self._show_interval()

    def _show_interval(self):
        self.interval_lbl.config(text=f"{self.cfg['interval_ms']} ms")

    def _elevate(self):
        if getattr(sys, "frozen", False):
            exe, args = sys.executable, ""
        else:
            exe, args = sys.executable, "-m gamers_ping"
        if ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1) > 32:
            self._close()

    def _update_loop(self):
        while True:
            try:
                ver = updater.update_if_available()
                if ver:
                    self._updated_to = ver
                    return
            except Exception:  # offline, rate-limited, read-only install dir... try again later
                pass
            time.sleep(6 * 3600)

    def _restart_for_update(self):
        updater.restart()
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
        """Tile the cards to fill the whole workspace.

        Picks the column count whose tiles are closest to a comfortable wide shape without
        getting too small; a short last row has its final card stretched across the gap.
        """
        n = len(live)
        if not n:
            return
        gap = px(10)
        w, h = max(self.body.winfo_width(), 1), max(self.body.winfo_height(), 1)
        min_w, min_h = px(340), px(136)
        best = None
        for cols in range(1, n + 1):
            rows = math.ceil(n / cols)
            tw, th = (w - gap * cols) / cols, (h - gap * rows) / rows
            too_small = (tw < min_w) + (th < min_h)
            score = too_small * 10 + abs(math.log((tw / max(th, 1)) / 2.4)) + 0.15 * (cols * rows - n)
            if best is None or score < best[0]:
                best = (score, cols, rows)
        _, cols, rows = best
        key = (cols, tuple(id(t) for t in live))
        if key == self._layout_key:
            return
        self._layout_key = key
        for i in range(max(cols, 12)):
            self.body.columnconfigure(i, weight=1 if i < cols else 0, uniform="col" if i < cols else "")
        for i in range(max(rows, 40)):
            self.body.rowconfigure(i, weight=1 if i < rows else 0, uniform="row" if i < rows else "")
        for i, t in enumerate(live):
            col = i % cols
            span = cols - col if i == n - 1 else 1  # last card absorbs the empty cells in its row
            self.cards[t].grid(row=i // cols, column=col, columnspan=span, sticky="nsew",
                               padx=(0, gap), pady=(0, gap))

    def _animate(self):
        """~30 fps: slide every graph along with the clock."""
        t0 = time.perf_counter()
        now = time.time()
        for card in self.cards.values():
            card.plot(now, ease=True)
        self.after(max(5, 33 - int((time.perf_counter() - t0) * 1000)), self._animate)

    def _tick(self):
        self._frame += 1
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
            self.cards[t].draw(self.cfg["window"], self._frame, self.cfg["interval_ms"] / 1000)

        if self._updated_to and not self.update_btn.winfo_ismapped():
            self.update_btn.config(text=f"⬆  v{self._updated_to} installed – restart to apply")
            self.update_btn.pack(side="left", padx=(0, px(10)))

        d = self.detector
        if d.game is None:
            self.chip.pack_forget()
        else:
            if d.mode == "udp":
                text, col = f"●  {d.game}  ·  tracking servers", GAME
            else:
                text, col = f"●  {d.game}  ·  TCP peers only ({d.sniffer.error or 'starting'})", WARN
            self.chip.config(text=text, fg=col, bg=blend(col, BG, 0.14))
            self.chip.pack(side="left")
        self.after(500, self._tick)


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text/graphs on high-DPI displays
    except (AttributeError, OSError):
        pass
    App().mainloop()
