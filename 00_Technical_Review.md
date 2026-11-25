# Technical review and implementation guide — PCB X Edge-AI Inspection Chamber

Reviewed document: *PCB X System Workflow and Training Guide* (8 pages).
This review answers Parts 1–8 of your request. Detailed material lives in
the package documents:

| Part | Where |
|---|---|
| 1 Hardware | `docs/A_Hardware.md` (diagrams, wiring, GPIO table, BOM in PHP) |
| 2 Training | `training/README.md` + `training/PCBX_YOLO_Training.ipynb` |
| 3 Pi software | `docs/C_Pi_Software_Roadmap.md` + `pcbx_inspection/` |
| 4, 5, 6, 8 | this document |
| 7 Test procedures | `docs/D_Testing_and_Validation.md` |

**Labels:** **[CONFIRMED]** checked against official/manufacturer sources or
by running the code in our build environment · **[RECOMMENDATION]** our
engineering choice · **[ASSUMPTION]** something we could not verify ·
**[MUST TEST]** you must measure it on your hardware. No accuracy or speed
number in this package is a measured result on your system.

---

## 0. Verdict in one paragraph

The PDF's architecture — two fixed cameras, sequential lighting, warp to a
fixed px/mm canvas, YOLOv8n per side, OpenCV coordinates, golden reference,
rule-based PASS/FAIL/REVIEW on a Raspberry Pi 5 4 GB with NCNN — is
**technically sound and appropriate for an undergraduate capstone**. We kept
it. The changes are about *reliability* rather than capability: decide
board orientation/side explicitly (the PDF does not), use Hungarian matching,
define what happens when the system *cannot* give a verdict, export
rectangular NCNN models, verify camera control before committing to the two
cameras, and add a level shifter + separate supply for the LEDs.

## 1. Corrections to the PDF

| # | PDF says | Issue | Correction (implemented) |
|---|---|---|---|
| 1 | Warp to "1100 × 450 px at 10 px/mm" | 115 mm × 10 px/mm = **1150** px, not 1100; no margin left for the board edge | Canvas = board + 2.5 mm margin = **1200 × 500 px** (`config.py`) |
| 2 | Bottom `imgsz=1024` | Shrinks the 1200 px canvas to 8.5 px/mm; a square 1024 input also wastes ~58 % of pixels on padding for a 2.4:1 board | Train at **1216**, export NCNN **rectangular 512 × 1216**; top 640 → **288 × 640**. Verified export + prediction in our environment [CONFIRMED] |
| 3 | Board alignment by outline or 2–3 fiducials | A rectangle's outline cannot distinguish 0° from 180°, and the PDF has no step that detects a **flipped** board | Outline → **template check** (correct side 0°/180° vs flipped) → **fiducial** fine alignment. Scenarios A/B/C are unit-tested on synthetic images |
| 4 | "Pick the nearest one (or use linear_sum_assignment)" | Nearest-neighbour can assign one detection to two references | **Hungarian only**, with a class-aware cost (test included that shows the NN failure) |
| 5 | Extra/unmatched detection → REVIEW | Every low-confidence noise box would cause REVIEW; duplicate boxes too | Extra **≥ T_high** → REVIEW; below → logged only; duplicates ignored |
| 6 | No rule for "system could not inspect" | A blurred image or wrong side must never yield PASS | No-verdict states: DOOR_OPEN, ERROR, NO_BOARD, NOT PCB X, FLIP BOARD; and coarse alignment cannot PASS (S1) |
| 7 | RAM ≈ 1–1.5 GB | Ultralytics imports PyTorch even for NCNN | ≈ 1.2–2.2 GB [ESTIMATE] — 4 GB still fine |
| 8 | Arducam: "set the lens position manually in Picamera2" | Arducam states its **AF** models need Arducam's custom libcamera for focus control [CONFIRMED] | Test in Stage 2; fallback Camera Module 3 (stock software) |
| 9 | EMEET "4K" | Retailer spec lists a **4 MP** sensor → 4K output is likely up-scaled [CONFIRMED spec / ASSUMPTION about up-scaling]; lockability of focus/exposure via UVC unknown | Capture 2560×1440; lock via `v4l2-ctl`; stability test decides; fallback 2nd CSI camera |
| 10 | WS2812B via SPI + level shifter | Correct. Missing: power and grounding details | Separate 5 V supply, common ground, 74AHCT125, 330 Ω, 1000 µF; both strips on one data line |
| 11 | Simultaneous capture "also works" | Adds threading + light-leak risk to save < 1 s | Sequential only |
| 12 | Optional 3× offline augmentation "for the paper" | Duplicates what Ultralytics does online; complicates the board-wise split | Don't do it |
| 13 | "Lock exposure… for the Arducam set lens position" | Also needed: white balance (AWB off + fixed gains) on the CSI camera | `ColourGains` fixed in `config.py` |
| 14 | Golden reference: δ from IPC-A-610 and > spread | Correct. Not stated *how* to combine | `tol = max(class tolerance, 4 × measured radial std)`, per component |

