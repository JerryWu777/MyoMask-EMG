"""Live demo: forehead EMG drives an avatar's expression in real time.

Usage:
  python emg_avatar_demo.py                 live, Arduino on COM4, electrodes on the forehead
  python emg_avatar_demo.py --port COM5
  python emg_avatar_demo.py --sim           no hardware: simulated signal, to check the window
  python emg_avatar_demo.py --replay        replay my recorded forehead EMG (data/forehead_134856.csv)
  python emg_avatar_demo.py --replay other.csv   replay any recording made by emg_site_en.py
Options: --on 2.5 --off 1.25 (score thresholds, hysteresis) --win 1.2 (s) --hold 0.4 (s) --baud 115200
Keys: R = recalibrate rest, S = save log, Esc = quit (also saves the log).
Close the Arduino IDE Serial Monitor / Plotter first so the port is free.

Scoring is the same as emg_site_en.py: (median signal - rest median) / robust rest SD,
here computed live over the last 1.2 s instead of over a whole 4 s action window.
The avatar switches only after the score stays above the threshold for 0.4 s (filters short movement spikes).
"""
import argparse
import collections
import csv
import random
import threading
import time
import tkinter as tk
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "emg_results_en"
DEFAULT_REPLAY = Path(__file__).parent.parent / "data" / "forehead_134856.csv"
# protocol used by emg_site_en.py: rest 5 s, then [action 4 s + rest 4 s] per expression, 2 rounds
CUES = ["Pucker lips", "Squeeze eyes", "Raise eyebrows"]
BASELINE_S, ACTION_S, REST_S, REPS = 5, 4, 4, 2


def cue_at(t):
    """Which expression the voice cue asked for at time t of a recording (None = rest)."""
    if t < BASELINE_S:
        return None
    k, r = divmod(t - BASELINE_S, ACTION_S + REST_S)
    if k >= REPS * len(CUES) or r >= ACTION_S:
        return None
    return CUES[int(k) % len(CUES)]
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
RAISE = "#1baf7a"          # same colour as "Raise eyebrows" in emg_site_en.py
CAL_S, PLOT_S = 5.0, 10.0
FPS = 30


class Source:
    """Background reader that keeps (time, A0) samples, from the Arduino or simulated."""

    def __init__(self, port, baud, sim, replay=None):
        self.samples = collections.deque(maxlen=20000)
        self.raw_log = []
        self.sim = sim
        self.replay = replay
        self.done = False
        self.stop = threading.Event()
        if replay:
            with open(replay, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))[1:]
            self.rec = [(float(t), int(float(v))) for t, v in rows]
        elif not sim:
            import serial
            self.ser = serial.Serial(port, baud, timeout=0.5)
            time.sleep(2.5)  # opening the port resets the Uno; wait for it to boot
            self.ser.reset_input_buffer()
        self.t0 = time.perf_counter()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        if self.replay:  # feed the recording at its original timing
            for t, v in self.rec:
                while time.perf_counter() - self.t0 < t:
                    if self.stop.is_set():
                        return
                    time.sleep(0.002)
                self.samples.append((t, v))
            self.done = True
            return
        while not self.stop.is_set():
            if self.sim:
                time.sleep(1 / 238)
                t = time.perf_counter() - self.t0
                raised = (t % 8) > 5.5 and t > CAL_S + 1  # brows up for 2.5 s every 8 s
                v = 428 + random.gauss(0, 24) + (raised and 120 + random.gauss(0, 60))
                v = int(min(1023, max(0, v)))
            else:
                parts = self.ser.readline().decode(errors="ignore").strip().split(",")
                try:
                    v = int(parts[0])
                except (ValueError, IndexError):
                    continue
                t = time.perf_counter() - self.t0
            self.samples.append((t, v))
            self.raw_log.append((t, v))

    def window(self, t_from):
        return np.array([v for t, v in list(self.samples) if t >= t_from], dtype=float)

    def close(self):
        self.stop.set()
        if not self.sim and not self.replay:
            self.ser.close()


