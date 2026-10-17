"""Single-channel facial EMG: test one site at a time with voice-cued expressions.

Usage:
  python emg_site_en.py forehead      record one site (forehead / eye / mouth)
  python emg_site_en.py compare       compare the latest recording of every site
Options: --port COM4 --reps 2 --baud 115200
Close the Arduino IDE Serial Monitor / Plotter first so the port is free.
"""
import argparse
import csv
import subprocess
import threading
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SITES = {"forehead": "Frontalis", "eye": "Orbicularis oculi", "mouth": "Orbicularis oris"}
SITE_TITLES = {"forehead": "Forehead", "eye": "Eye corner", "mouth": "Mouth corner"}
ACTIONS = [("Pucker lips", "#2a78d6"), ("Squeeze eyes", "#eb6834"), ("Raise eyebrows", "#1baf7a")]
BASELINE_S, ACTION_S, REST_S = 5, 4, 4
OUT = Path(__file__).parent / "emg_results_en"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
plt.rcParams.update({
    "font.family": "Segoe UI", "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})


class Speaker:
    """One long-lived PowerShell process for English voice cues (no per-cue startup lag)."""

    def __init__(self):
        ps = (
            "[Console]::InputEncoding=[Text.Encoding]::UTF8;"
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "try{$s.SelectVoiceByHints('Female',0,0,[Globalization.CultureInfo]'en-US')}catch{};"
            "$s.Rate=1;"
            "while(($l=[Console]::In.ReadLine()) -ne $null){$s.Speak($l)}"
        )
        self.p = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def say(self, text):
        self.p.stdin.write((text + "\n").encode("utf-8"))
        self.p.stdin.flush()

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=15)


def build_schedule(reps):
    """Rest 5 s, then [action 4 s + rest 4 s] for each expression, repeated `reps` times."""
    sched = [(0, BASELINE_S, None)]
    t = BASELINE_S
    for _ in range(reps):
        for i in range(len(ACTIONS)):
            sched += [(t, t + ACTION_S, i), (t + ACTION_S, t + ACTION_S + REST_S, None)]
            t += ACTION_S + REST_S
    return sched, t


def smooth(x, n):
    """Median filter removes 0/1023 spikes, then a moving average."""
    if n < 3:
        return x
    pad = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")
    med = np.median(np.lib.stride_tricks.sliding_window_view(pad, n), axis=1)
    return np.convolve(med, np.ones(n) / n, mode="same")


def analyze(t, a0, sched):
    """Activation score per expression: (median during action - rest median) / robust rest SD."""
    ok = (a0 > 2) & (a0 < 1020)

    def mask(s, e):
        return (t >= s + 0.8) & (t < e) & ok  # skip 0.8 s reaction time

    rest = np.any([mask(s, e) for s, e, i in sched if i is None], axis=0)
    r_med = np.median(a0[rest])
    r_sd = np.median(np.abs(a0[rest] - r_med)) * 1.4826 + 1e-6
    res = []
    for k in range(len(ACTIONS)):
        m = np.any([mask(s, e) for s, e, i in sched if i == k], axis=0)
        res.append(((np.median(a0[m]) - r_med) / r_sd, np.percentile(a0[m], 90)))
    return r_med, r_sd, res, 1 - ok.mean()


def plot_site(ax, t, a0, sched, site, res):
    for s, e, i in sched:
        if i is not None:
            ax.axvspan(s, e, color=ACTIONS[i][1], alpha=0.13, lw=0)
    fs = len(t) / (t[-1] - t[0])
    ax.plot(t, a0, color="#d6d5cf", lw=0.6)
    ax.plot(t, smooth(a0, max(3, int(fs * 0.15))), color=INK, lw=1.2)
    ax.set_ylim(-20, 1043)
    ax.set_xlim(0, t[-1])
    ax.set_ylabel("A0 (ADC)", fontsize=9)
    ax.set_title(f"{SITE_TITLES[site]}  ·  {SITES[site]}", loc="left", fontsize=11.5, color=INK, pad=8)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    score = "     ".join(f"{ACTIONS[k][0]}  {res[k][0]:+.1f}" for k in range(len(ACTIONS)))
    ax.text(1.0, 1.02, "Activation score:   " + score, transform=ax.transAxes,
            ha="right", va="bottom", fontsize=9, color=INK2)


def action_legend(fig):
    handles = [plt.Rectangle((0, 0), 1, 1, color=c, alpha=0.35, lw=0) for _, c in ACTIONS]
    handles += [plt.Line2D([], [], color=INK, lw=1.2), plt.Line2D([], [], color="#d6d5cf", lw=1.2)]
    labels = [a for a, _ in ACTIONS] + ["Smoothed", "Raw"]
    fig.legend(handles, labels, loc="lower center", ncol=5, frameon=False, fontsize=9,
               labelcolor=INK2, bbox_to_anchor=(0.5, 0.0))


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))[1:]
    d = np.array(rows, dtype=float)
    return d[:, 0], d[:, 1]


def site_figure(site, t, a0, sched, res, png):
    fig, ax = plt.subplots(figsize=(13, 4.0))
    plot_site(ax, t, a0, sched, site, res)
    ax.set_xlabel("Time (s)", fontsize=9)
    fig.suptitle("Facial EMG - single-site test", x=0.01, ha="left", fontsize=13, color=INK, weight="bold")
    action_legend(fig)
    fig.tight_layout(rect=(0, 0.07, 1, 0.97))
    fig.savefig(png, dpi=160)
    plt.close(fig)


