# V2 — hardware evaluation, PCB analysis, and what changed

This is Version 2 of the existing `PCBX_Capstone` repository. The title,
objectives, scope, the golden-reference approach and the PASS / FAIL /
REVIEW classification are unchanged. Only what the new hardware
(2 × Camera Module 3) and the requested features need was changed.

Labels: **[CONFIRMED]** = official/manufacturer source or verified by running
the code · **[ESTIMATE]** = calculated, must be measured · **[MUST TEST]** =
needs the physical chamber · **[DECISION]** = engineering choice with reasons.

---

## 1. Hardware evaluation (Part 2)

| # | Question | Answer |
|---|---|---|
| 1 | Pi 5 4 GB enough? | **Yes.** Estimated 1.2–2.2 GB in use (V1 analysis unchanged; Camera Module 3 in 2×2-binned mode uses less RAM than the old 16 MP plan). [ESTIMATE] — measure with `tools/benchmark.py`. |
| 2 | Two Camera Module 3 on one Pi 5? | **Yes.** The Pi 5 has two 4-lane MIPI connectors (CAM/DISP 0 and 1), each for a camera *or* a display. Two official camera modules work without configuration changes. [CONFIRMED] |
| 3 | Both images + YOLO without long delays? | **Yes** if the models run as NCNN. Ultralytics' Pi 5 benchmark (YOLO26n, 640 px) lists ~67 ms/image for NCNN vs ~299 ms for PyTorch `.pt`, network only. [CONFIRMED] Per board: ≈ 1.3–2.2 s. [ESTIMATE] |
| 4 | Simultaneous operation possible? | **Yes, technically.** Picamera2 can open and stream both cameras at the same time (two `Picamera2(n)` objects). [CONFIRMED] `tools/test_cameras.py --both-streaming` checks it on your Pi. [MUST TEST] |
| 5 | Sequential acquisition better? | **Yes — and it is what the software does.** Both cameras stay *open and streaming* the whole session (no start-up delay), but the photos are taken *one after the other*, because only one LED strip may be on per photo (light from the other side leaks through holes and board edges). Cost: < 1 s. [DECISION] |
| 6 | Same camera model for both sides? | **Yes, and it is better.** Identical optics → identical code, one calibration procedure, one set of settings. Each camera still gets its **own** lens calibration file, and each **side** has its own golden reference. Because both cameras see a board face un-mirrored and every image is warped to the same 10 px/mm canvas, a side's golden reference is valid for whichever camera sees that side (this is what makes flipped insertion work). |
| 7 | 32 GB microSD enough? | **Yes**, with weekly off-loading of `logs/`. OS + desktop ≈ 5–7 GB, venv with CPU PyTorch ≈ 2–3 GB, models < 30 MB → ~20 GB free. One inspection with raw images ≈ 2–4 MB → ~5,000 boards before cleaning; a 250-image-per-side dataset capture ≈ 1 GB. [ESTIMATE] Buy a **high-endurance A1/A2** card; 64 GB only if it costs about the same. Check with `df -h`. |
| 8 | Limitations | (a) Picamera2/libcamera camera numbering — confirm which camera is `camera_num 0/1` with `rpicam-hello --list-cameras`; (b) two CSI cameras occupy both CAM/DISP ports → use an **HDMI** display, not the DSI touch display; (c) ribbon cables: Pi 5 needs the **22-pin "Standard–Mini"** cable, keep it short (≤ 500 mm) and away from the drawer; (d) Camera Module 3 standard focuses from **10 cm**, so mount ≥ 11 cm from the board; (e) only one inference runs at a time (sides processed one after the other); (f) OpenCV can only *decode* EAN/UPC barcodes. |
| 9 | Recommended settings | 2304 × 1296 binned capture, manual exposure (`ExposureTime`), AWB off with fixed `ColourGains`, `AfMode` manual + fixed `LensPosition` (≈ 1 / distance in m; tune with `--focus-sweep`), NCNN models, Active Cooler, official 27 W PSU. All in `config.py`. |

**Conclusion:** the Pi 5 4 GB + 2 × Camera Module 3 Standard combination is
sufficient. Nothing needs to be replaced. The EMEET/Arducam code path is kept
only as an optional fallback (`backend: "uvc"`).

### Camera Module 3 facts used [CONFIRMED]
4608 × 2592 sensor, 66° horizontal × 41° vertical field of view (standard
lens), focus range 10 cm–∞, Sony IMX708, motorised focus. At 120 mm the view
is ≈ 156 × 90 mm → ≈ 14.8 px/mm in the 2304-wide binned mode, above the
10 px/mm canvas. [ESTIMATE]

---

## 2. What the PCB photos show

Your board is a Sharp power-supply board, silkscreen **"SHARP QPWBP0335PFZZ"**,
with a per-unit sticker **"MTI 5V PWR21100004 FT"** and masking tape "S4".