Everything else in the PDF — sequential lighting, keep cameras open, discard
buffered frames, CLAHE on L only, no heavy denoise/sharpen, same preprocessing
for training and inference, label by type not designator, label missing parts
by *not* labelling them, 70/15/15 split by board, test set used once, YOLOv8n
first / YOLOv8s only if clearly better, train on Colab/PC never on the Pi,
NCNN on the Pi — is **correct** and kept.

---

## 2. Part 1 summary — hardware (details in `A_Hardware.md`)

* **Pi 5 4 GB: sufficient** [ESTIMATE ≈ 1.2–2.2 GB used]; 8 GB costs ₱6,550 more at
  Makerlab PH (Nov 2026) for unused headroom. **Active Cooler: yes. NCNN: yes**
  [CONFIRMED: Ultralytics recommends NCNN as fastest on Pi; YOLO26n NCNN 67 ms at
  640 px on Pi 5, network only]. **2–4 s per board: realistic** [ESTIMATE 1.3–2.2 s].
* **Cameras:** not incompatible, but test-gated (see correction 8 and 9).
  Different resolutions are not a problem because each side is warped to the same
  10 px/mm canvas and compared only with its own golden reference.
* **LEDs:** WS2812B is sufficient *with* a level shifter, separate supply, diffusers
  and side-angled bars. Plain white strips + MOSFETs are the simpler fallback (code supports both).
* **Storage:** 64 GB A2 high-endurance microSD. SSD only if already owned.
* **Mechanics:** drawer + removable 3-D-printed nest, corner tabs, one drawer microswitch.
  No E-stop, presence sensor or lock.
* **Controls:** Power (J2), START (GPIO17, lit), GUI for everything else.
* **Budget:** ≈ ₱24,200 with the EMEET kept (≈ ₱22,200 if the Arducam passes).

## 3. Part 2 summary — training (details in `training/README.md`)

* Keep **two models** (disjoint classes, different resolutions).
* Label the **aligned canvases** produced by the Pi software → identical preprocessing.
* `prepare_dataset.py` fixes Label Studio's class-order and file-prefix issues and splits **by board**.
* Parameters: PDF values kept except bottom `imgsz 1216`, gentler colour augmentation.
* **YOLO26n**: same dataset, labels, folders, notebook; change only the model name;
  same NCNN export; runs on Pi 5 [CONFIRMED in docs; export+predict verified here].

---

## 4. Part 4 — image processing, fiducials, alignment, rules

### 4.1 Preprocessing: what to implement