def summary_figure(scores, png):
    """Grouped bars: activation score of every expression at every site."""
    sites = list(scores)
    x = np.arange(len(sites))
    w = 0.26
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for k, (name, col) in enumerate(ACTIONS):
        vals = [scores[s][k] for s in sites]
        ax.bar(x + (k - 1) * w, vals, w - 0.02, color=col, label=name, zorder=2)
    for i, s in enumerate(sites):
        top = max(scores[s])
        for k, v in enumerate(scores[s]):
            if v >= top - 0.05:  # label the strongest expression (ties included)
                ax.text(x[i] + (k - 1) * w, v + 0.12, f"{v:+.1f}", ha="center", va="bottom",
                        fontsize=9.5, color=INK, weight="bold")
    ax.axhline(0, color="#c3c2b7", lw=1, zorder=3)
    ax.set_xticks(x, [f"{SITE_TITLES[s]}\n{SITES[s]}" for s in sites], fontsize=10, color=INK2)
    ax.set_ylabel("Activation score (vs. rest)", fontsize=9.5)
    ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9.5, labelcolor=INK2, loc="upper right")
    fig.suptitle("Which expression activates each site?", x=0.01, ha="left", fontsize=13,
                 color=INK, weight="bold")
    fig.text(0.01, 0.905, "Median signal during the expression minus rest, in units of rest variability",
             fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(png, dpi=160)
    plt.close(fig)


def record_site(site, port, reps, baud):
    import serial

    OUT.mkdir(parents=True, exist_ok=True)
    sched, total = build_schedule(reps)
    speaker = Speaker()
    ser = serial.Serial(port, baud, timeout=0.5)
    time.sleep(2.5)  # opening the port resets the Uno; wait for it to boot
    ser.reset_input_buffer()
    speaker.say(f"Testing {SITE_TITLES[site]}. Get ready, relax your face.")
    time.sleep(4)

    rows, stop = [], threading.Event()
    t0 = time.perf_counter()

    def reader():
        while not stop.is_set():
            parts = ser.readline().decode(errors="ignore").strip().split(",")
            try:
                rows.append((time.perf_counter() - t0, int(parts[0])))
            except (ValueError, IndexError):
                pass

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    for start, _, idx in sched:
        while time.perf_counter() - t0 < start:
            time.sleep(0.01)
        label = "Relax" if idx is None else ACTIONS[idx][0]
        if start > 0 or idx is not None:
            speaker.say(label)
        print(f"{start:5.1f}s  {label}", flush=True)
    while time.perf_counter() - t0 < total:
        time.sleep(0.01)
    stop.set()
    th.join(timeout=2)
    ser.close()
    speaker.say("Recording finished")
    speaker.close()

    stamp = time.strftime("%H%M%S")
    csv_path = OUT / f"{site}_{stamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "A0"])
        w.writerows(rows)

    t, a0 = load_csv(csv_path)
    r_med, r_sd, res, sat = analyze(t, a0, sched)
    print(f"\n{len(t)} samples, ~{len(t) / total:.0f} Hz; rest {r_med:.0f} +/- {r_sd:.0f}; "
          f"saturated {sat * 100:.1f}%")
    for k, (name, _) in enumerate(ACTIONS):
        print(f"  {name:<15} activation {res[k][0]:+6.1f}")
    png = OUT / f"{site}_{stamp}.png"
    site_figure(site, t, a0, sched, res, png)
    print(f"\nFigure: {png}")


def compare(reps):
    sched, _ = build_schedule(reps)
    found = [(s, sorted(OUT.glob(f"{s}_*.csv"))) for s in SITES]
    found = [(s, files[-1]) for s, files in found if files]
    if not found:
        print("No recordings yet")
        return
    fig, axes = plt.subplots(len(found), 1, figsize=(13, 3.3 * len(found) + 0.8), sharex=True, squeeze=False)
    scores = {}
    for ax, (site, path) in zip(axes[:, 0], found):
        t, a0 = load_csv(path)
        _, _, res, _ = analyze(t, a0, sched)
        plot_site(ax, t, a0, sched, site, res)
        scores[site] = [r[0] for r in res]
        print(f"{site:<10}" + "".join(f"{v:>+8.1f}" for v in scores[site]))
    axes[-1, 0].set_xlabel("Time (s)", fontsize=9)
    fig.suptitle("Facial EMG - three sites compared", x=0.01, ha="left", fontsize=13, color=INK, weight="bold")
    action_legend(fig)
    fig.tight_layout(rect=(0, 0.04, 1, 0.98))
    stamp = time.strftime("%H%M%S")
    fig.savefig(OUT / f"comparison_waveforms_{stamp}.png", dpi=160)
    plt.close(fig)
    summary_figure(scores, OUT / f"comparison_summary_{stamp}.png")
    print(f"\nFigures saved in {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("site", help="forehead / eye / mouth, or compare")
    ap.add_argument("--port", default="COM4")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()
    if args.site == "compare":
        compare(args.reps)
    else:
        record_site(args.site, args.port, args.reps, args.baud)
