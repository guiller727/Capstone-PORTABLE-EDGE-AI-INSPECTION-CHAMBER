# Package C — PCB X inspection software (Raspberry Pi 5) — V2

Architecture, stage-by-stage bring-up and deployment are explained in
`../docs/C_Pi_Software_Roadmap.md`. This file is the quick reference.

## Install on the Raspberry Pi

```bash
# Raspberry Pi OS (64-bit) with desktop, freshly updated
sudo apt update && sudo apt full-upgrade -y && sudo reboot
git clone <your-repo-url> ~/PCBX_Capstone        # or copy the folder with a USB stick
cd ~/PCBX_Capstone/pcbx_inspection
chmod +x install_pi.sh run_pcbx.sh
./install_pi.sh                                    # ~10-20 min
sudo reboot
source ~/pcbx-venv/bin/activate && cd ~/PCBX_Capstone/pcbx_inspection
python -m pytest -q tests                          # expect: 39 passed (+1 GUI test with a display)
```

## Files you must create before the first real inspection

| Needed | How | Stage |
|---|---|---|
| Settings for your cameras/LEDs | edit `config.py` (`# TUNE` lines) | 2–5 |
| `references/calibration/upper_camera.json`, `lower_camera.json` | `tools/calibrate_camera.py --camera upper/lower` | 6 |
| `models/pcb_x/board_profile.json` + `templates/` (markers, holes) | `tools/build_board_profile.py` | 6 |
| `models/pcb_x/top/` and `bottom/` (`best.pt`, `best_ncnn_model/`) | training notebook / `training/export.py --profile-dir` | 7 |
| `models/pcb_x/golden_reference.json` | `tools/build_golden_reference.py --side top/bottom` | 9 |

Check everything at once: `python tools/check_profile.py` (prints READY or the problems).
Until all files exist the GUI starts in **NOT READY** and lists what is missing.

## Everyday commands

| Command | Purpose |
|---|---|
| `./run_pcbx.sh` | start the appliance (auto-restart on crash) |
| `python main.py --windowed` | start in a window (development) |
| `python main.py --simulate --windowed` | no hardware: images from `sim_images/upper` and `sim_images/lower` (needs a ready profile) — works on Windows |
| `python main.py --mode flip` | one camera, operator flips the board |
| `python tools/test_cameras.py` | camera stability / `--focus-sweep` / `--list` / `--both-streaming` |
| `python tools/check_profile.py` | profile + model + golden readiness, sample inference |
| `python tools/test_leds.py` | LED test (`--interactive`) |
| `python tools/test_inputs.py` | START button and drawer switch |
| `python tools/calibrate_camera.py --camera lower --capture 20` | lens calibration |
| `python tools/build_board_profile.py --side top --camera upper --capture [--keep ..] [--marker ...]` | identification markers + holes |
| `python tools/test_alignment.py --camera upper --images DIR --expect top` | identification / orientation / alignment accuracy |
| `python tools/capture_dataset.py --board B07 --count 5` | training images (raw + canvas) |
| `python tools/build_golden_reference.py --side bottom --images DIR --seed-label FILE` | golden reference (one side) |
| `python tools/run_offline.py --images test_set --truth test_set/truth.csv` | decisions on saved upper/lower images + confusion table |
| `python tools/benchmark.py [--full 30]` | speed, RAM, temperature |

Run tools from this folder. Outputs go to `test_output/`, inspection logs to `logs/`.

## Dependencies

apt: `python3-picamera2 python3-tk python3-gpiozero python3-lgpio v4l-utils` ·
pip (venv): `torch` (CPU build), `ultralytics==8.4.218`, `ncnn`, `spidev`,
`scipy`, `psutil`, `pillow`, `pytest`. All installed by `install_pi.sh`.

## Developing on Windows

`pip install ultralytics==8.4.218 scipy pillow pytest` in a venv, then
`python -m pytest -q tests` and `python main.py --simulate --windowed` work
without the Pi-only packages (picamera2, spidev, gpiozero are imported only
when real hardware is used).
