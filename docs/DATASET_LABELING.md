# Dataset collection and labelling — beginner guide (V2)

Goal: a dataset that teaches YOLO to find PCB X's components **as the chamber
sees them**. One PCB model, two sides → two datasets, two models:

| Side | Also called | Dataset folder | Classes |
|---|---|---|---|
| FRONT | Side A, `top` | `training/datasets/pcbx_top` | electrolytic_cap, film_capacitor, ceramic_capacitor, varistor, fuse, inductor, transformer, connector |
| BACK | Side B, `bottom` | `training/datasets/pcbx_bottom` | resistor, smd_capacitor, diode, ic8 |

The names `top`/`bottom` are kept from V1 so the existing scripts and notebook
work unchanged. (Class list change from V1: see `docs/01_V2_Evaluation_and_Changes.md` §2.)

---

## A. Capturing images

### A1. Always use the chamber and the capture tool
```bash
cd ~/PCBX_Capstone/pcbx_inspection && source ~/pcbx-venv/bin/activate
python tools/capture_dataset.py --board B07 --count 5
```
Each insertion produces one image per camera. The tool **identifies** the side,
corrects the orientation, warps to the 1200 × 500 px canvas, applies CLAHE —
exactly like the inspection — and saves:

```
dataset_capture/raw/upper|lower/B07_..._n01_upper.jpg   raw (keep for re-processing)
dataset_capture/canvas/top/B07_..._n01_lower.jpg        -> label in the FRONT project
dataset_capture/canvas/bottom/B07_..._n01_upper.jpg     -> label in the BACK project
dataset_capture/canvas/unidentified/...                  -> check why (before markers exist: use --side)
```
Before identification markers exist (first days), capture one side at a time
with `--camera upper --side top`.

### A2. Board IDs (prevents leakage)
Write **B01, B02, …** on every physical board with a marker. File names start
with that ID (`--board B07`). Every image of one board — including its defect
variants — must stay in the same split (train *or* val *or* test).

### A3. How many images? (realistic for one PCB model)
Every image contains **all** parts of that side (15 front, 21 back), so few
images already give many labelled objects.

| Phase | Boards | Insertions per board | Images per side | Labelled objects |
|---|---|---|---|---|
| **Pilot** (week 4) | 5–6 | 5 | ~30 | ~450 front / ~630 back |
| **First full set** | 12–15 | 8–10 | ~120–150 | ~2,000 / ~3,000 |
| **Expand only if needed** | 20–30 | 8–10 | ~250 (PDF target) | ~3,750 / ~5,250 |

Decide whether to expand with the **learning curve** (`training/learning_curve.py`,
notebook cell 17): if validation mAP@50 still rises by > 2 points between 75 %
and 100 % of the data, or a class has recall < 0.95, add images — **new boards
first**, more photos of the same boards second.

### A4. What to vary (and what not)
| Vary | How | Why |
|---|---|---|
| Insertion | pull the drawer, re-seat the board between shots | position/tilt variation the system will meet |
| Orientation | normal and rotated 180° in the tray | different lighting angle on parts |
| Side up | also insert boards **flipped** (dual mode) | the front is then seen by the **lower** camera → camera variety |
| Brightness | LED brightness 0.5 / 0.6 / 0.7 (Settings) | LED ageing, exposure drift |
| Defects | with permission: remove, shift (~1 mm), swap a part | rare situations; keep variants in the board's split |
| Do NOT vary | room light (drawer closed), camera distance, focus, mirror images | they never change during inspection |

---

## B. Labelling with Label Studio (already used in V1)

### B1. Install and start (Windows, in the training venv)
```powershell
pip install label-studio
label-studio start          # opens http://localhost:8080
```
Create an account (local only).

### B2. Two projects
1. **Create Project** → name *PCBX Front (top)*.
2. **Labeling Setup → Custom template → Code**: paste
   `training/label_studio/labeling_config_top.xml`. Save.
3. **Data Import**: drag the images from `dataset_capture/canvas/top/`.
4. Repeat for *PCBX Back (bottom)* with `labeling_config_bottom.xml` and `canvas/bottom/`.