| Technique | What it does | Use? |
|---|---|---|
| **Lens undistortion** | Removes barrel/pincushion bending using the checkerboard calibration | **Yes** — needed for correct millimetres, especially for the webcam |
| **Perspective transform (warp)** | Maps the board's 4 corners/fiducials to a fixed rectangle → constant px/mm, straight board | **Yes** — the most important step |
| **CLAHE** (on L of LAB) | Local contrast boost in small tiles, with a clip limit so noise isn't amplified | **Yes** (clip 2.0, 8×8) — helps dark parts on dark mask; colours untouched |
| **Gamma correction** | Non-linear brightness curve (brightens shadows) | **Only if** images are still too dark after fixing exposure; default off |
| Histogram equalization (global) | Stretches the whole histogram | **No** — CLAHE does this better locally; global HE amplifies glare |
| Denoising | Smooths noise | **No** — the chamber is bright, noise is low; denoising erases fine edges of SMD parts |
| Sharpening | Boosts edges | **No** — creates halos YOLO never saw in training |
| Thresholding | Black/white segmentation | **Only inside OpenCV steps** (board outline, fiducials), **never** on the image given to YOLO |
| Quality check | Blur (Laplacian variance), dark/bright, saturation | **Yes** — before inference; retry the capture |

Pipeline (implemented, same for dataset and inspection):
`raw → undistort → outline warp → side/orientation → fiducial refinement →
canvas 1200×500 → CLAHE → YOLO`.
Fix lighting and exposure *first*; software cannot recover clipped highlights.

### 4.2 Fiducials and automatic orientation

1. **Annotate fiducials in YOLO?** **No.** They are simple, high-contrast circles;
   OpenCV (threshold + contour + circularity + sub-pixel centroid) finds them
   deterministically and more precisely than a YOLO box, without labelling.
2. **OpenCV instead of YOLO?** **Yes** (`vision/fiducials.py`).
3. **Orientation from fiducials?** Only if their layout is **not 180°-symmetric**
   (e.g. three in an L). Two diagonal fiducials look the same after 180° rotation.
   That is why the system *also* uses a template comparison. If there are no
   templates yet, the code tries 0° and 180° and keeps the better fiducial fit.
4. **Rotated board corrected automatically?** **Yes** (Scenario B): the canvas is
   rotated by 180° and the homography updated. In the nest only 0°/180°
   (and flipped) are physically possible.
5. **Perspective transform from fiducials?** Yes in principle, but with 2–3
   fiducials we fit a **similarity** (rotation + scale + shift) *on top of* the
   outline homography — robust with only 2 points. A full homography needs 4.
6. **Side A vs Side B?** Each camera stores a reference template of its correct
   side and of the flipped board (`build_board_profile.py --flipped`). The best
   normalised-cross-correlation score decides: correct side → continue; flipped →
   "FLIP THE BOARD", no inspection (Scenario C); all scores low → "NOT PCB X".

**How many fiducials?** 2 visible = enough for the similarity fit; 3 (non-collinear,
asymmetric) = also gives orientation and a residual check. **Partly obstructed?**
Each fiducial is searched only in a small window around its expected position, so
one hidden fiducial is simply "not found"; with ≥ 2 found, alignment is `ok`; with
fewer it is `coarse`, and rule S1 prevents a PASS. A dirty fiducial producing a
wrong centre shows up as a large residual (> 0.35 mm) → `coarse` as well.

### 4.3 Golden reference (`tools/build_golden_reference.py`)

1. **Capture** 10+ known-good boards × 3 re-insertions with the final setup
   (`capture_dataset.py --board Bxx --note good`). Keep them out of the test set.
2. **Identify components:** seed from one hand-checked YOLO label file → each box is
   one expected component; IDs auto-generated (R1, C1, U1 …) — rename to the
   silkscreen designators.
3. **Expected coordinates:** detect on every image, match to the seed with the same
   Hungarian matcher (same class only), take the **mean** centre in mm.
4. **Store:** `references/golden_<side>.json` (format in `inspection/golden_reference.py`):
   ```json
   {"id": "R3", "class": "resistor", "x_mm": 42.10, "y_mm": 18.60, "w_mm": 2.1,
    "h_mm": 1.3, "tol_mm": 0.50, "std_x_mm": 0.05, "std_y_mm": 0.04, "seen": 30}
   ```
