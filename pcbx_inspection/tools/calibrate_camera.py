#!/usr/bin/env python3
"""
tools/calibrate_camera.py - Stage 6a: lens-distortion calibration (once per camera).

Print a checkerboard (9 x 6 INNER corners, 8 mm squares - fits the ~140 x 80 mm
view) and glue it flat on stiff card. Place it on the tray at the board's
height. Capture 15-20 images: centre, corners, edges, slightly tilted.

  python tools/calibrate_camera.py --side bottom --capture 20
  python tools/calibrate_camera.py --side top --folder my_checkerboard_photos/

Output: references/calibration/<side>_camera.json  (+ undistorted preview).
PASS criteria: RMS reprojection error < 0.5 px (< 1.0 px acceptable for webcams);
straight board edges look straight in the preview near the image corners.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

import config as C  # noqa: E402
from vision.calibration import Undistorter, calibrate_from_images, save_calibration  # noqa: E402


def capture_images(side, n):
    from camera import create_camera
    from lighting import LedController
    import time
    imgs = []
    out = C.PROJECT_DIR / "test_output" / "calibration" / side
    out.mkdir(parents=True, exist_ok=True)
    with LedController(C.LIGHTING) as leds:
        cam = create_camera(side, C.CAMERAS[side])
        cam.open()
        try:
            for i in range(n):
                input(f"[{i + 1}/{n}] move the checkerboard, then press Enter...")
                leds.light(side)
                time.sleep(C.LED_SETTLE_S)
                img = cam.capture()
                leds.all_off()
                ok, _ = cv2.findChessboardCorners(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                                                  PATTERN)
                print("   corners found" if ok else "   corners NOT found - retake")
                cv2.imwrite(str(out / f"calib_{i:02d}.jpg"), img)
                if ok:
                    imgs.append(img)
        finally:
            cam.close()
    return imgs


PATTERN = (9, 6)


def main():
    global PATTERN
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--capture", type=int, help="capture N images now")
    ap.add_argument("--folder", type=Path, help="use existing images")
    ap.add_argument("--cols", type=int, default=9)
    ap.add_argument("--rows", type=int, default=6)
    ap.add_argument("--square-mm", type=float, default=8.0)
    args = ap.parse_args()
    PATTERN = (args.cols, args.rows)
    if args.folder:
        imgs = [cv2.imread(str(p)) for p in sorted(args.folder.glob("*"))
                if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
    elif args.capture:
        imgs = capture_images(args.side, args.capture)
    else:
        ap.error("use --capture N or --folder DIR")
    calib, n = calibrate_from_images(imgs, PATTERN, args.square_mm)
    path = C.CALIBRATION_DIR / C.CAMERAS[args.side]["calibration_file"]
    save_calibration(path, calib)
    print(f"Used {n} images. RMS reprojection error = {calib['rms_px']:.3f} px")
    print(f"Saved {path}")
    und = Undistorter(path)
    prev = C.PROJECT_DIR / "test_output" / "calibration" / f"{args.side}_undistorted.jpg"
    prev.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(prev), cv2.hconcat([imgs[0], und.apply(imgs[0])]))
    print(f"Before/after preview: {prev}")


if __name__ == "__main__":
    main()