The label names in the XML are the class names. Do not rename them in Label Studio.

### B3. Drawing boxes
* Press the hotkey (1, 2, 3 …) for the class, drag a rectangle, repeat.
* Zoom with the mouse wheel for SMD parts.
* Box = **component body including its terminations/leads where visible**, tight
  (1–2 px margin), not the copper pads, not the silkscreen outline.
* Every instance of every class, every image. A missed box teaches the model that the part is "background".

| Situation | What to do |
|---|---|
| Part missing (defect board) | draw **nothing** there |
| Part shifted | box where it **is**, correct class |
| Wrong part fitted | label what it **is** |
| Part partly outside the canvas | label if ≥ 50 % visible |
| Not sure what it is | check the BOM / ask the company — never guess |
| Holes, silkscreen, SHARP logo, T1 block, barcode, solder joints of front parts | **no box** |
| D8 (large DPAK-style diode) | `diode` |
| JMP02 wire jumper | no box (not in the class list) |

**Small SMD parts (0805 ≈ 20 × 12 px):** zoom to 200–400 %, keep the box on
the body edges, be consistent between images; if a part is unreadable because
of glare, fix the lighting rather than guessing.

### B4. Export
Project → **Export → "YOLO with Images"** → zip. Keep it as it is.

### B5. Convert, split, check
```powershell
cd training
python tools/prepare_dataset.py --export front_export.zip --side top --val-boards B13 B14 --test-boards B15 B16 B17
python tools/prepare_dataset.py --export back_export.zip  --side bottom --val-boards B13 B14 --test-boards B15 B16 B17
python tools/check_dataset.py --side top
python tools/check_dataset.py --side bottom
python tools/make_dataset_zip.py          # -> pcbx_dataset.zip for Colab
```
`prepare_dataset.py` remaps Label Studio's class order by **name**, removes the
hash prefix Label Studio adds to file names, and splits **by board**. Use the
**same** board IDs for val/test on both sides, and put defective boards in the
test set. Open 10–20 images in `datasets/pcbx_*/_previews/` — wrong boxes are obvious there.

### B6. Folder layout and `data.yaml`
```
training/datasets/pcbx_top/
├── images/train  images/val  images/test     (*.jpg)
├── labels/train  labels/val  labels/test     (*.txt, one line per box)
├── pcbx_top.yaml                              (data.yaml - written by the tools)
└── split_report.csv
```
A label line: `class_id x_center y_center width height`, all 0–1 relative to
the image, e.g. `6 0.575 0.440 0.209 0.489` (= transformer).

```yaml
# pcbx_top.yaml
train: images/train
val: images/val
test: images/test
names:
  0: electrolytic_cap
  1: film_capacitor
  2: ceramic_capacitor
  3: varistor
  4: fuse
  5: inductor
  6: transformer
  7: connector
```
The scripts also write `_resolved_pcbx_top.yaml` with an absolute `path:` —
that avoids the common "images not found" error.

### B7. Common labelling mistakes
1. Boxes on the copper pads instead of the part.
2. Forgetting a few small parts per image (very common, very harmful).
3. Inconsistent box tightness between labellers → agree on a rule; one person
   labels, another reviews 10 %.
4. Two classes for the same thing (e.g. "cap" and "electrolytic_cap").
5. Labelling the silkscreen designator text.
6. The same board in train and test (leakage) → `check_dataset.py` catches it.
7. Labelling raw camera images instead of canvases → wrong scale for the Pi.

### Alternatives
**Roboflow** (web): easy, exports "YOLOv8" format directly — but images are
uploaded to the cloud (ask the company). Put its export through
`prepare_dataset.py` only if its folder looks like Label Studio's; otherwise
arrange `images/` + `labels/` by hand per split. **CVAT** also exports YOLO
format. The rest of the workflow is identical.

## C. External datasets
Not mixed into the main model (different cameras, scale, labels). Optional
pre-training experiment only — see `docs/00_Technical_Review.md` §6.2.
