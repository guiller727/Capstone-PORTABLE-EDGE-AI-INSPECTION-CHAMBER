# Package D — Testing and validation procedures

Each test lists: **purpose · setup · procedure · tool · pass criterion ·
record**. Pass criteria are *suggested* starting points — agree final values
with your adviser and the partner company *before* testing, and write them in
Chapter 3. Record every run in a sheet (date, settings, result) — copy the
templates at the end.

| # | Test | Tool | When |
|---|---|---|---|
| D1 | Camera | `tools/test_cameras.py` | Stage 2, after any camera change |
| D2 | LED | `tools/test_leds.py` | Stage 3 |
| D3 | Inputs | `tools/test_inputs.py` | Stage 11 |
| D4 | Calibration & fiducial/alignment | `tools/calibrate_camera.py`, `tools/test_alignment.py` | Stage 6 |
| D5 | Model validation | `training/validate.py`, notebook cell 12 | after each training |
| D6 | Golden-reference accuracy | `tools/build_golden_reference.py`, `tools/test_alignment.py` | Stage 9 |
| D7 | Inspection decision | `tools/run_offline.py`, `pytest` | Stage 10 |
| D8 | Full system integration | GUI | Stage 13 |
| D9 | Performance | `tools/benchmark.py` | Stage 13 |

---

### D1. Camera test
* **Purpose:** frames are sharp, correctly exposed and *stable* (no auto-adjustment).
* **Setup:** final camera height, LEDs connected, known-good board in the nest, drawer closed.
* **Procedure:** `python tools/test_cameras.py` (10 captures per side); focus sweep if needed.
* **Pass:** configured resolution; brightness std < 2.0; sharpness CV < 5 %; capture < 1.0 s/side.
* **Record:** resolution, exposure/gain/focus values, mean brightness, sharpness, time.

### D2. LED test
* **Purpose:** independent switching, uniform white light, no flicker.
* **Procedure:** `python tools/test_leds.py`; photograph a white/grey card with each side lit.
* **Pass:** only the selected strip lights; grey-card corners within ±10 % of centre
  brightness; no colour errors; LEDs off after exit; LED supply wires not warm after 10 min on.

### D3. Inputs test
* **Procedure:** `python tools/test_inputs.py`; press START 20×; open/close drawer 20×.
* **Pass:** exactly 20 "START pressed" lines (no bounce), 40 correct door messages.

### D4. Calibration, fiducial and alignment test
* **Purpose:** prove Scenarios A, B, C and the "not PCB X" case.
* **Procedure:** calibration RMS from `calibrate_camera.py`. Then capture raw images
  (`capture_dataset.py --side both`) in four sets of **≥ 20 insertions**:
  (A) normal, (B) rotated 180°, (C) flipped, (D) empty tray / other board. For each set:
  `python tools/test_alignment.py --side top --images <set> --expect ok|wrong_side|unknown_board`
* **Pass:** calibration RMS < 0.5 px (USB webcam < 1.0 px); A: 100 % `ok`, B: 100 % `ok`
  with `rot180=True`, C: 100 % `wrong_side`, D: 100 % `no_board`/`unknown_board`;
  mean fiducial residual < 0.15 mm; repeatability (std) < 0.10 mm.
* **Also test:** cover one fiducial with a paper dot → still `ok` (if ≥ 2 visible);
  cover all → `coarse` → board result cannot be PASS (rule S1).

### D5. Model validation
* **Purpose:** detector quality on boards it has never seen.
* **Procedure:** `python validate.py --side <s> --weights ...` (val split) for every
  candidate (YOLOv8n, YOLO26n, imgsz variants). Choose **one** per side on validation.
  At the very end: `--split test` once. Also validate the **NCNN** model
  (`--weights export_out/<s>_best_ncnn_model --imgsz 512 1216`) — it must be within
  ~1 mAP point of the `.pt`.
* **Metrics** (explain in Chapter 3):
  * **Precision** = TP / (TP + FP) — of the boxes the model drew, how many were right.
  * **Recall** = TP / (TP + FN) — of the real parts, how many were found. *Most important
    here: a missed part becomes "MISSING → FAIL" (false reject).*
  * **F1** = 2PR / (P + R) — balance of both.
  * **mAP@50** — average precision over all classes, a box counts as correct if
    IoU ≥ 0.5 with the label. **mAP@50-95** averages IoU thresholds 0.5…0.95 (box tightness).
  * **Confusion matrix** — rows/columns per class + "background": shows *which*
    classes are mixed up (e.g. resistor ↔ smd_capacitor) and missed parts.
  * **Training/validation loss & learning curves** (`results.png`): both losses should
    fall and flatten; validation loss rising while training loss falls = overfitting.
