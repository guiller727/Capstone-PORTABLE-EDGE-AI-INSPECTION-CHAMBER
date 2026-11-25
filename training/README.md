# Package B — AI training (YOLOv8n baseline, YOLO26n optional)

Everything needed to go from **chamber photos → labelled dataset → trained
models → NCNN files on the Raspberry Pi**. The only files you supply are your
images and your annotations.

```
training/
├── README.md                     ← this file
├── requirements.txt
├── PCBX_YOLO_Training.ipynb      ← Google Colab notebook (also runs locally)
├── common.py                     ← shared helpers (class lists, YAML writer)
├── configs/hyp_top.yaml          ← training settings, top model
├── configs/hyp_bottom.yaml       ← training settings, bottom model
├── label_studio/labeling_config_top.xml / _bottom.xml
├── dataset_template/             ← empty folder structure + data YAMLs
├── tools/prepare_dataset.py      ← Label Studio export → split by board → dataset
├── tools/check_dataset.py        ← verify labels, leakage, previews
├── tools/make_dataset_zip.py     ← safe zip for Colab
├── tools/make_demo_dataset.py    ← fake data to rehearse the pipeline
├── train.py  validate.py  export.py  learning_curve.py
```

> **Verified in our build environment (x86 CPU, ultralytics 8.4.218):** demo
> dataset → `prepare_dataset.py` → `check_dataset.py` → `train.py` (YOLOv8n and
> YOLO26n) → `validate.py` → `export.py` (rectangular NCNN 512×1216 and 288×640)
> → NCNN prediction, and the complete notebook executed top-to-bottom. **Not
> verified:** accuracy on your real images, Colab GPU timing, and NCNN speed on
> the Raspberry Pi 5 — those must be measured by you.

---

## 1. Dataset workflow (the part that went wrong before)

The key idea: **you label the same straightened "canvas" images that the Pi
feeds to YOLO** (1200 × 500 px, 10 px/mm, CLAHE applied). Training and
inspection images are then produced by the same code, as the PDF requires.

```
Pi: tools/capture_dataset.py  ──►  dataset_capture/canvas/top/*.jpg
                                    dataset_capture/canvas/bottom/*.jpg
        │  (copy to your PC)
        ▼
Label Studio: 2 projects (top, bottom) ──► Export "YOLO with Images" (zip)
        ▼
python tools/prepare_dataset.py --export <zip> --side top    (and bottom)
python tools/check_dataset.py --side top                     (and bottom)
python tools/make_dataset_zip.py      ──►  pcbx_dataset.zip  ──► Google Drive
```

### 1.1 File naming rule (needed for the board-wise split)

Every image name must **start with the physical board ID**: `B07_20261125_101530_n02.jpg`.
`capture_dataset.py` does this for you (`--board B07`). Write the ID on each
board with a marker. Optional suffix notes like `_missingR3` help you later.

### 1.2 Label Studio setup

1. `pip install label-studio` → `label-studio start` (opens in the browser).
2. Create **two projects**: *PCBX Top* and *PCBX Bottom*.
3. *Settings → Labeling Interface → Code*: paste
   `label_studio/labeling_config_top.xml` (or `_bottom.xml`).
4. *Import*: drag in the canvas images of that side.
5. Label (rules below). *Export → **YOLO with Images***. Keep the zip as it is.

### 1.3 Labelling rules (write them in your methodology)

| Situation | What to do |
|---|---|
| Normal component | Tight box around the **component body incl. its terminations**, not the copper pads |
| **Missing** component | **No box.** There is nothing to label. The golden reference + rules detect "missing". |
| **Shifted / misplaced** component | Box **where it actually is**, with its real class. The rules measure the shift. |
| Wrong component fitted (e.g. diode where a resistor belongs) | Label what it **really is** (diode). The rules report WRONG TYPE. |
| Tombstoned / lifted part | Label it with its class (it is present); position/shape issues are a delimitation unless you add a class later |
| Part partly hidden at the image edge | Label if ≥ 50 % visible |
| Unsure what a part is | Ask the partner company / check the BOM — never guess |
| Fiducials, holes, silkscreen | Do **not** label (fiducials are found by OpenCV) |

### 1.4 Check your annotations

