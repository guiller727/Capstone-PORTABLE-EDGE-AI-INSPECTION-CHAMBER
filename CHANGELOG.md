# Changelog

## V2 — two Camera Module 3, PCB identification, profiles, tolerance UI

Base: the V1 `PCBX_Capstone_Package.zip`. Capstone title, objectives, scope,
golden-reference approach and PASS / FAIL / REVIEW classification unchanged.
Full explanation: `docs/01_V2_Evaluation_and_Changes.md` (§4 lists every module).

### Hardware
- Cameras: **2 × Raspberry Pi Camera Module 3 Standard** (CAM0 lower, CAM1 upper). EMEET/Arducam dropped; USB-webcam code kept as optional fallback.
- Storage: 32 GB high-endurance microSD evaluated as sufficient.
- Wiring, GPIO, LEDs, buttons: unchanged. Docs updated (cable type and orientation, camera tests).

### New
- `vision/identification.py` — FRONT/BACK identification from printed markings (front first), 0/180° decision, optional barcode marker, whole-board fallback; unknown/ambiguous → REVIEW.
- `inspection/profile.py` + `models/pcb_x/` — PCB profile folder (metadata, golden reference, board profile, `top/` and `bottom/` models; NCNN preferred, `.pt` fallback).
- Dual mode (one insertion, flipped insertion handled automatically) and flip mode (one camera, prompt, same-side detection, FINISH).
- GUI: Settings window (profile/model status, inspection settings, tolerance editor, golden JSON editor, restore backup), History window (HTML report, CSV export), live preview, side info, flagged-parts table, NOT READY list.
- `config/settings.json` — GUI-editable, validated settings.
- `storage/report.py` — HTML inspection report.
- `tools/check_profile.py` — deployment check incl. sample inference.
- Tests: `tests/test_v2_scenarios.py` (15 required cases + extras), `tests/test_gui_smoke.py`.
- Docs: `01_V2_Evaluation_and_Changes`, `PCB_IDENTIFICATION_AND_ORIENTATION`, `GOLDEN_REFERENCE_AND_TOLERANCES`, `DATASET_LABELING`, `MODEL_TRAINING`, `MODEL_INTEGRATION`, `TROUBLESHOOTING`.

### Modified
- Cameras renamed by position (`upper`/`lower`); one aligner per camera that knows both sides.
- Golden reference schema v2: both sides in one file, thresholds per side, default/class/component tolerances incl. X/Y, `required` flag, validation, atomic save with backups and revision; revision + hash recorded in every result.
- Decision engine: per-axis tolerance, optional parts, R9 ambiguous match, S2 side-level REVIEW reasons (side not identified, orientation ambiguous, capture unusable, model missing, conflicting identification).
- Runner never crashes on missing camera/model/golden — collects problems (NOT READY).
- Model loading validated (exists, loads, class list equals profile).
- Front class list: + `film_capacitor`, + `ceramic_capacitor`, − `terminal_block` (matches the real board; **confirm with your adviser**).
- `capture_dataset.py` sorts images by identified side; `build_board_profile.py` creates identification markers; `build_golden_reference.py` writes into the profile with safe save; `export.py --profile-dir` installs trained models; notebook packages in profile layout.
- Result CSV: new columns (cameras, mode, profile, golden revision/hash, notes); an existing V1 CSV is kept as `results_v1.csv`.

### Removed
- `references/examples/` (V1 per-side formats) → replaced by `models/pcb_x/*.example.json`.
- `tests/test_alignment_synthetic.py` → replaced by the V2 scenario tests (same scenarios plus 90°, barcode, flipped).

### Not included on purpose
- No trained model, no real golden reference, no real board profile: they must be created from your own PCB X images (`*.example.json` show the format with rough positions).

## V1
Initial package: Raspberry Pi application, training workflow, hardware/testing documentation.