class Demo:
    def __init__(self, src, on, off, win, hold):
        self.src, self.on, self.off, self.win, self.hold = src, on, off, win, hold
        self.since = None                    # wall time the score first went above the threshold
        self.root = tk.Tk()
        self.root.title("PSiFi Mask · live facial EMG → avatar")
        self.root.configure(bg=SURFACE)
        self.chart = tk.Canvas(self.root, width=620, height=440, bg=SURFACE, highlightthickness=0)
        self.face = tk.Canvas(self.root, width=440, height=440, bg=SURFACE, highlightthickness=0)
        head = tk.Label(self.root, text="Forehead EMG  →  avatar expression", font=("Segoe UI", 16, "bold"),
                        fg=INK, bg=SURFACE, anchor="w")
        self.status = tk.Label(self.root, text="", font=("Segoe UI", 11), fg=INK2, bg=SURFACE, anchor="w")
        mode = ("REPLAY of my recorded forehead EMG  ·  " + Path(src.replay).name + "  ·  " if src.replay
                else "SIMULATED SIGNAL  ·  " if src.sim else "LIVE  ·  ")
        foot = tk.Label(self.root, text=mode + "R recalibrate  ·  S save log  ·  Esc quit",
                        font=("Segoe UI", 9), fg=MUTED, bg=SURFACE)
        head.grid(row=0, column=0, columnspan=2, sticky="w", padx=24, pady=(18, 0))
        self.status.grid(row=1, column=0, columnspan=2, sticky="w", padx=24)
        self.chart.grid(row=2, column=0, padx=(24, 8), pady=12)
        self.face.grid(row=2, column=1, padx=(8, 24), pady=12)
        foot.grid(row=3, column=0, columnspan=2, pady=(0, 12))
        self.root.bind("<Escape>", lambda e: self.quit())
        self.root.bind("r", lambda e: self.calibrate())
        self.root.bind("s", lambda e: self.save())
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.history = collections.deque()   # (t, score)
        self.events = []                     # (t, score, state)
        self.level, self.up, self.count = 0.0, False, 0
        self.calibrate()

    # ---------- signal ----------
    def calibrate(self):
        self.cal_until = time.perf_counter() - self.src.t0 + CAL_S
        self.r_med = None

    def score(self, now):
        if self.r_med is None:
            if now < self.cal_until:
                return None
            rest = self.src.window(self.cal_until - CAL_S + 0.8)
            rest = rest[(rest > 2) & (rest < 1020)]
            if len(rest) < 50:
                return None
            self.r_med = float(np.median(rest))
            self.r_sd = float(np.median(np.abs(rest - self.r_med)) * 1.4826 + 1e-6)
        w = self.src.window(now - self.win)
        w = w[(w > 2) & (w < 1020)]
        if len(w) < 10:
            return None
        return (float(np.median(w)) - self.r_med) / self.r_sd

    # ---------- loop ----------
    def tick(self):
        now = time.perf_counter() - self.src.t0
        s = self.score(now)
        if s is None and self.src.replay and self.src.done:
            self.status.config(text=f"Replay finished  ·  triggered: {self.count}  ·  Esc to quit")
        elif s is None:
            left = max(0.0, self.cal_until - now)
            self.status.config(text=f"Calibrating rest… keep your face relaxed ({left:.1f} s)")
        else:
            self.since = (self.since if self.since is not None else now) if s > self.on else None
            if not self.up and self.since is not None and now - self.since >= self.hold:
                self.up, self.count = True, self.count + 1
            elif self.up and s < self.off:
                self.up = False
            self.level += 0.35 * (min(1.0, max(0.0, s / (self.on * 1.6))) - self.level)
            self.history.append((now, s))
            self.events.append((round(now, 3), round(s, 2), "surprised" if self.up else "neutral"))
            cue = ""
            if self.src.replay:
                cue = "   ·   recorded cue: " + (cue_at(now) or "rest")
                if self.src.done:
                    cue = "   ·   replay finished (Esc to quit)"
            self.status.config(text=f"Rest {self.r_med:.0f} ± {self.r_sd:.0f} ADC   ·   score {s:+.1f}   ·   "
                                    f"threshold {self.on:+.1f}   ·   triggered: {self.count}{cue}")
        while self.history and self.history[0][0] < now - PLOT_S:
            self.history.popleft()
        self.draw_chart(now)
        self.draw_face()
        self.root.after(int(1000 / FPS), self.tick)

    # ---------- drawing ----------
    def draw_chart(self, now):
        c, W, H, L, T, B = self.chart, 620, 440, 48, 20, 400
        c.delete("all")
        lo, hi = -2.0, 8.0
        y = lambda v: B - (min(hi, max(lo, v)) - lo) / (hi - lo) * (B - T)
        x = lambda t: L + (t - (now - PLOT_S)) / PLOT_S * (W - L - 10)
        if self.src.replay:  # shade the windows where the recording asked for "Raise eyebrows"
            t = max(0.0, now - PLOT_S)
            while t < now:
                if cue_at(t) == "Raise eyebrows":
                    s0 = t
                    while t < now and cue_at(t) == "Raise eyebrows":
                        t += 0.05
                    c.create_rectangle(x(s0), T, x(t), B, fill="#e3f4ec", outline="")
                t += 0.05
        for v in range(-2, 9, 2):
            c.create_line(L, y(v), W - 10, y(v), fill=GRID)
            c.create_text(L - 8, y(v), text=f"{v:+d}" if v else "0", anchor="e", fill=MUTED, font=("Segoe UI", 9))
        c.create_line(L, y(self.on), W - 10, y(self.on), fill=RAISE, dash=(6, 4), width=2)
        c.create_text(W - 12, y(self.on) - 10, text="trigger", anchor="e", fill=RAISE, font=("Segoe UI", 9, "bold"))
        pts = [p for t, s in self.history for p in (x(t), y(s))]
        if len(pts) >= 4:
            c.create_line(*pts, fill=INK, width=2, smooth=True)
        c.create_text(L, B + 22, text=f"Activation score, last 10 s  ({self.win:g} s window, {self.hold:g} s hold)", anchor="w",
                      fill=INK2, font=("Segoe UI", 10))

    def draw_face(self):
        c, k = self.face, self.level
        c.delete("all")
        cx, cy = 220, 230
        c.create_oval(30, 30, 410, 410, fill="#eef6f1" if self.up else "#f1f0ec", outline="")
        # ears, head, hair
        for sx in (-1, 1):
            c.create_oval(cx + sx * 112 - 16, cy - 10, cx + sx * 112 + 16, cy + 40, fill="white", outline=INK, width=3)
        c.create_oval(cx - 110, cy - 130, cx + 110, cy + 140, fill="white", outline=INK, width=3)
        hair = [cx - 122, cy - 20, cx - 128, cy - 110, cx - 80, cy - 170, cx - 20, cy - 186, cx + 40, cy - 182,
                cx + 100, cy - 150, cx + 128, cy - 80, cx + 120, cy - 18, cx + 92, cy - 78, cx + 54, cy - 60,
                cx + 30, cy - 96, cx - 10, cy - 62, cx - 40, cy - 98, cx - 70, cy - 60, cx - 96, cy - 84]
        c.create_polygon(hair, fill="white", outline=INK, width=3, smooth=True)
        # brows rise and arch with the score
        lift, arch = 26 * k, 4 + 10 * k
        for sx in (-1, 1):
            bx = cx + sx * 50
            by = cy - 22 - lift
            c.create_line(bx - 26, by + 6, bx, by - arch, bx + 26, by + 6, smooth=True, width=5, fill=INK, capstyle="round")
        # eyes open wider
        eh = 10 + 14 * k
        for sx in (-1, 1):
            ex = cx + sx * 50
            c.create_oval(ex - 15, cy + 22 - eh, ex + 15, cy + 22 + eh, fill="white", outline=INK, width=3)
            c.create_oval(ex - 6, cy + 22 - 6, ex + 6, cy + 22 + 6, fill=INK, outline="")
        # mouth: soft smile -> open "o"
        my = cy + 92
        if k < 0.3:
            c.create_line(cx - 26, my - 4, cx, my + 6, cx + 26, my - 4, smooth=True, width=4, fill=INK, capstyle="round")
        else:
            h = 8 + 26 * k
            c.create_oval(cx - 16 - 6 * k, my - h / 2, cx + 16 + 6 * k, my + h / 2, fill="#3a2a2a", outline=INK, width=3)
        label = "Surprised" if self.up else "Neutral"
        c.create_text(cx, 400, text=label, fill=RAISE if self.up else INK2, font=("Segoe UI", 15, "bold"))

    # ---------- output ----------
    def save(self):
        OUT.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        tag = "replay" if self.src.replay else "sim" if self.src.sim else "live"
        with open(OUT / f"avatar_demo_{tag}_{stamp}_scores.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "score", "avatar"])
            w.writerows(self.events)
        with open(OUT / f"avatar_demo_{tag}_{stamp}_raw.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "A0"])
            w.writerows(list(self.src.raw_log))
        print(f"Log saved in {OUT}  (triggered {self.count} times)")

    def quit(self):
        if self.events:
            self.save()
        self.src.close()
        self.root.destroy()

    def run(self):
        self.root.after(200, self.tick)
        self.root.mainloop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM4")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--on", type=float, default=2.5, help="score that triggers the expression")
    ap.add_argument("--off", type=float, default=1.25, help="score that releases it")
    ap.add_argument("--win", type=float, default=1.2, help="seconds of signal per score")
    ap.add_argument("--hold", type=float, default=0.4, help="seconds above threshold before switching")
    ap.add_argument("--sim", action="store_true", help="simulated signal, no Arduino needed")
    ap.add_argument("--replay", nargs="?", const=str(DEFAULT_REPLAY), default=None,
                    help="replay a recorded CSV (default: my forehead recording)")
    args = ap.parse_args()
    Demo(Source(args.port, args.baud, args.sim, args.replay), args.on, args.off, args.win, args.hold).run()