`tools/check_dataset.py` stops on structural errors and writes
`_previews/*.jpg` with boxes drawn. **Open 10–20 previews** — wrong class IDs
or shifted boxes are obvious there. Also: one person labels, another person
reviews 10 % of images (report the agreement in your paper).

`prepare_dataset.py` fixes two classic Label Studio problems automatically:
the class order in `classes.txt` (alphabetical in some versions) is **remapped
by name** to our order, and the hash prefix Label Studio adds to file names
(`3f2a9c1d-B07_...`) is removed.

### 1.5 Split 70/15/15 by board

```bash
python tools/prepare_dataset.py --export top_export.zip --side top \
       --val-boards B16 B17 B18 --test-boards B19 B20 B21
```
Choose test boards yourself so they include **defective boards**. Use the
**same board IDs for both sides**. Without `--*-boards`, the script splits
randomly by board (seed 42).

---

## 2. One model or two? (PDF proposes two — keep two)

| | Two models (recommended) | One model, 11 classes |
|---|---|---|
| Image size | top 640, bottom 1216 — each side only pays for what it needs | everything at 1216 → top inference ~3× slower for no benefit |
| Classes | disjoint (no top part ever appears on the bottom) | model must also learn "this class never appears in this view" |
| Errors | a bottom-model mistake cannot affect top results | coupled |
| Work | 2 trainings, 2 files | 1 training |
| RAM on Pi | 2 small models (≈ 6–12 MB each as NCNN) | 1 model |

## 3. Training parameters — evaluation of the PDF values

| Parameter | PDF | Final | What it does / why |
|---|---|---|---|
| model | yolov8n | **yolov8n** baseline, yolo26n second experiment | n = smallest/fastest. Try `s` only if `n` misses parts on **validation** |
| imgsz top | 640 | **640** | Long side of the canvas → 640 px (5.3 px/mm). Large THT parts are ≥ 30 px. Fine. |
| imgsz bottom | 1024 | **1216** | Canvas is 1200 px wide; 1216 keeps every pixel (0805 ≈ 20 × 12 px). 1024 shrinks it to 8.5 px/mm. Cost is controlled by the **rectangular export** (512 × 1216 instead of 1216 × 1216). Compare both on validation if time allows. |
| epochs | 150 | **150** (upper limit) | Number of passes over the data. With ~200 images this is normal. |
| patience | 30 | **30** | **Early stopping**: stops if validation fitness has not improved for 30 epochs and keeps `best.pt`. Yes, use it. |
| fliplr | 0 | **0** | Mirroring is unrealistic (the aligned board is never mirrored). Correct. |
| degrees | 3 | **3** | Alignment leaves < 1° error; 3° is a safe margin. Correct. |
| translate | 0.05 | **0.05** | Small shifts; correct. |
| scale | 0.2 | **0.2** | px/mm is fixed by the warp; small scale changes only. Correct. |
| mosaic | (default 1.0) | **1.0**, `close_mosaic=10` | Mixes 4 images; useful for small datasets; turned off for the last 10 epochs so the model finishes on realistic images. |
| hsv_h / s / v | (default .015/.7/.4) | **0.01 / 0.4 / 0.3** | Reduced: lighting is controlled and part colours carry information. |
| batch | — | top 16, bottom 8 | Lower if "CUDA out of memory". |

**Preventing overfitting:** split by board (most important), keep the
validation set untouched by training, early stopping, moderate augmentation,
more *different boards* rather than more photos of the same board, and watch
`results.png`: if training loss keeps falling while validation loss rises, you
are overfitting.

**Small-object evaluation:** look at the per-class P/R/mAP of `resistor` and
`smd_capacitor` (they are the small classes) printed by `validate.py`, at the
confusion matrix (missed small parts appear in the *background* column), and
— most important — at the **component-level results of the full system on the
test boards** (`pcbx_inspection/tools/run_offline.py`). A part missed by YOLO
becomes a MISSING → FAIL, so recall of small classes directly drives false
rejects.

**Offline 3× augmentation (PDF, Section 5):** don't. Ultralytics already
augments on-the-fly every epoch; adding pre-generated copies mostly inflates
the dataset and makes the 70/15/15 bookkeeping error-prone.

## 4. YOLOv8n → YOLO26n

