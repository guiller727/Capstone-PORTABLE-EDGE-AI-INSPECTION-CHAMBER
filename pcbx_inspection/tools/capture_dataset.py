#!/usr/bin/env python3
"""
tools/capture_dataset.py - capture TRAINING images with the real chamber, using
EXACTLY the same alignment + preprocessing as the inspection program.

V2: every image is IDENTIFIED (front/back) and orientation-corrected, then
saved in the folder of the side it shows - so a board inserted flipped or
rotated still lands in the right dataset:
    dataset_capture/canvas/top/      FRONT (Side A) -> label with the top classes
    dataset_capture/canvas/bottom/   BACK  (Side B) -> label with the bottom classes
    dataset_capture/canvas/unidentified/  (before markers exist, or not recognised)

  python tools/capture_dataset.py --board B07 --count 5            # both cameras
  python tools/capture_dataset.py --board B07 --count 3 --note missingR3
  python tools/capture_dataset.py --board B07 --camera upper --side top   # before markers exist
  python tools/capture_dataset.py --from-raw old_raw/ --camera upper

FILE NAMING RULE: names start with the physical board ID (B01, B02, ...).
The dataset split script uses it so one board never appears in both training
and test sets. Write the board ID on the board with a marker.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

import config as C  # noqa: E402
from inspection.profile import Profile  # noqa: E402
from inspection.runner import make_aligners, make_canvas  # noqa: E402
from vision.preprocessing import preprocess_canvas  # noqa: E402
from vision.quality import check_quality  # noqa: E402

OUT = C.PROJECT_DIR / "dataset_capture"


def save_pair(camera, name, raw, aligner, expected_side=None):
    (OUT / "raw" / camera).mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / "raw" / camera / f"{name}.jpg"), raw, [cv2.IMWRITE_JPEG_QUALITY, 95])
    res = aligner.align(raw, expected_side)
    if res.canvas is None:
        print(f"   {camera}: {res.status} - {res.message}")
        return None
    side = res.side if res.usable and res.side else "unidentified"
    (OUT / "canvas" / side).mkdir(parents=True, exist_ok=True)
    canvas = preprocess_canvas(res.canvas, C.PREPROCESS)
    cv2.imwrite(str(OUT / "canvas" / side / f"{name}.jpg"), canvas, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"   {camera}: -> {side:12} ({res.status}, rotation {res.rotation_deg} deg) {res.message}")
    return side


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", help="physical board ID, e.g. B07")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--note", default="", help="e.g. good, missingR3, shiftedC2")
    ap.add_argument("--camera", choices=list(C.CAMERAS) + ["both"], default="both")
    ap.add_argument("--side", choices=["top", "bottom"],
                    help="force the side (only before identification markers exist)")
    ap.add_argument("--from-raw", type=Path, help="re-process saved raw images")
    ap.add_argument("--profile", default=C.ACTIVE_PROFILE)
    args = ap.parse_args()
    prof = Profile(C.MODELS_DIR, args.profile)
    aligners = make_aligners(make_canvas(prof), prof.load_board_profile(), prof.dir)
    cams = list(C.CAMERA_ORDER) if args.camera == "both" else [args.camera]

    if args.from_raw:
        if args.camera == "both":
            ap.error("--from-raw needs --camera upper or --camera lower")
        for p in sorted(args.from_raw.glob("*")):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                print(p.name)
                save_pair(args.camera, p.stem, cv2.imread(str(p)), aligners[args.camera], args.side)
        return
    if not args.board:
        ap.error("--board is required")
    from camera import create_camera
    from lighting import LedController
    opened = {}
    with LedController(C.LIGHTING) as leds:
        try:
            for c in cams:
                opened[c] = create_camera(c, C.CAMERAS[c])
                opened[c].open()
            for i in range(1, args.count + 1):
                input(f"[{i}/{args.count}] seat board {args.board} in the tray, close door, Enter...")
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                for c in cams:
                    leds.light(C.CAMERAS[c].get("led", "top"))
                    time.sleep(C.LED_SETTLE_S)
                    raw = opened[c].capture()
                    leds.all_off()
                    ok, _, why = check_quality(raw, C.QUALITY)
                    if not ok:
                        print(f"   {c}: quality warning: {why}")
                    name = f"{args.board}_{stamp}_n{i:02d}_{c}" + (f"_{args.note}" if args.note else "")
                    save_pair(c, name, raw, aligners[c], args.side)
        finally:
            for c in opened.values():
                c.close()


if __name__ == "__main__":
    main()
