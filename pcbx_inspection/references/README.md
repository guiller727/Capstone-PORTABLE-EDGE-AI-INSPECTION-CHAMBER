# references/

Files created during setup (Stages 6 and 9). Back them up — they ARE your
calibrated system.

| File | Created by | Content |
|---|---|---|
| `calibration/top_camera.json`, `calibration/bottom_camera.json` | `tools/calibrate_camera.py` | lens matrix K, distortion, RMS error |
| `board_profile.json` | `tools/build_board_profile.py` | fiducial positions (mm) per side, template paths, optional fixed homography |
| `templates/top_ok.png`, `top_flipped.png`, `bottom_ok.png`, `bottom_flipped.png` | `tools/build_board_profile.py` | small grey reference images for side/orientation check |
| `golden_top.json`, `golden_bottom.json` | `tools/build_golden_reference.py` | expected components with mean position and tolerance |

`examples/` contains **illustrative** files that show the format only. The
coordinates in them are invented — never use them for real inspection.

**When must they be rebuilt?**

* Camera moved, refocused or replaced → calibration, board profile, golden references.
* New model trained → golden references (detections centres shift slightly).
* Lighting changed → templates (board profile) and check quality thresholds.