5. **Tolerance:** `max(class default, 4 × radial std)`. Class defaults (0.5 mm SMD,
   1.0–1.5 mm THT) are placeholders — set them with the partner company
   (IPC-A-610 placement criteria), and report them.
6. **Same-class components** (many resistors): they are distinguished by **position**,
   not appearance; the Hungarian matcher pairs each expected R with at most one
   detected resistor.

### 4.4 Coordinate extraction and matching

The PDF's chain (YOLO → centre → mm → compare → rules) is correct. Conversion:
`x_mm = x_px / 10 − 2.5`, `y_mm = y_px / 10 − 2.5` on the canvas.

**Nearest neighbour vs Hungarian.** Nearest neighbour treats each reference
alone; two neighbouring resistors can both claim the same detection, hiding a
missing part (shown by `test_hungarian_one_to_one_vs_nearest_neighbour`).
**Hungarian assignment** (`scipy.optimize.linear_sum_assignment`) chooses all
pairs together, minimising total cost, and guarantees one-to-one pairing.

Cost = `distance / tol + 2.0 × (class differs)`; pairs farther than
`max(3 × tol, 1.5 mm)` are forbidden. The class penalty prefers the correct-class
detection when two are nearby, but still allows a wrong-class pairing so the result
is "WRONG TYPE" rather than "MISSING + EXTRA". Components close together are handled
because the cost is normalised by each component's own tolerance.

### 4.5 Final PASS / FAIL / REVIEW decision table

**Pre-conditions (no verdict; board is not inspected):**

| Code | Condition | Screen |
|---|---|---|
| DOOR_OPEN | drawer switch open | CLOSE THE DOOR |
| ERROR | camera failure or quality check failed 3× | ERROR – TRY AGAIN |
| NO_BOARD | no board outline found | NO BOARD |
| UNKNOWN_BOARD | template score < threshold | NOT PCB X |
| WRONG_SIDE | flipped template wins | FLIP THE BOARD |

**Per expected component** (first matching rule wins):

| Rule | Condition | Status | Board effect |
|---|---|---|---|
| R1 | no detection ≥ T_low within the gate radius | MISSING | FAIL |
| R2 | matched detection conf < T_high | UNCERTAIN | REVIEW |
| R3 | conf ≥ T_high, other class | WRONG_TYPE | FAIL |
| R4 | conf ≥ T_high, same class, offset > tol | MISPLACED | FAIL |
| R5 | conf ≥ T_high, same class, offset ≤ tol | OK | — |

**Per unmatched detection:** R6 duplicate of a matched box → ignored · R7 conf ≥ T_high → EXTRA → REVIEW
(`EXTRA_IS_FAIL=True` makes it FAIL if the company prefers) · R8 conf < T_high → logged only.
**Per side:** S1 alignment `coarse` → a PASS becomes REVIEW.

**Board verdict:** FAIL if any FAIL status on either side → else REVIEW if any
REVIEW condition → else PASS. **FAIL has priority**: a confirmed defect is not
hidden by an uncertain one. A part shifted farther than the gate radius appears
as MISSING (+ possibly EXTRA) — still FAIL. Start with T_low = 0.25, T_high = 0.60,
tune on validation boards, freeze before the test set (as in the PDF).

**Delimitation to state:** "wrong type" is detected only when the wrong part
*looks* different (a 1 kΩ vs 10 kΩ resistor is not distinguishable); polarity and
solder-joint quality are not inspected unless added as classes.

---

## 5. Part 5 — capture and inspection sequence

**Evaluation of your 18 steps:** correct in substance. Changes: (a) the drawer
switch is checked before capture; (b) a quality check with retry follows each
capture; (c) identification (PCB X? which side? rotated?) happens **after both
captures**, because it needs the aligned images and capturing both takes ~1 s;
(d) the no-verdict exits are explicit; (e) saving runs in the background so the
result appears immediately.

