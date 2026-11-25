#!/usr/bin/env python3
"""
tools/capture_dataset.py - capture TRAINING images with the real chamber, using
EXACTLY the same alignment + preprocessing as the inspection program.

  python tools/capture_dataset.py --board B07 --count 5
      -> 5 insertions of board B07. After each capture you re-seat the board
         (pull the tray out and push it back) and press Enter.
  python tools/capture_dataset.py --board B07 --count 3 --note missingR3
  python tools/capture_dataset.py --from-raw old_raw_images/ --side bottom

Output (dataset_capture/):
  raw/<side>/B07_20261125_101530_n01.jpg        raw frames (keep! for re-processing)
  canvas/<side>/B07_20261125_101530_n01.jpg     -> upload THESE to Label Studio

FILE NAMING RULE: the name MUST start with the physical board ID (B01, B02,
...). The dataset split script uses it so one board never appears in both
training and test sets. Write the board ID on the board with a marker.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

import config as C  # noqa: E402
from inspection.runner import SIDES, make_aligners, make_canvas  # noqa: E402
from vision.preprocessing import preprocess_canvas  # noqa: E402
from vision.quality import check_quality  # noqa: E402

OUT = C.PROJECT_DIR / "dataset_capture"


def save_pair(side, name, raw, aligner):
    (OUT / "raw" / side).mkdir(parents=True, exist_ok=True)
    (OUT / "canvas" / side).mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / "raw" / side / f"{name}.jpg"), raw, [cv2.IMWRITE_JPEG_QUALITY, 95])
    res = aligner.align(raw)
    if not res.usable:
        print(f"   {side}: NOT aligned ({res.status}: {res.message}) - canvas not saved")
        return False
    canvas = preprocess_canvas(res.canvas, C.PREPROCESS)
    cv2.imwrite(str(OUT / "canvas" / side / f"{name}.jpg"), canvas,
                [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"   {side}: {res.status} - {res.message}")
    return True


def from_raw(folder: Path, side: str):
    aligners = make_aligners(make_canvas())
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".png", ".jpeg"))
    for p in files:
        raw = cv2.imread(str(p))
        print(p.name)
        save_pair(side, p.stem, raw, aligners[side])


def live(board, count, note, sides):
    from camera import create_camera
    from lighting import LedController
    aligners = make_aligners(make_canvas())
    cams = {}
    with LedController(C.LIGHTING) as leds:
        try:
            for s in sides:
                cams[s] = create_camera(s, C.CAMERAS[s])
                cams[s].open()
            for i in range(1, count + 1):
                input(f"[{i}/{count}] seat board {board} in the tray, close door, Enter...")
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                for s in sides:
                    leds.light(s)
                    time.sleep(C.LED_SETTLE_S)
                    raw = cams[s].capture()
                    leds.all_off()
                    ok, m, why = check_quality(raw, C.QUALITY)
                    if not ok:
                        print(f"   {s}: quality warning: {why}")
                    name = f"{board}_{stamp}_n{i:02d}" + (f"_{note}" if note else "")
                    save_pair(s, name, raw, aligners[s])
        finally:
            for c in cams.values():
                c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", help="physical board ID, e.g. B07")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--note", default="", help="e.g. good, missingR3, shiftedC2")
    ap.add_argument("--side", choices=["top", "bottom", "both"], default="both")
    ap.add_argument("--from-raw", type=Path, help="re-process saved raw images")
    args = ap.parse_args()
    sides = list(SIDES) if args.side == "both" else [args.side]
    if args.from_raw:
        if args.side == "both":
            ap.error("--from-raw needs --side top or --side bottom")
        from_raw(args.from_raw, args.side)
    else:
        if not args.board:
            ap.error("--board is required")
        live(args.board, args.count, args.note, sides)


if __name__ == "__main__":
    main()