Facts checked in the Ultralytics docs (Nov 2026): YOLO26 was released in
January 2026; it removes DFL and offers an NMS-free (end-to-end) head; NCNN
export supports YOLOv8, YOLO11 and YOLO26 detection models; Ultralytics
benchmarks YOLO26n with NCNN on a Raspberry Pi 5 CPU.

| Question | Answer |
|---|---|
| Same dataset / images? | **Yes** |
| Same YOLO label format (`class cx cy w h`)? | **Yes** |
| Same folder structure & data YAML? | **Yes** |
| Same notebook / scripts? | **Yes** — change one value: `BASE_MODEL = "yolo26n.pt"` (notebook) or `--model yolo26n.pt` (scripts) |
| Necessary changes | ultralytics **≥ 8.4** on PC/Colab **and** on the Pi (we pin 8.4.218 everywhere) |
| Optional changes | run name suffix to keep both experiments; re-tune `T_LOW`/`T_HIGH` on validation (confidence scales differ between models); rebuild golden references with the new model |
| Export process changes? | **No** — `format="ncnn"`, same rectangular `imgsz`. We exported YOLO26n to NCNN at 288 × 640 and ran prediction successfully in our test environment |
| Pi deployment still possible? | **Yes** — the Pi code loads any Ultralytics NCNN folder; class-name check is the same |

Choose between YOLOv8n and YOLO26n **on the validation set** (mAP@50 of small
classes, then speed measured on the Pi with `tools/benchmark.py`). Report
both in Chapter 4 — that comparison is a good contribution.

---

## 5. Google Colab (recommended for training)

1. Upload `pcbx_dataset.zip` to `MyDrive/PCBX/`.
2. Open `PCBX_YOLO_Training.ipynb` in Colab (*File → Upload notebook*), select
   *T4 GPU*, run all cells. Settings are only in cell 2.
3. Cell 16 downloads `pcbx_models_<model>_<date>.zip` (also saved in Drive):
   `models/top_best_ncnn_model/`, `models/bottom_best_ncnn_model/`, `best.pt`
   files, and the evidence (curves, confusion matrices, metrics JSON).
4. Copy the two model folders to `pcbx_inspection/models/` on the Pi.

## 6. Local training on Windows (same files, same dataset folder)

**With an NVIDIA GPU**

```powershell
# 1. Install Python 3.12 (python.org, tick "Add to PATH") and VS Code (+ Python extension)
# 2. Open PowerShell in the training folder
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
# 3. PyTorch with CUDA: copy the exact command from https://pytorch.org/get-started/locally/
#    (Windows, Pip, Python, CUDA). It looks like:
#    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 4. Same steps as Colab
python tools/prepare_dataset.py --export top_export.zip --side top
python tools/check_dataset.py --side top
python train.py --side top
python train.py --side bottom
python validate.py --side top --weights weights_out/top_yolov8n_best.pt
python export.py  --side top --weights weights_out/top_yolov8n_best.pt
```

**Without an NVIDIA GPU:** install the CPU build
(`pip install torch torchvision`) — everything works, but expect hours
instead of minutes. Use it for `--epochs 3` pipeline tests and for
validation/export; do the real training on Colab. (`train.py` lowers the batch
size automatically on CPU.) Apple Silicon Macs use `device=mps` automatically.

The notebook also runs locally in VS Code/Jupyter from the `training/` folder:
it detects "not Colab" and uses `training/pcbx_dataset.zip` and `training/runs/`.

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `images not found` | Use our scripts; they write absolute-path YAMLs (`_resolved_*.yaml`) |
| `RuntimeError: ... freeze_support` / DataLoader worker crash (Windows) | Scripts use `workers=0` on Windows and the `if __name__ == "__main__"` guard |
| `CUDA out of memory` | `--batch 4` (bottom) |
| `torch.cuda.is_available()` is False with a GPU | You installed the CPU wheel — reinstall with the CUDA command from pytorch.org; update the NVIDIA driver |
| Class names wrong after export | Label Studio label values must match `common.py` exactly; `prepare_dataset.py` stops on unknown names |
| mAP ≈ 0 after many epochs | Look at `_previews/`; usually wrong class remap or boxes on wrong images |
| Great val mAP, bad on new boards | Leakage — same board in train and val. `check_dataset.py` reports it |
| NCNN export fails on Windows | Run `export.py` on Colab or directly on the Pi (same command) |
