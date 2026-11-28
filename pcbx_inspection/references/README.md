# references/  (camera-specific data)

V2: everything that belongs to a **PCB** moved to the profile folder
`models/<profile>/` (golden reference, identification markers, fiducials,
templates). This folder keeps only what belongs to a **camera**:

| File | Created by | Content |
|---|---|---|
| `calibration/upper_camera.json` | `tools/calibrate_camera.py --camera upper` | lens matrix K, distortion, RMS error, optional `fixed_homography` |
| `calibration/lower_camera.json` | `tools/calibrate_camera.py --camera lower` | same for the lower camera |

Recalibrate when a camera is moved, refocused or replaced. Recalibrating
overwrites the file, so re-run `tools/build_board_profile.py
--save-fixed-homography` afterwards if you use the fixed homography.
