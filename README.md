# MyoMask · Facial EMG Experiment

Code and data behind the sensor test in my MyoMask portfolio project: which facial muscles tell expressions apart, measured with a single-channel EMG sensor, an Arduino Uno and a Python recorder. Everything here was built, coded and recorded by me.

![Activation score per site](results/1_activation_summary.png)

## Results

Activation score = (median signal during the expression − median at rest) ÷ robust SD at rest.

| Site | Muscle | Pucker lips | Squeeze eyes | Raise eyebrows |
|---|---|---:|---:|---:|
| Forehead | Frontalis | +0.4 | −0.5 | **+3.9** |
| Eye corner | Orbicularis oculi | +0.1 | +0.8 | −0.4 |
| Mouth corner | Orbicularis oris | **+1.6** | **+1.6** | +0.2 |

- The forehead responds selectively to raising the eyebrows (clearest result).
- The mouth corner responds to puckering and to squeezing the eyes (squeezing also tenses the cheeks and upper lip).
- The eye corner shows short peaks only; the weak score reflects motion artifacts on thin, mobile skin.

**Limits:** one participant (me), one channel, two rounds per site. The scores are indicative, not statistical.

![Raw EMG at three sites](results/2_waveforms_three_sites.png)

## Setup

- EMG sensor board, single channel, ±9 V from two 9 V batteries; SIG → Arduino A0, GND → Arduino GND
- 3 surface electrodes per site: MID and END on the muscle, REF on bone behind the ear
- Arduino Uno reads A0 at about 240 Hz and streams over USB serial (115200 baud)
- Python gives voice cues, records the signal to CSV, scores each expression and plots it

![Workflow](docs/workflow_diagram.png)

**Protocol per site:** rest 5 s, then (pucker lips 4 s, rest 4 s, squeeze eyes 4 s, rest 4 s, raise eyebrows 4 s, rest 4 s) × 2 rounds. Sites are tested one at a time.

## Files

| Path | What it is |
|---|---|
| `code/EMG_6ch_fix.ino` | Arduino sketch: reads A0–A5 (with a settling read) and prints them over serial |
| `code/emg_site_en.py` | Recorder: voice cues, serial capture, CSV, activation scores, plots |
| `code/emg_avatar_demo.py` | Avatar test: turns the forehead score into an avatar expression (live, simulated or replaying a CSV) |
| `code/workflow_diagram.py` | Draws the workflow diagram |
| `data/*.csv` | Raw recordings, one per site: time in seconds, A0 value 0–1023 |
| `results/*.png` | Summary chart, waveforms of all sites, one figure per site |

## Run it

```bash
pip install -r requirements.txt
python code/emg_site_en.py forehead --port COM4   # record one site (forehead / eye / mouth)
python code/emg_site_en.py compare                # compare the latest recording of every site
python code/emg_avatar_demo.py --replay           # replay data/forehead_134856.csv into the avatar
```

Close the Arduino IDE Serial Monitor first so the port is free.

**Safety note:** connect the two 9 V batteries as +9 V / GND / −9 V exactly as marked on the sensor board. Reversing them burned one of my boards during the Gen 2 test.
