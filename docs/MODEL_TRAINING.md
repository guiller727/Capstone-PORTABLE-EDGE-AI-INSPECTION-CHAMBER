# Training the YOLO models — beginner guide (V2)

Two models: **front** (`--side top`) and **back** (`--side bottom`). Same
scripts on Windows, Linux and Google Colab. Command reference and
troubleshooting: `training/README.md`. Dataset: `docs/DATASET_LABELING.md`.

## 1. Which YOLO and which size
| Choice | Recommendation | Why |
|---|---|---|
| Version | **YOLOv8n** as the baseline (as in your PDF); **YOLO26n** as the comparison experiment | both use the same dataset, labels, folders and scripts; both export to NCNN for the Pi |
| Size | **n (nano)** | runs on the Pi 5 CPU in ~0.1 s per side; try `s` only if `n` misses parts on validation |
| Base weights | COCO-pretrained (`yolov8n.pt`, downloaded automatically) | transfer learning: the model already knows edges/shapes |

## 2. Training computer
| Option | Notes |
|---|---|
| **Google Colab (free T4 GPU)** | easiest; `training/PCBX_YOLO_Training.ipynb` |
| Windows PC with NVIDIA GPU (≥ 4 GB VRAM) | same speed class as Colab |
| PC without NVIDIA GPU | works (CPU), many times slower; fine for 3-epoch tests |
| Raspberry Pi | **not** for training |

## 3. Windows set-up (once)
```powershell
# Python 3.12 from python.org (tick "Add python.exe to PATH"), VS Code + Python extension
cd C:\...\PCBX_Capstone\training
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1           # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
# PyTorch: copy the command from https://pytorch.org/get-started/locally/
#   with GPU, e.g.:  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
#   without GPU:     pip install torch torchvision
pip install -r requirements.txt      # ultralytics==8.4.218 (same version as on the Pi)
python -c "import torch, ultralytics; print(torch.cuda.is_available(), ultralytics.__version__)"
```

## 4. Train
```powershell
python tools/make_demo_dataset.py --side top        # optional: 5-minute rehearsal with fake data
python train.py --side top                           # front model (imgsz 640)
python train.py --side bottom                        # back model  (imgsz 1216)
python train.py --side bottom --model yolo26n.pt     # comparison
```
Results: `runs/<side>/<side>_<model>/` (`weights/best.pt`, `results.csv`,
`results.png`, confusion matrices). A copy of `best.pt` goes to `weights_out/`.

### Settings (from `configs/hyp_top.yaml`, `hyp_bottom.yaml`)
| Setting | Front | Back | Meaning |
|---|---|---|---|
| `imgsz` | 640 | 1216 | image size the network sees. The canvas is 1200 px wide; the back keeps full resolution so an 0805 part stays ~20 × 12 px |
| `epochs` | 150 | 150 | maximum passes over the data |
| `patience` | 30 | 30 | **early stopping**: stop if validation does not improve for 30 epochs; `best.pt` is the best epoch |
| `batch` | 16 | 8 | images per step; lower (8/4) if "CUDA out of memory" |
| `fliplr/flipud` | 0 | 0 | no mirroring (the real images are never mirrored) |
| `degrees, translate, scale` | 3, 0.05, 0.2 | same | small geometric changes = residual alignment error |
| `hsv_h/s/v` | 0.01/0.4/0.3 | same | small colour/brightness changes = lighting drift |
| `mosaic`, `close_mosaic` | 1.0, 10 | same | combines 4 images (helps small datasets); off for the last 10 epochs |

Typical time on a T4: front ~10–20 min, back ~30–60 min for ~150 images. [ESTIMATE]

## 5. Evaluate
```powershell
python validate.py --side top --weights weights_out/top_yolov8n_best.pt              # validation set
python validate.py --side top --weights weights_out/top_yolov8n_best.pt --split test # ONCE, at the end
python learning_curve.py --side bottom                                              # enough data?
```

### What the numbers mean
| Term | Plain meaning | For this project |
|---|---|---|
| **Precision** | of all boxes the model drew, the share that were real parts of the right class | low precision → EXTRA/WRONG_TYPE → REVIEW/FAIL on good boards |
| **Recall** | of all real parts, the share the model found | **most important**: a missed part becomes MISSING → FAIL (false reject) |
| **F1** | balance of precision and recall (2PR/(P+R)) | one number per class |
| **mAP50** | mean Average Precision; a box counts as correct if it overlaps the label by ≥ 50 % (IoU ≥ 0.5) | main detection score; aim ≥ 0.95 per class in this controlled chamber |
| **mAP50-95** | mAP averaged over IoU 0.50 … 0.95 | how *tight* boxes are — matters for position accuracy |
| **Confusion matrix** | table: true class vs predicted class (+ "background") | shows which classes are mixed up (e.g. resistor ↔ smd_capacitor) and missed parts (background column) |
| **Training loss** | error on training images (box, class, DFL parts) | should fall steadily |
| **Validation loss** | error on validation images | should fall and flatten; **rising while training loss falls = overfitting** |
| **Learning curve** | val mAP50 vs number of training images (25/50/75/100 %) | flat at the end → enough data |

`results.png` shows the losses and metrics per epoch; `BoxPR_curve.png` the
precision–recall trade-off; `val_batch*_pred.jpg` example predictions — look
at these images, not only numbers.

### Choosing between models and thresholds
1. Compare candidates (v8n vs 26n, 1024 vs 1216) on **validation** only:
   recall and mAP50 of the small classes first, then speed on the Pi
   (`tools/benchmark.py`).
2. Set `t_low` / `t_high` in the golden reference using validation boards:
   `t_low` low enough that real parts are never ignored; `t_high` where wrong
   classes become rare.
3. Freeze everything, then run the test split **once** and report it.

## 6. Export for the Raspberry Pi
```powershell
python export.py --side top    --weights weights_out/top_yolov8n_best.pt    --profile-dir ..\pcbx_inspection\models\pcb_x
python export.py --side bottom --weights weights_out/bottom_yolov8n_best.pt --profile-dir ..\pcbx_inspection\models\pcb_x
```
This creates the NCNN model (rectangular input 288 × 640 / 512 × 1216),
checks it against the `.pt`, copies **both** into the profile and updates
`metadata.json`. Next: `docs/MODEL_INTEGRATION.md`.
