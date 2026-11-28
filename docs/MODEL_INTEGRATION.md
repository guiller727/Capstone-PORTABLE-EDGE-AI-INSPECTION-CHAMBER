# Putting a trained model into the inspection system (V2)

No trained model is shipped with the repository — it must come from your own
labelled PCB X images. This guide starts when training is finished.

## 0. `.pt` or NCNN on the Raspberry Pi?

| Format | Pi 5 speed (Ultralytics benchmark, YOLO26n, 640 px, network only) | Use |
|---|---|---|
| PyTorch `best.pt` | ~299 ms/image | **works** on the Pi; keep it as the master copy and fallback |
| ONNX | ~126 ms/image | no advantage over NCNN here — not used |
| **NCNN** `best_ncnn_model/` | **~67 ms/image**, same accuracy | **used when present** |

So: export to NCNN, but keep `best.pt` next to it. The application loads
`<side>/best_ncnn_model/` if it exists (`config.PREFER_NCNN = True`), otherwise
`<side>/best.pt`. Our own (non-Pi) test confirmed both formats load through
the same code; **measure the real Pi speed** with `tools/benchmark.py --compare-pt`.

## 1. Find the trained files
| Where you trained | File |
|---|---|
| `training/train.py` | `training/weights_out/top_yolov8n_best.pt` (copy of `runs/top/top_yolov8n/weights/best.pt`) |
| Colab notebook | the downloaded `pcbx_models_<model>_<date>.zip` → `pcb_x/top/best.pt` + `pcb_x/top/best_ncnn_model/` (also in Drive `MyDrive/PCBX/`) |

Use `best.pt` (best validation epoch), not `last.pt`.

## 2. Install into the profile
**From the training PC (recommended):**
```powershell
cd training
python export.py --side top    --weights weights_out/top_yolov8n_best.pt    --profile-dir ..\pcbx_inspection\models\pcb_x
python export.py --side bottom --weights weights_out/bottom_yolov8n_best.pt --profile-dir ..\pcbx_inspection\models\pcb_x
```
**From the Colab zip:** copy `pcb_x/top/` and `pcb_x/bottom/` into
`pcbx_inspection/models/pcb_x/` (next to `metadata.json`).

Result:
```
pcbx_inspection/models/pcb_x/
├── metadata.json        classes + "model": {"ncnn": "top/best_ncnn_model", "pt": "top/best.pt",
│                                            "imgsz": [288, 640], "pt_imgsz": 640}
├── top/best.pt
├── top/best_ncnn_model/{model.ncnn.param, model.ncnn.bin, metadata.yaml}
├── bottom/best.pt
└── bottom/best_ncnn_model/...
```
The class names in `metadata.json` must equal the model's class names, in the
same order. `export.py` checks this; the application checks it again when it loads.

## 3. Copy to the Pi
```bash
# from the PC (replace user/IP), or use a USB stick / git
scp -r pcbx_inspection/models/pcb_x user@<pi-ip>:~/PCBX_Capstone/pcbx_inspection/models/
```
(`.gitignore` allows `best.pt` in `models/`; NCNN folders are small too.)

## 4. Golden reference and board profile
Models alone are not enough: the profile also needs
`board_profile.json` (identification markers + holes, `tools/build_board_profile.py`)
and `golden_reference.json` (`tools/build_golden_reference.py`, which **uses
the installed model**). After installing a *new* model, rebuild the golden
reference: detection centres can shift slightly between models.

## 5. Test that it loads and runs
```bash
cd ~/PCBX_Capstone/pcbx_inspection && source ~/pcbx-venv/bin/activate
python tools/check_profile.py
python tools/check_profile.py --image dataset_capture/raw/upper/B07_..._n01_upper.jpg --side top
```
Expected: `[OK]` lines for metadata, golden, markers, both models ("loaded …,
classes match, dummy inference … ms"), the sample image aligned and the
detected boxes drawn in `test_output/check_profile_sample.jpg`, then `READY`.

Typical errors: "No usable top model" → files not in `top/`; "classes differ"
→ wrong side's model or `metadata.json` not updated; "Could not load" →
ultralytics version differs from training (use 8.4.218 on both).

## 6. Run the application
```bash
./run_pcbx.sh                 # or: python main.py --windowed
```
The header shows the profile and golden revision; **Settings > Profile &
model** shows which format each side uses. Inspect known-good and known-defect
boards, then follow `docs/D_Testing_and_Validation.md`.

## 7. Replacing a model later
1. Train → `export.py --profile-dir …` (overwrites `top/` or `bottom/`).
2. Rebuild that side's golden reference, re-check thresholds on validation boards.
3. `tools/check_profile.py` → restart the app (or Settings > Profile & model > Use this profile).
4. Keep the old folder (e.g. copy `models/pcb_x` to `models/pcb_x_2026-12-10`) to roll back.

A second PCB type = a second profile folder with its own metadata, models,
golden reference and markers; select it in Settings.