**Final sequence** (implemented in `inspection/runner.py`):

| # | Step | Notes |
|---|---|---|
| 0 | Start-up (once): open both cameras, lock exposure/WB/focus, load + warm-up both models, load golden refs | 5–20 s [MUST TEST]; never per board |
| 1 | Operator places PCB X in the nest, pushes the drawer closed | microswitch closes |
| 2 | START (button or screen) | ignored while busy |
| 3 | Drawer closed? else CLOSE THE DOOR | |
| 4 | Top LED on → wait `LED_SETTLE_S` → discard `flush_frames` → grab → LED off | |
| 5 | Bottom LED on → wait → discard → grab → LED off | |
| 6 | Quality check each image; retry up to 2× | else ERROR |
| 7 | Align both: undistort → outline → side/orientation → fiducials | NO_BOARD / NOT PCB X / FLIP |
| 8 | CLAHE on both canvases | same function as dataset |
| 9 | YOLO top + bottom (conf ≥ T_low) | |
| 10 | px → mm, Hungarian matching | |
| 11 | Rules → side verdicts → board verdict | |
| 12 | Show overlays, banner, flagged list | REVIEW enables operator buttons |
| 13 | Save raw/canvas/overlay JPEGs + CSV/JSON (background) | |

**Your specific questions**

* *Identification before or after both captures?* After (see above).
* *Keep cameras initialised?* **Yes** — opening takes seconds and resets auto modes.
* *Sequential or simultaneous?* **Sequential** — no light leakage, simpler.
* *Old frames in the EMEET buffer?* After the LED switches on, `grab()` and discard
  `flush_frames` (default 5 ≈ 170 ms at 30 fps), then `read()`. Verified procedure in
  Stage 4: compare brightness with a long-wait reference.
* *How long after the LED?* Start at **0.3 s** (PDF). The LEDs themselves switch in
  microseconds; the wait is for the camera pipeline. Reduce in Stage 4 only if
  brightness stays identical.
* *Quality check before inference?* **Yes** (blur, dark, bright, saturation).
* *Camera fails?* Exception caught → retry → ERROR state on screen, logged, the
  program stays alive; the operator presses START again. If a camera disappears
  completely, restart the program (auto-restart wrapper handles crashes).

---

## 6. Part 6 — dataset

### 6.1 Own dataset

* **250 images per side, 20–30 boards: practical and well-reasoned.** Every image
  contains *all* parts, so 250 images ≈ 3,750 (top) / 5,250 (bottom) labelled
  instances — plenty. The limiting factor is the number of **different boards**,
  not photos.
* **Re-insert between shots** (pull drawer, re-seat board): this is the variation
  the system meets in use.
