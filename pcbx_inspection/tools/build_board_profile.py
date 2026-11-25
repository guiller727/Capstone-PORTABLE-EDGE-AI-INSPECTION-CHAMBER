#!/usr/bin/env python3
"""
tools/build_board_profile.py - Stage 6b: teach the system what PCB X looks like.

Creates/updates references/board_profile.json with, for each side:
  * fiducial positions in mm (from the built-in fiducial marks)
  * a reference template of the correct side (orientation + "is it PCB X?")
  * a reference template of the FLIPPED board (wrong-side detection)
  * optionally a fixed homography (fallback if the board edge is hard to see)

Procedure (do it for side = top and side = bottom):
  1. Insert a known-good board the normal way. Run:
       python tools/build_board_profile.py --side top --capture
     Open test_output/profile/top_candidates.jpg. Fiducial candidates are
     numbered. If the canvas is upside-down compared with how you want to
     define the board, run again with --rotate180.
  2. Choose the numbers that are real fiducials and save them + template:
       python tools/build_board_profile.py --side top --capture --keep 0 3
  3. Flip the board over (other side towards this camera) and run:
       python tools/build_board_profile.py --side top --capture --flipped
  4. Repeat for --side bottom.
Use --image FILE instead of --capture to work from a saved raw image.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import config as C  # noqa: E402
from inspection.runner import make_canvas  # noqa: E402
from vision import fiducials as fid  # noqa: E402
from vision.board_alignment import BoardAligner, _template_prep  # noqa: E402
from vision.calibration import Undistorter  # noqa: E402
from vision.preprocessing import to_gray_normalized  # noqa: E402

OUT = C.PROJECT_DIR / "test_output" / "profile"
PROFILE = C.REFERENCES_DIR / "board_profile.json"


def grab(side):
    import time
    from camera import create_camera
    from lighting import LedController
    with LedController(C.LIGHTING) as leds:
        cam = create_camera(side, C.CAMERAS[side])
        cam.open()
        try:
            leds.light(side)
            time.sleep(C.LED_SETTLE_S)
            return cam.capture()
        finally:
            leds.all_off()
            cam.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--capture", action="store_true")
    src.add_argument("--image", type=Path)
    ap.add_argument("--keep", type=int, nargs="*", help="candidate numbers that are fiducials")
    ap.add_argument("--flipped", action="store_true", help="board is inserted flipped")
    ap.add_argument("--rotate180", action="store_true")
    ap.add_argument("--save-fixed-homography", action="store_true")
    args = ap.parse_args()

    raw = grab(args.side) if args.capture else cv2.imread(str(args.image))
    if raw is None:
        sys.exit("Could not read image")
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / f"{args.side}_raw.jpg"), raw)

    canvas_geo = make_canvas()
    und = Undistorter(C.CALIBRATION_DIR / C.CAMERAS[args.side]["calibration_file"])
    aligner = BoardAligner(args.side, canvas_geo, {}, C.ALIGN, und)   # outline only
    img = und.apply(raw)
    H, corners, how = aligner.coarse_homography(img)
    if H is None:
        sys.exit(f"Board outline not found ({how}). Improve contrast between board and "
                 "tray nest, or check ALIGN outline_* settings.")
    if args.rotate180:
        H = canvas_geo.rot180() @ H
    canvas = cv2.warpPerspective(img, H, (canvas_geo.w, canvas_geo.h))
    cv2.imwrite(str(OUT / f"{args.side}{'_flipped' if args.flipped else ''}_canvas.jpg"), canvas)

    profile = json.loads(PROFILE.read_text()) if PROFILE.exists() else {}
    profile.setdefault("board", C.BOARD_NAME)
    profile["canvas"] = {"px_per_mm": C.PX_PER_MM, "margin_mm": C.CANVAS_MARGIN_MM,
                         "width_px": canvas_geo.w, "height_px": canvas_geo.h,
                         "board_w_mm": C.BOARD_WIDTH_MM, "board_h_mm": C.BOARD_HEIGHT_MM}
    sp = profile.setdefault("sides", {}).setdefault(args.side, {})
    tdir = C.REFERENCES_DIR / "templates"
    tdir.mkdir(parents=True, exist_ok=True)

    if args.flipped:
        t = _template_prep(canvas, C.ALIGN["template_size"]).astype(np.uint8)
        cv2.imwrite(str(tdir / f"{args.side}_flipped.png"), t)
        sp["template_flipped"] = f"templates/{args.side}_flipped.png"
        PROFILE.write_text(json.dumps(profile, indent=2))
        print(f"Saved flipped template for {args.side}.")
        return

    gray = to_gray_normalized(canvas)
    cands = fid.find_candidates(gray, C.PX_PER_MM)
    vis = canvas.copy()
    for i, c in enumerate(cands):
        x, y, r = int(c["x_px"]), int(c["y_px"]), int(c["d_px"] / 2) + 3
        cv2.circle(vis, (x, y), r, (0, 0, 255), 2)
        cv2.putText(vis, str(i), (x + r, y - r), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    cv2.imwrite(str(OUT / f"{args.side}_candidates.jpg"), vis)
    print(f"{len(cands)} round candidates - see {OUT / f'{args.side}_candidates.jpg'}")
    for i, c in enumerate(cands[:40]):
        x_mm = c["x_px"] / C.PX_PER_MM - C.CANVAS_MARGIN_MM
        y_mm = c["y_px"] / C.PX_PER_MM - C.CANVAS_MARGIN_MM
        print(f"  [{i:2d}] x={x_mm:7.2f} mm  y={y_mm:6.2f} mm  d={c['d_px'] / C.PX_PER_MM:.2f} mm"
              f"  circularity={c['circularity']:.2f}")

    if args.keep is None:
        print("\nRun again with --keep N N ... to store fiducials and the template.")
        return
    fids = []
    for k in args.keep:
        c = cands[k]
        fids.append([round(c["x_px"] / C.PX_PER_MM - C.CANVAS_MARGIN_MM, 3),
                     round(c["y_px"] / C.PX_PER_MM - C.CANVAS_MARGIN_MM, 3),
                     round(c["d_px"] / C.PX_PER_MM, 3)])
    if len(fids) < 2:
        print("WARNING: fewer than 2 fiducials - fine alignment will be unavailable.")
    sp["fiducials_mm"] = fids
    t = _template_prep(canvas, C.ALIGN["template_size"]).astype(np.uint8)
    cv2.imwrite(str(tdir / f"{args.side}_ok.png"), t)
    sp["template_ok"] = f"templates/{args.side}_ok.png"
    if args.save_fixed_homography:
        sp["fixed_homography"] = H.tolist()
    PROFILE.write_text(json.dumps(profile, indent=2))
    print(f"Saved {len(fids)} fiducials and template for {args.side} in {PROFILE}")


if __name__ == "__main__":
    main()