* **Pass (suggested):** mAP@50 ≥ 0.95 overall and recall ≥ 0.95 for every class on the
  test boards. (The chamber is very controlled; lower values usually mean a data problem.)

### D5b. Learning-curve test (dataset sufficiency, PDF Section 3.4)
`python learning_curve.py --side bottom` (or notebook cell 17) trains on 25/50/75/100 %
of the training images with the same validation set and plots val mAP@50 vs. number of
images. **Interpretation:** curve flat between 75 % and 100 % (< 2 points gain) →
enough data; still rising → capture more (different boards first). Report the plot.

### D6. Golden-reference accuracy
* **Purpose:** the expected positions are accurate and tolerances are realistic.
* **Procedure:** build from 10+ known-good boards × 3 insertions. Then inspect
  **other** known-good boards (not used to build it) 3× each with `run_offline.py`.
  Measure 3–5 component centre distances with calipers/CAD and compare with `x_mm`.
* **Pass:** every component `seen` ≥ 90 % while building; std < 0.10 mm; 0 MISPLACED
  on unseen good boards; caliper/CAD distances agree within 0.2 mm; every tolerance
  > 3 × measured std (otherwise good boards will randomly fail).

### D7. Inspection decision test
* **Purpose:** the PASS / FAIL / REVIEW logic is correct and explainable.
* **Unit level:** `python -m pytest -q tests` — covers missing, wrong type, misplaced,
  uncertain, extra, duplicates, FAIL-over-REVIEW priority, Hungarian vs nearest-neighbour,
  coarse alignment, WS2812 encoding, and the A/B/C alignment scenarios.
* **System level:** prepare a ground-truth table of **physical test boards** —
  known-good boards and boards with one controlled defect each (missing part,
  shifted part ≥ 1 mm, wrong part, extra part). Capture each 3× into
  `test_set/top|bottom/` and write `test_set/truth.csv` (`name,expected` with PASS/FAIL).
  `python tools/run_offline.py --images test_set --truth test_set/truth.csv`
* **Report:** the 2 × 3 table (truth PASS/FAIL × system PASS/FAIL/REVIEW), plus
  * **Defect escape rate** = FAIL boards judged PASS ÷ FAIL boards → target **0**.
  * **False reject rate** = good boards judged FAIL ÷ good boards.
  * **REVIEW rate** = REVIEW ÷ all boards (+ how the operator decided).
  * Component-level: per defect type, detected / missed.

### D8. Full-system integration test
* Power on → program starts by itself → READY within ~60 s [MUST TEST].
* 30 consecutive boards (mix of good/defective/rotated/flipped) using the
  physical START button only. **Pass:** no crash or freeze; every flip/rotation
  handled per Scenarios A–C; every board logged; drawer-open start refused.
* Pull the USB camera mid-session → "ERROR – TRY AGAIN", program stays alive;
  reconnect + restart program recovers.
* Kill the process (`pkill -f main.py`) → restarts within 5 s (`run_pcbx.sh`).

### D9. Performance test
* `python tools/benchmark.py` then `python tools/benchmark.py --full 30`.
* **Report:** inference ms per side (mean, p95), full inspection time (mean, p95, max),
  capture time, RAM used, CPU temperature start/end, `get_throttled`.
* **Pass:** mean total ≤ 4 s (your objective), p95 ≤ 5 s, `throttled=0x0`, RAM < 3 GB.
* **Comparison with manual inspection:** time the operator on the same boards
  (the PDF cites ~33 s/unit from Dayrit et al., 2025 — measure your own baseline too).

---

## Record templates (copy into Excel)

**Alignment test**

| Date | Side | Set (A/B/C/D) | n | ok | rot180 | wrong_side | unknown/no_board | coarse | mean residual mm | max residual mm |
|---|---|---|---|---|---|---|---|---|---|---|

**Decision test**

| Board ID | Defect (truth) | Capture # | System verdict | Flagged parts | Operator decision | Time s |
|---|---|---|---|---|---|---|

**Performance test**

| Date | Model top/bottom | imgsz | inf top ms (mean/p95) | inf bottom ms | total s (mean/p95/max) | RAM GB | temp °C start/end | throttled |
|---|---|---|---|---|---|---|---|---|
