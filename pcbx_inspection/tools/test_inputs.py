#!/usr/bin/env python3
"""
tools/test_inputs.py - check the START button, door switch and status LED.

  python tools/test_inputs.py      (Ctrl+C to stop)

PASS criteria: every press prints exactly ONE "START pressed" line (no
bounce), door state follows the door, status LED blinks then stays on.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C  # noqa: E402
from hardware import Inputs  # noqa: E402


def main():
    io = Inputs(C.START_BUTTON_GPIO, C.DOOR_SWITCH_GPIO, C.STATUS_LED_GPIO)
    count = {"n": 0}

    def pressed():
        count["n"] += 1
        print(f"START pressed ({count['n']})")

    io.on_start(pressed)
    io.set_status_led("busy")
    time.sleep(2)
    io.set_status_led("ready")
    last = None
    try:
        while True:
            d = io.door_closed()
            if d != last:
                print("Door", "CLOSED" if d else "OPEN")
                last = d
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        io.close()


if __name__ == "__main__":
    main()
