"""
Gen 1 EMG recording: webcam face + live EMG curve in one video.

Keys (in the preview window):
  SPACE  guided run: 5 s baseline, then 3 x (relax 4 s / raise brows 4 s), beeps as cues
  R      free recording start / stop (no cues)
  ESC    quit

Output: recordings/<timestamp>.mp4 and .csv (t, raw, smooth, phase)
Before recording: unplug the laptop charger and HDMI, hands off the laptop.
"""
import argparse, csv, os, threading, time, winsound
from collections import deque

import cv2
import numpy as np
import serial

FPS = 20
W, H = 640, 480
PLOT_SECONDS = 8
SMOOTH_N = 40  # ~0.2 s at ~200 Hz

BASELINE_S, PHASE_S, ROUNDS = 5, 4, 3
GUIDED_TOTAL = BASELINE_S + PHASE_S * 2 * ROUNDS


def guided_phase(t):
    if t < BASELINE_S:
        return "BASELINE"
    if t >= GUIDED_TOTAL:
        return "DONE"
    return "RELAX" if int((t - BASELINE_S) // PHASE_S) % 2 == 0 else "RAISE BROWS"


def beep(freq, dur=350):
    threading.Thread(target=winsound.Beep, args=(freq, dur), daemon=True).start()


class SerialReader(threading.Thread):
    def __init__(self, port, baud):
        super().__init__(daemon=True)
        self.ser = serial.Serial(port, baud, timeout=0.05)
        time.sleep(2.5)  # Uno resets when the port opens
        self.ser.reset_input_buffer()
        self.buf = deque(maxlen=400 * PLOT_SECONDS)
        self.lock = threading.Lock()
        self.running = True

    def run(self):
        pending = b""
        while self.running:
            pending += self.ser.read(512)
            *lines, pending = pending.split(b"\n")
            now = time.perf_counter()
            for line in lines:
                parts = line.decode(errors="ignore").strip().split(",")
                if parts and parts[0].isdigit():
                    with self.lock:
                        self.buf.append((now, int(parts[0])))

    def snapshot(self):
        with self.lock:
            return list(self.buf)

    def stop(self):
        self.running = False
        self.ser.close()


class Camera(threading.Thread):
    def __init__(self, index):
        super().__init__(daemon=True)
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
        self.frame = np.zeros((H, W, 3), np.uint8)
        self.running = True

    def run(self):
        while self.running:
            ok, f = self.cap.read()
            if ok:
                self.frame = cv2.flip(cv2.resize(f, (W, H)), 1)

    def stop(self):
        self.running = False
        self.cap.release()


def smooth(vals):
    # trailing moving average, so the newest point is not dragged down by edge effects
    v = np.asarray(vals, float)
    if len(v) == 0:
        return v
    c = np.cumsum(np.insert(v, 0, 0))
    idx = np.arange(1, len(v) + 1)
    lo = np.maximum(idx - SMOOTH_N, 0)
    return (c[idx] - c[lo]) / (idx - lo)


def draw_panel(samples, now, baseline, phase, rec_label):
    p = np.full((H, W, 3), 24, np.uint8)
    top, bottom, left, right = 90, H - 70, 20, W - 20
    recent = [(t, v) for t, v in samples if t >= now - PLOT_SECONDS]
    level = 0.0
    if len(recent) > 2:
        ts = np.array([t for t, _ in recent])
        raw = np.array([v for _, v in recent], float)
        sm = smooth(raw)
        ymax = max(300.0, float(sm.max()) * 1.3)
        xs = left + (ts - (now - PLOT_SECONDS)) / PLOT_SECONDS * (right - left)
        ys_raw = bottom - np.clip(raw / ymax, 0, 1) * (bottom - top)
        ys_sm = bottom - np.clip(sm / ymax, 0, 1) * (bottom - top)
        cv2.polylines(p, [np.int32(np.c_[xs, ys_raw])], False, (90, 90, 90), 1, cv2.LINE_AA)
        cv2.polylines(p, [np.int32(np.c_[xs, ys_sm])], False, (120, 220, 60), 3, cv2.LINE_AA)
        level = float(sm[-SMOOTH_N:].mean())
        if baseline:
            yb = int(bottom - min(baseline / ymax, 1) * (bottom - top))
            cv2.line(p, (left, yb), (right, yb), (200, 160, 60), 1, cv2.LINE_AA)
            cv2.putText(p, "baseline", (right - 80, yb - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 160, 60), 1, cv2.LINE_AA)

    cv2.putText(p, "EMG  forehead (A0)", (left, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
    if rec_label:
        cv2.circle(p, (right - 120, 25), 7, (0, 0, 230), -1)
        cv2.putText(p, rec_label, (right - 105, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 230), 1, cv2.LINE_AA)
    if phase:
        color = (60, 140, 255) if phase == "RAISE BROWS" else (220, 220, 220)
        cv2.putText(p, phase, (left, 72), cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 2, cv2.LINE_AA)

    ratio = level / baseline if baseline else 0
    bar_w = int(min(ratio / 4, 1) * (right - left))
    cv2.rectangle(p, (left, H - 45), (right, H - 25), (60, 60, 60), 1)
    cv2.rectangle(p, (left, H - 45), (left + bar_w, H - 25), (60, 140, 255), -1)
    label = f"activation x{ratio:.1f}" if baseline else f"level {level:.0f}  (baseline not set)"
    cv2.putText(p, label, (left, H - 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)
    return p


def summarize(rows):
    phases = {}
    for _, raw, _, ph in rows:
        phases.setdefault(ph, []).append(raw)
    for ph, v in phases.items():
        print(f"  {ph:12s} mean {np.mean(v):6.1f}  median {np.median(v):6.1f}  n={len(v)}")
    if "RELAX" in phases and "RAISE BROWS" in phases:
        print(f"  raise / relax = {np.mean(phases['RAISE BROWS']) / np.mean(phases['RELAX']):.2f}x")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM4")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--test", type=float, default=0, help="headless self-test: record N seconds, no window")
    ap.add_argument("--auto", type=float, default=None, help="start a guided run after N seconds of preview, quit when done")
    args = ap.parse_args()

    os.makedirs("recordings", exist_ok=True)
    ser = SerialReader(args.port, args.baud)
    cam = Camera(args.cam)
    ser.start()
    cam.start()

    mode = None  # None / "guided" / "free"
    rec_start = writer = csv_file = csv_w = None
    frames_written = 0
    last_logged = 0.0
    baseline = None
    cue_done = set()
    rows = []
    base_name = ""

    def start(m):
        nonlocal mode, rec_start, writer, csv_file, csv_w, frames_written, last_logged, cue_done, rows, base_name
        base_name = os.path.join("recordings", time.strftime("%Y%m%d_%H%M%S") + ("_guided" if m == "guided" else "_free"))
        writer = cv2.VideoWriter(base_name + ".mp4", cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W * 2, H))
        csv_file = open(base_name + ".csv", "w", newline="")
        csv_w = csv.writer(csv_file)
        csv_w.writerow(["t", "raw", "smooth", "phase"])
        mode, rec_start, frames_written, cue_done, rows = m, time.perf_counter(), 0, set(), []
        last_logged = rec_start
        beep(900, 300)  # sync marker
        print(f"recording -> {base_name}.mp4")

    def stop():
        nonlocal mode, writer, csv_file
        writer.release()
        csv_file.close()
        print(f"saved {base_name}.mp4 / .csv")
        summarize(rows)
        mode, writer, csv_file = None, None, None

    if args.test:
        start("free")
    launched = time.perf_counter()
    auto_started = False
    try:
        while True:
            now = time.perf_counter()
            samples = ser.snapshot()
            phase = None
            rec_label = ""
            if mode:
                t = now - rec_start
                rec_label = f"REC {t:4.1f}s"
                if mode == "guided":
                    phase = guided_phase(t)
                    # cue beeps at each relax / raise boundary
                    for i in range(2 * ROUNDS):
                        k = BASELINE_S + i * PHASE_S
                        if t >= k and k not in cue_done:
                            cue_done.add(k)
                            beep(500 if i % 2 == 0 else 1200)
                    if t >= BASELINE_S and "base" not in cue_done:
                        cue_done.add("base")
                        b = [v for ts, v in samples if rec_start <= ts < rec_start + BASELINE_S]
                        baseline = float(np.mean(b)) if b else None
                else:
                    phase = "FREE"
                # log new samples
                new = [(ts, v) for ts, v in samples if ts > last_logged]
                if new:
                    sm = smooth([v for _, v in samples])[-len(new):]
                    for (ts, v), s in zip(new, sm):
                        tt = ts - rec_start
                        ph = guided_phase(tt) if mode == "guided" else "FREE"
                        csv_w.writerow([f"{tt:.4f}", v, f"{s:.1f}", ph])
                        rows.append((tt, v, s, ph))
                    last_logged = new[-1][0]

            img = np.hstack([cam.frame.copy(), draw_panel(samples, now, baseline, phase, rec_label)])

            if mode:
                due = int((now - rec_start) * FPS) + 1
                while frames_written < due:
                    writer.write(img)
                    frames_written += 1
                done_guided = mode == "guided" and now - rec_start >= GUIDED_TOTAL + 1
                done_test = args.test and now - rec_start >= args.test
                if done_guided:
                    for d in (0, 0.25, 0.5):
                        threading.Timer(d, beep, (900, 150)).start()
                if done_guided or done_test:
                    stop()
                    if args.test or args.auto is not None:
                        time.sleep(0.6)
                        break

            if args.auto is not None and not auto_started and now - launched >= args.auto:
                auto_started = True
                baseline = None
                start("guided")
            if args.auto is not None and not auto_started:
                phase_left = args.auto - (now - launched)
                img = img.copy()
                cv2.putText(img, f"starting in {phase_left:.0f}s - sit still", (W + 20, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (60, 140, 255), 2, cv2.LINE_AA)

            if not args.test:
                cv2.imshow("EMG Gen 1  |  SPACE guided   R free   ESC quit", img)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    if mode:
                        stop()
                    break
                if key == ord(" ") and not mode:
                    baseline = None
                    start("guided")
                if key in (ord("r"), ord("R")):
                    stop() if mode else start("free")
            time.sleep(max(0, 1 / FPS - (time.perf_counter() - now)))
    finally:
        ser.stop()
        cam.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
