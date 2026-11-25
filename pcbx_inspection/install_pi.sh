#!/usr/bin/env bash
# install_pi.sh - one-time setup of the PCB X inspection software on a
# Raspberry Pi 5 running Raspberry Pi OS (64-bit, with desktop).
#
#   cd ~/PCBX_Capstone/pcbx_inspection
#   chmod +x install_pi.sh run_pcbx.sh
#   ./install_pi.sh
#
# Safe to run again (it skips what is already done).
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HOME/pcbx-venv"

echo "== 1/7 System check"
uname -m | grep -q aarch64 || { echo "Needs 64-bit Raspberry Pi OS (aarch64)"; exit 1; }
grep -E "PRETTY_NAME" /etc/os-release
python3 --version

echo "== 2/7 apt packages"
sudo apt update
sudo apt install -y python3-venv python3-pip python3-picamera2 python3-tk \
    python3-gpiozero python3-lgpio v4l-utils libopenblas0 git

echo "== 3/7 Enable SPI (WS2812B data on GPIO10)"
sudo raspi-config nonint do_spi 0 || true
ls /dev/spidev0.0 >/dev/null 2>&1 && echo "SPI OK" || echo "SPI device appears after reboot"

echo "== 4/7 Virtual environment ($VENV) with access to apt packages"
if [ ! -d "$VENV" ]; then
  python3 -m venv --system-site-packages "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel

echo "== 5/7 Pin numpy to the system version (picamera2 is compiled against it)"
SYS_NUMPY=$(/usr/bin/python3 -c "import numpy; print(numpy.__version__)")
echo "numpy==$SYS_NUMPY" > "$APP_DIR/constraints.txt"
echo "System numpy $SYS_NUMPY"

echo "== 6/7 Python packages (CPU-only PyTorch first, then ultralytics etc.)"
pip install -c "$APP_DIR/constraints.txt" torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu
pip install -c "$APP_DIR/constraints.txt" -r "$APP_DIR/requirements.txt"

echo "== 7/7 Self-test imports"
python - <<'PY'
import importlib
for m in ["numpy", "cv2", "torch", "ultralytics", "ncnn", "scipy", "PIL.ImageTk",
          "tkinter", "spidev", "gpiozero", "picamera2"]:
    try:
        mod = importlib.import_module(m)
        print(f"  OK   {m:12} {getattr(mod, '__version__', '')}")
    except Exception as e:
        print(f"  FAIL {m:12} {e}")
PY
mkdir -p "$APP_DIR/logs" "$APP_DIR/models" "$APP_DIR/references/calibration"
chmod +x "$APP_DIR/run_pcbx.sh"
# write the autostart entry with THIS machine's path (enable it in Stage 14)
sed "s#^Exec=.*#Exec=$APP_DIR/run_pcbx.sh#" "$APP_DIR/deploy/pcbx.desktop" \
    > "$APP_DIR/deploy/pcbx.local.desktop"

cat <<EOF

Done. Next steps:
  * Reboot once (sudo reboot) so SPI is active.
  * Camera check:   rpicam-hello --list-cameras     and    v4l2-ctl --list-devices
  * Arducam IMX519 AUTOFOCUS model only: follow Arducam's guide (dtoverlay=imx519
    in /boot/firmware/config.txt and their libcamera packages). Camera Module 3
    needs nothing extra.
  * Run the unit tests:  source $VENV/bin/activate && cd $APP_DIR && python -m pytest -q tests
  * Start manually:      $APP_DIR/run_pcbx.sh
  * Autostart at boot:   see docs/C_Pi_Software_Roadmap.md (Stage 14)
EOF