| Feature | Use in V2 |
|---|---|
| "SHARP" logo + "QPWBP0335PFZZ" part number (front, bottom-left) | **Front identification markers** (template matching). Same on every unit. |
| White rectangular block inside the T1 outline + "T1" label (back) | **Back identification markers**. Very high contrast — the most reliable back marker. |
| Barcode | **Not visible in the photos.** The white T1 block may be a barcode-label area left blank on this unit. Supported as an *optional* marker; identification does not depend on it. |
| Sticker "PWR21100004" | **Not used as a template** — the number changes from unit to unit (it is the serial). Could be read for traceability later (OCR), out of scope. |
| Masking tape "S4" | Covers part of "SHARP"/"QPWBP…" on this unit. Markers are matched individually, so one covered marker does not break identification (min_markers = 1). Ask the company whether tape is normal on production boards. |
| 4 corner mounting holes (both sides) | **Fiducials** for sub-millimetre alignment. They are 180°-symmetric, so they give position only; orientation comes from the markers. |

**Component count check:** front = F1, L1, L2, C13, VAR1, C1, C2, C3, C6,
second large capacitor next to C6, C12, C10, T1, CN1, PWR1 → **15** (JMP02 wire
jumper not counted); back = 9 resistors (R1, R3, R4, R6, R9, R10, RFB1, RFB2,
RSENSE), 4 SMD capacitors (C4, C7, C8, C11), 7 diodes (D1–D5, D7, D8), IC1 →
**21**. Both match the counts in your PDF.

**Class list change [DECISION — confirm with your adviser]:** the V1 front
classes had no class for **C13** (red X2 film capacitor) or **C10** (light-blue
Y ceramic disc), and listed a `terminal_block` the board does not have. V2
front classes: `electrolytic_cap, film_capacitor, ceramic_capacitor,
varistor, fuse, inductor, transformer, connector`. Back classes unchanged
(`resistor, smd_capacitor, diode, ic8`; label D8 — the large DPAK-type
package — as `diode` too). Without these classes, a missing C13 or C10 could
never be detected.

---

## 3. Identification and orientation strategy (Parts 4–5)

| Method | Verdict for PCB X |
|---|---|
| **Template matching of printed markings** | **Used.** Fast (< 5 ms per marker), no training, works for logos and text as *images*, gives position → orientation. |
| Barcode detection (`cv2.barcode`) | **Supported, optional.** Detects 1-D barcodes; decodes EAN-8/13, UPC-A/E only [CONFIRMED]. Other symbologies (e.g. Code 128) are decoded with `pyzbar` if installed. |
| OCR of the serial/part number | **Not used.** Small silkscreen, partly taped over, slow on a Pi CPU, error-prone. Matching the printed text as an image is more reliable. |
| ArUco / QR markers | **Not needed.** Would require adding stickers to every board (changes the product). Possible fallback if the company allows a label. |
| Mounting holes (fiducials) | **Used for alignment**, not identification (symmetric). |

Order: front markers first (SHARP, part number); if none is confidently found
→ back markers (T1 block, T1 label, optional barcode); if none → the side is
**unknown → REVIEW**. If markers match at both 0° and 180° equally →
**ambiguous → REVIEW**. Details and calibration procedure:
`docs/PCB_IDENTIFICATION_AND_ORIENTATION.md`.

---

## 4. Changes by module

Legend: **K** kept unchanged · **M** modified/extended · **N** new · **R** removed (with reason)

| Module / file | Status | What and why |
|---|---|---|
| `config.py` | M | Cameras renamed by position (`upper` CAM1 / `lower` CAM0), both Camera Module 3; `INSPECTION_MODE` dual/flip; settings.json overrides with validation. Board/model specifics moved to the profile. |
| `config/settings.json` | N | Values changed from the GUI (whitelisted, validated). |
| `camera/picam_camera.py` | M | Detects connected cameras, warns if not IMX708, `fresh=False` capture for live preview, skips unsupported controls. |
| `camera/uvc_camera.py` | M | Kept as optional fallback only. |
| `camera/file_camera.py` | K/M | Simulation kept; empty folder now raises a clean camera error. |
| `vision/identification.py` | N | Marker-based side identification (front first), 0/180 decision, barcode marker, whole-board fallback. |
| `vision/board_alignment.py` | M | One aligner per **camera** (knows both sides); outline → identification → orientation → fiducials. 90/270° handled by the outline step. Reports rotation applied. V1 outline/warp/fiducial code reused. |
| `vision/fiducials.py` | M | Diameter range widened for mounting holes. |
| `vision/calibration.py` | M | Calibration file may also hold a fixed homography. |
| `vision/component_detection.py` | M | Validates model before use (exists, loads, class list = profile) with clear errors. |
| `inspection/profile.py` | N | PCB profile folder (`models/pcb_x/`): metadata, model resolution (NCNN preferred, `.pt` fallback), readiness check. |
| `inspection/golden_reference.py` | M | Schema v2: both sides in one file, per-side thresholds, default/class/component tolerances incl. X and Y, `required` flag, validation, atomic save with backups + revision, normalised coordinates written for reference. |
| `inspection/component_matching.py` | K | Hungarian matching unchanged (uses resolved tolerances). |
| `inspection/decision_engine.py` | M | V1 rules R1–R8, S1 kept; added per-axis tolerance, optional parts, R9 ambiguous match, S2 side-level REVIEW reasons, documented combination table. |
| `inspection/runner.py` | M | Dual mode (side assignment per image, flipped insertion handled), flip mode (prompt, same-side detection, FINISH), never crashes on missing models/cameras ("not ready" list), records profile + golden revision/hash. |
| `gui/interface.py` | M | Same layout idea; adds side info (camera, identification, rotation, holes), flagged-parts table with dx/dy, live preview, FINISH for flip mode, NOT READY list. |
| `gui/settings_window.py` | N | Profile/model status, inspection settings, tolerance editor, raw JSON editor, restore backup. |
| `gui/history_window.py` | N | History list, open folder, HTML report, CSV export. |
| `gui/overlay.py` | M | New statuses drawn. |
| `storage/result_logger.py` | M | More CSV columns (cameras, mode, profile, golden revision/hash, notes); V1 CSV kept as `results_v1.csv`. |
| `storage/report.py` | N | Self-contained HTML inspection report. |
| `tools/*` | M | Camera names, profile paths; `build_board_profile.py` now creates identification markers; `capture_dataset.py` sorts images by identified side. |
| `tools/check_profile.py` | N | Deployment check: metadata, golden, markers, model load, sample inference. |
| `references/examples/` | R | V1 per-side formats; replaced by `models/pcb_x/*.example.json`. |
| `tests/` | M/N | V1 decision tests kept; alignment test replaced by V2 scenarios (15 required cases + extras) and a GUI smoke test. |
| `training/` | M | Class list (see §2), Label Studio configs, `export.py --profile-dir` installs into the profile, notebook packages in profile layout. Dataset organisation `pcbx_top` / `pcbx_bottom` kept (top = front, bottom = back). |
| `lighting/`, `hardware/`, `deploy/`, `install_pi.sh`, `run_pcbx.sh` | K/M | Unchanged except installer messages and `pyyaml`. |

