# Troubleshooting (V2)

First step for any problem: look at the GUI's **NOT READY** list or status
line, then `logs/app.log`, then run `python tools/check_profile.py`.

## Cameras
| Symptom | Cause / fix |
|---|---|
| `rpicam-hello --list-cameras` shows 0 or 1 camera | power off; re-seat ribbon: **Pi 5 needs the 22-pin "Standard–Mini" cable**, metal contacts face the **Ethernet port** side on the Pi 5; latch fully closed |
| "CSI camera 1 not detected" | only one camera found; check the second cable; confirm numbering with `python tools/test_cameras.py --list` and swap `camera_num` in `config.py` if upper/lower are reversed |
| warning "camera … is ov5647/imx219, expected imx708" | wrong camera model on that connector |
| image blurry | `python tools/test_cameras.py --camera lower --focus-sweep 4 14 0.5`, put the best `LensPosition` in `config.py`; camera must be ≥ 10 cm from the board |
| brightness changes between shots | auto-exposure still on — check `ExposureTime`, `AwbEnable: False` in `config.py`; run the stability test |
| "image unusable after 3 attempts" | quality limits in `config.QUALITY` too strict for your lighting, or LED not lighting that side |
| upper image shows the bottom LED light | `led` mapping in `CAMERAS` or strips wired in the other order |
| `ImportError: picamera2` in the venv | venv must be created with `--system-site-packages` (`install_pi.sh` does it) |
| numpy / simplejpeg errors when importing picamera2 | numpy in the venv differs from the system one → re-run `install_pi.sh` (it pins numpy) |

## Identification / orientation
| Symptom | Fix |
|---|---|
| always "PCB side not identified" | markers not configured (`board_profile.json` missing) → `tools/build_board_profile.py`; or `min_score` too high; or markers covered by tape |
| "orientation ambiguous" | chosen marker looks the same rotated 180° — pick a less symmetric area (the tool prints the 180° score) |
| front identified as back or vice versa | marker rectangle taken from the wrong side image; rebuild that side |
| "Board not detected" | not enough contrast between board and nest (use matte black), board partly outside the view, `outline_*` limits in `config.ALIGN` |
| alignment "coarse" → REVIEW | holes not found: check `fiducials_mm` positions/diameter, `fiducial_d_range_mm`, focus; hole hidden by the nest |

## Models
| Symptom | Fix |
|---|---|
| "No usable top model" | put `best.pt` or `best_ncnn_model/` in `models/pcb_x/top/` (`docs/MODEL_INTEGRATION.md`) |
| "classes differ" | wrong side's model, or `metadata.json` classes not equal to training classes |
| "file too small - not a trained model" | an empty/placeholder `best.pt` |
| "Could not load …" | ultralytics version on the Pi ≠ training version (pin 8.4.218) |
| slow (> 1 s per side) | `.pt` in use instead of NCNN (see Settings > Profile & model); no Active Cooler (`vcgencmd get_throttled` ≠ 0x0) |

## Golden reference / tolerances
| Symptom | Fix |
|---|---|
| NOT READY "golden_reference.json is invalid" | the message lists each problem (line/field); fix in Settings > Golden JSON or restore a backup |
| "has no BACK section" | build it: `tools/build_golden_reference.py --side bottom ...` |
| good boards FAIL as MISPLACED | tolerance tighter than repeatability (check `std_*` values), or golden built with a different model/camera setup → rebuild |
| many AMBIGUOUS | two same-class parts closer than their tolerances add up → reduce those tolerances |

## LEDs and inputs
| Symptom | Fix |
|---|---|
| LEDs dark | `ls /dev/spidev0.0` (enable SPI, reboot); 5 V supply on; common ground |
| random colours / flicker | missing common ground or level shifter (74AHCT125); 330 Ω in data line |
| wrong colours | `color_order` in `config.LIGHTING` |
| START pressed twice per press | bouncing button; `bounce_time` in `hardware/inputs.py` |

## Training (more in `training/README.md`)
| Symptom | Fix |
|---|---|
| "images not found" | use the scripts (absolute-path YAML) |
| mAP ≈ 0 | wrong labels/class mapping → check `_previews/` |
| great val, bad on new boards | leakage — same board in train and val |
| CUDA out of memory | `--batch 4` |
