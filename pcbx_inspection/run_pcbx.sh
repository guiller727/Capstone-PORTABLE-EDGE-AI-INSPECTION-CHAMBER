#!/usr/bin/env bash
# run_pcbx.sh - start the inspection program; restart it automatically if it
# crashes (an appliance should recover without someone opening an IDE).
# A normal "Exit" from the GUI (exit code 0) stops the loop.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HOME/pcbx-venv"
cd "$APP_DIR" || exit 1
# shellcheck disable=SC1091
source "$VENV/bin/activate"
while true; do
  python main.py "$@"
  code=$?
  if [ $code -eq 0 ]; then
    exit 0
  fi
  echo "$(date) main.py exited with code $code - restarting in 3 s" >> "$APP_DIR/logs/restarts.log"
  sleep 3
done
