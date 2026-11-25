#!/usr/bin/env python3
"""
main.py - start the PCB X inspection appliance.

    python main.py              # real hardware (Raspberry Pi)
    python main.py --simulate   # no hardware: images from sim_images/top|bottom,
                                # dummy LEDs, no GPIO (works on Windows too)
    python main.py --windowed   # not full screen (for development)

Run from the project folder (the folder that contains this file).
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(Path(__file__).resolve().parent)

import config as C                                   # noqa: E402
from storage import setup_app_logging               # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="PCB X inspection")
    ap.add_argument("--simulate", action="store_true", help="run without hardware")
    ap.add_argument("--windowed", action="store_true", help="do not use full screen")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    setup_app_logging(C.LOGS_DIR, logging.DEBUG if args.debug else logging.INFO)
    if args.windowed:
        C.FULLSCREEN = False
    simulate = args.simulate or C.SIMULATE
    logging.info("Starting PCB X inspection (simulate=%s)", simulate)

    from hardware import Inputs
    from inspection.runner import InspectionSystem
    from gui.interface import App

    inputs = Inputs(C.START_BUTTON_GPIO, C.DOOR_SWITCH_GPIO, C.STATUS_LED_GPIO,
                    simulate=simulate)
    system = InspectionSystem(simulate=simulate)
    app = App(system, inputs)
    try:
        app.run()
    finally:
        inputs.close()
        logging.info("Program closed")


if __name__ == "__main__":
    main()