* **Few boards (e.g. 5–8)?** Still possible, with honest limits:
  * Use every board both normal and rotated 180° (alignment normalises it, but the
    lighting falls differently), several insertions, LED brightness ±10 %.
  * Make **defect variants** on a few sacrificial boards (remove/shift/swap parts,
    with the company's permission). Each variant is new data — but it is still
    the **same board ID** and must stay in the same split.
  * Evaluate with **leave-one-board-out** cross-validation (train on N−1 boards,
    test on the remaining one, repeat) to get a fairer estimate than a single
    tiny test split.
* **Limitations of many images of one board:** images are highly correlated — the
  model may memorise that board's solder joints, part brands and markings;
  metrics measured on other photos of the *same* board are inflated. That is why
  the split is by board and why test results must come from unseen boards.

### 6.2 External datasets (FICS-PCB, Roboflow Universe, Kaggle)

* **Main model: don't mix them in.** They differ in camera angle, scale (px/mm),
  lighting, labelling convention (body vs pads, what counts as "capacitor") and class
  names. Mixing them shifts the training distribution away from your chamber and can
  *lower* accuracy on PCB X, especially for the rare top-side classes.
* **If you want to try them (optional experiment):**
  1. Map names to our classes (e.g. "R", "res" → `resistor`), drop classes you don't
     use, relabel where conventions differ.
  2. Rescale images so parts have roughly your px/mm.
  3. **Pre-train** on the external data, then **fine-tune on PCB X only**
     (`--model runs/.../external_best.pt`).
  4. Never put external images in validation/test; keep the external model only if
     **validation** mAP of small classes improves vs. the COCO-pretrained baseline.
  5. Check each dataset's licence and cite it.
* COCO-pretrained `yolov8n.pt`/`yolo26n.pt` already supplies general visual
  features (transfer learning) — that is the "external dataset" step, as the PDF says.

### 6.3 Synthetic data and augmentation (fixed chamber)

| Augmentation | Verdict |
|---|---|
| Brightness/contrast small (±20–30 %), small hue/saturation | **Yes** (LED ageing, exposure drift) |
| Translation ±5 %, rotation ±3°, scale ±20 % | **Yes** (residual alignment error) |
| Mosaic (Ultralytics default) | **Yes**, off for the last 10 epochs |
| Slight blur/noise | Optional (small focus drift) |
| Horizontal/vertical flips | **No** — the aligned board is never mirrored |
| Large rotations (90°, arbitrary) | **No** — alignment removes them |
| Perspective/shear | **No** — removed by the warp |
| Random cropping that cuts parts | **No** |
| Synthetic component placement (copy-paste) | **Avoid** in the main study — pasted parts lack real shadows/solder fillets and teach unrealistic cues. A missing-part defect needs no synthetic image anyway (it is simply unlabelled) |

### 6.4 Dataset evaluation
Metrics and the 25/50/75/100 % learning-curve procedure: `D_Testing_and_Validation.md`
(D5, D5b). Tools: `training/validate.py`, `training/learning_curve.py`, notebook
cells 12 and 17.

---

## 7. Part 8 — final technical review

| # | Question | Assessment |
|---|---|---|
| 1 | Architecture feasible? | **Yes.** Every block uses standard, documented tools; the full software chain runs end-to-end on synthetic data in our tests. Real accuracy/speed must be measured. |
| 2 | Hardware appropriate? | **Yes, with two test gates:** EMEET control locking and Arducam focus software. Add level shifter, LED supply, cooler, 27 W PSU, HDMI display. |
| 3 | Camera & lighting need improvement? | **Lighting yes** (diffusers, side-angled bars, matte nest). Cameras: only if the Stage 2 tests fail → Camera Module 3. |
| 4 | YOLOv8n + OpenCV + rules appropriate? | **Yes** — the right split of work: learning only where appearance varies (part type), deterministic geometry and rules where explainability matters. |
| 5 | Fiducial alignment reliable? | **Yes if** ≥ 2 fiducials are visible and the outline is found; reliability is now *measured* (D4) and failures degrade to REVIEW/no verdict, never to PASS. |
| 6 | Dataset plan sufficient? | **Yes if** you get ≥ 15–20 distinct boards incl. defects. With fewer, use leave-one-board-out and state it. |
| 7 | Software maintainable? | **Yes** — config in one file, hardware isolated in `runner.py`, pure functions for vision/rules, 18 unit tests, simulation mode, one installer. |
| 8 | Biggest risks | (1) too few distinct/defective boards; (2) camera settings not lockable (EMEET) / focus software (Arducam); (3) glare & uneven light; (4) recall of the smallest SMD parts; (5) "wrong type" limited to visually different parts; (6) outline detection needs nest contrast; (7) Pi package conflicts (mitigated by `install_pi.sh`) |
| 9 | Implement first | Chamber + cameras + lighting (Stages 1–4) and a **30-image pilot** per side to prove small parts are detectable — before building anything else |
| 10 | Remove to reduce complexity | simultaneous capture · offline 3× augmentation · E-stop, reset, next-board, manual-capture buttons · presence sensor, lock · SATA SSD · 8 GB Pi · denoise/sharpen/histogram equalisation · fiducial YOLO class · standalone executable · external datasets in the main model · OpenCV-only full-screen GUI (Tkinter replaces it) |

### 7.1 Prioritised implementation roadmap

| Week | Milestone | Exit check |
|---|---|---|
| 1 | Buy core parts (A8 order); flash OS; `install_pi.sh`; unit tests pass | D: `pytest` 18 passed |
| 2 | Temporary rig (cardboard/foam-board) at 120 mm; cameras + LEDs working | D1, D2 pass |
| 3 | Camera decision (keep/replace); lighting with diffusers; calibration | D1 stable, RMS < 0.5 px |
| 4 | Board profile + alignment; **30-image pilot per side → label → quick train** | D4 A/B/C pass; small parts detected in pilot |
| 5 | Final chamber + drawer/nest (now that distances are known) | D4 repeated in final chamber |
| 6–7 | Full dataset capture (20–30 boards, defects) + labelling + review | `check_dataset.py` OK |
| 8 | Training (YOLOv8n, YOLO26n), learning curve, model choice on val, NCNN export | D5 on val |
| 9 | Golden references; tune T_low/T_high/tolerances on val boards | D6 pass |
| 10 | GUI, buttons, logging, autostart | D3, D8 |
| 11 | Performance + integration test; **test set once**; time vs manual | D7, D9 |
| 12 | Survey with QC personnel, write Chapter 4, defense demo rehearsal | — |

### 7.2 Recommended final configuration

```
HARDWARE
  Raspberry Pi 5 4 GB · Active Cooler · official 27 W PSU · 64 GB A2 high-endurance microSD
  Bottom (SMD) camera: Camera Module 3 on CAM0 (or Arducam IMX519 if focus control works)
  Top (THT) camera:   EMEET C60E on USB 2.0 if it passes the lock test, else Camera Module 3 on CAM1
  Working distance 110–130 mm, capture 2304×1296 (CM3 binned) / 2560×1440 (EMEET)
  WS2812B 2 × 24 LEDs on GPIO10 (SPI) via 74AHCT125, own 5 V 3 A supply, opal diffusers,
    LED bars along the long sides at 30–45°
  7" HDMI touchscreen · Power button on J2 · START button GPIO17 (+LED GPIO22) · drawer switch GPIO27
  Drawer with removable matte-black 3-D-printed nest, corner tabs, end-stop + detent

SOFTWARE
  Raspberry Pi OS 64-bit (desktop) · venv --system-site-packages · ultralytics 8.4.218 (same on PC/Colab)
  Canvas 1200 × 500 px @ 10 px/mm · CLAHE (2.0, 8×8) · outline + template + fiducial alignment
  YOLOv8n per side (YOLO26n as compared alternative) · top 640 → NCNN 288×640 · bottom 1216 → NCNN 512×1216
  T_low 0.25 / T_high 0.60 (tune on val) · Hungarian matching · rules R1–R8 + S1
  Tkinter GUI · background logging (CSV + JSON + JPEG) · desktop autostart + auto-restart

DATA
  Own chamber images only, labelled on canvases · 70/15/15 split by board · defects in the test set
  ~250 images/side from 20–30 boards · test set used once
```

---

### Sources consulted (Nov 2026)
Ultralytics docs: Raspberry Pi guide, NCNN integration, YOLO26 model page, PyPI
release 8.4.218 · Arducam 16MP IMX519 documentation · EMEET C60E product pages
(EMEET, Adorama, AVL Gear) · rpi_ws281x Pi 5 support wiki and README, rpi5-ws2812
(PyPI) · Raspberry Pi 5 J2 power-button breakout (Raspberry Pi docs / element14) ·
Raspberry Pi 2026 price announcements · Makerlab PH, element14 PH listings ·
Label Studio YOLO export structure (Ultralytics Label Studio integration page).
