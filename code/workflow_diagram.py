"""Draw the experiment workflow diagram (English) as a PNG."""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = sys.argv[1] if len(sys.argv) > 1 else "workflow_diagram.png"
INK, INK2, MUTED, LINE, SURFACE, CARD = "#0b0b0b", "#52514e", "#898781", "#c3c2b7", "#fcfcfb", "#ffffff"
ACCENT = "#2a78d6"
ACTIONS = [("Pucker lips", "#2a78d6"), ("Squeeze eyes", "#eb6834"), ("Raise eyebrows", "#1baf7a")]
plt.rcParams["font.family"] = "Segoe UI"

STEPS = [
    ("Electrodes", "3 leads on one muscle\nMID · END · REF"),
    ("EMG sensor", "Amplify · rectify · smooth\n±9 V battery supply"),
    ("Arduino Uno", "Pin A0 · 10-bit ADC\n~236 samples / s"),
    ("Python", "Voice-cued protocol\nSerial log → CSV"),
    ("Analysis", "Activation vs. rest\nWaveform & summary plots"),
]
LINKS = ["", "", "USB", ""]

fig = plt.figure(figsize=(14, 3.7))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 14)
ax.set_ylim(0, 3.7)
ax.axis("off")
fig.patch.set_facecolor(SURFACE)

ax.text(0.5, 3.3, "Facial EMG Experiment - Workflow", fontsize=17, weight="bold", color=INK)

w, h, gap, y0 = 2.2, 1.55, 0.45, 1.25
x0 = (14 - (5 * w + 4 * gap)) / 2
for i, (title, body) in enumerate(STEPS):
    x = x0 + i * (w + gap)
    ax.add_patch(FancyBboxPatch((x, y0), w, h, boxstyle="round,pad=0,rounding_size=0.14",
                                fc=CARD, ec=LINE, lw=1.1))
    ax.add_patch(FancyBboxPatch((x, y0 + h - 0.07), w, 0.07, boxstyle="square,pad=0", fc=ACCENT, ec="none"))
    ax.text(x + 0.2, y0 + h - 0.33, f"{i + 1:02d}", fontsize=10, color=ACCENT, weight="bold", va="center")
    ax.text(x + 0.2, y0 + h - 0.64, title, fontsize=13.5, color=INK, weight="bold", va="center")
    ax.text(x + 0.2, y0 + h - 0.9, body, fontsize=9.4, color=INK2, va="top", linespacing=1.5)
    if i < 4:
        xa = x + w + 0.06
        ax.add_patch(FancyArrowPatch((xa, y0 + h / 2), (xa + gap - 0.12, y0 + h / 2),
                                     arrowstyle="-|>", mutation_scale=14, color=MUTED, lw=1.4))
        if LINKS[i]:
            ax.text(xa + (gap - 0.06) / 2, y0 + h / 2 + 0.1, LINKS[i], fontsize=7.8, color=MUTED,
                    ha="center", va="bottom")

# protocol strip: Rest 5 s, then (action 4 s + rest 4 s) x 3 expressions, repeated twice
py = 0.6
ax.text(x0, py, "Protocol per site", fontsize=9.5, color=INK2, weight="bold", va="center")


def pill(cx, label, col):
    tw = 0.068 * len(label) + 0.28
    ax.add_patch(FancyBboxPatch((cx, py - 0.18), tw, 0.36, boxstyle="round,pad=0,rounding_size=0.18",
                                fc=(col + "22") if col else "#f1f0ec", ec=col or LINE, lw=0.9))
    ax.text(cx + tw / 2, py, label, fontsize=8.4, color=INK2, ha="center", va="center")
    return cx + tw + 0.08


cx = pill(x0 + 1.5, "Rest 5 s", None)
ax.text(cx + 0.02, py, "→", fontsize=11, color=MUTED, va="center")
cx += 0.32
ax.text(cx, py, "(", fontsize=16, color=MUTED, va="center")
cx += 0.14
for name, col in ACTIONS:
    cx = pill(cx, f"{name} 4 s", col)
    cx = pill(cx, "Rest 4 s", None)
ax.text(cx - 0.04, py, ")", fontsize=16, color=MUTED, va="center")
ax.text(cx + 0.14, py, "× 2", fontsize=10, color=INK2, weight="bold", va="center")

fig.savefig(OUT, dpi=170)
print(OUT)