### Architectural changes and why
1. **Cameras named by position, sides identified from the board.** V1 assumed
   "top camera = top side". With identical cameras and flipping allowed, a
   camera can see either side, so the side must come from the image itself.
2. **PCB profile folder.** Lets you replace the model or add a second board
   without touching code (your Part 6 request), and keeps camera data
   (`references/calibration`) separate from board data (`models/<profile>`).
3. **"No verdict" states became REVIEW** where you asked for it (side not
   identified, orientation ambiguous, capture unusable). Pure operator
   prompts (door open, no board at all, flip the board in flip mode) still
   give no verdict because no inspection took place.

---

## 5. Implemented vs. needs physical validation

| Feature | Implemented & tested in simulation | Needs physical validation |
|---|---|---|
| Two-camera capture (sequential, both open) | ✔ (file cameras) | ✔ Picamera2 with 2 × CM3, timing |
| Flip mode (one camera) | ✔ | ✔ |
| Side identification (markers, barcode) | ✔ synthetic boards | ✔ real markers, real lighting, tape on units |
| Orientation 0/90/180/270, ambiguity | ✔ | ✔ |
| Mounting-hole fine alignment | ✔ | ✔ hole visibility, residual |
| Model loading .pt / NCNN, validation | ✔ real (tiny) YOLOv8n trained + exported in our environment | ✔ speed on Pi 5 |
| Golden JSON, tolerance editing, backups | ✔ incl. GUI under a virtual display | — |
| Rules and front/back combination | ✔ 15 required scenarios | ✔ with real defect boards |
| GUI (main, settings, history, preview) | ✔ smoke test (simulated) | ✔ touchscreen usability |
| LEDs, buttons, drawer switch | code unchanged from V1 | ✔ |

---

## 6. Missing information (please provide / confirm)

1. **Barcode:** does PCB X carry a barcode sticker (location, symbology)? Not visible in the photos.
2. **Masking tape / stickers:** are "S4" tape and the PWR sticker on every production unit, and always in the same place? (They must not cover identification markers.)
3. **Exact board size and mounting-hole positions** (calipers or Gerber) — examples use 115 × 45 mm and holes ≈ 4 mm from the edges.
4. **Class list confirmation** (§2): film/ceramic capacitor classes, no terminal block.
5. **Tolerances** per component type from the partner company (IPC-A-610 class).
6. **Which defect types** the company wants detected (missing, shifted, wrong part — polarity/solder are outside scope unless added).
7. **Number of physical boards** available (affects dataset and test split).
8. **Display**: final screen model (HDMI recommended, see §1 limitation b).

---

### Sources (checked Nov 2026)
Raspberry Pi camera documentation (Pi 5 uses the 22-pin mini connector,
Standard–Mini cable) · Arducam quick-start guide (Pi 5: metal contacts face the
Ethernet port) · Tom's Hardware / The Pi Hut dual-camera guides (two cameras on
Pi 5 with Picamera2) · Raspberry Pi Camera Module 3 product brief and
product page (4608 × 2592, 66° × 41°, 10 cm–∞) · Ultralytics Raspberry Pi guide
(YOLO26n Pi 5: PyTorch 299 ms, ONNX 126 ms, NCNN 67 ms) · OpenCV barcode
tutorial (EAN-8/13, UPC-A/E).
