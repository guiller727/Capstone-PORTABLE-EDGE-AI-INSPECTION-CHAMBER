#!/usr/bin/env python3
"""
tools/build_board_profile.py - Stage 6b (V2): teach the system how to IDENTIFY
each side of PCB X and where its fiducials (mounting holes) are.

Writes models/<profile>/board_profile.json + templates/ for side top (FRONT)
or bottom (BACK). Run it once per side with a known-good board inserted in
the NORMAL orientation (as in your "PCB X SIDE A/B NORMAL ORIENTATION" slides).

STEP 1 - look at the straightened board and its round candidates (holes):
    python tools/build_board_profile.py --side top --camera upper --capture
    -> test_output/profile/top_canvas.jpg      (board, 10 px/mm, mm grid every 10 mm)
       test_output/profile/top_candidates.jpg  (numbered round candidates)
    If the canvas is upside-down compared with your NORMAL orientation, add --rotate180.

STEP 2 - store the mounting holes as fiducials (pick their numbers):
    python tools/build_board_profile.py --side top --camera upper --capture --keep 0 3 5 7

STEP 3 - add identification markers (rectangles in mm, read off the mm grid):
    python tools/build_board_profile.py --side top --camera upper --capture \
        --marker sharp_logo 28.5 41.5 9 3  --marker part_number 47 42 16 2.5
    python tools/build_board_profile.py --side bottom --camera lower --capture \
        --marker t1_white_block 37.5 17 8 22  --marker t1_label 37.5 3.5 5 3
    (x_mm y_mm = CENTRE of the rectangle, then width and height in mm)
    Optional barcode area (if your boards carry a barcode sticker):
        --barcode barcode 37.5 17 10 22
    Interactive alternative (needs a monitor): --select-markers

STEP 4 - check: python tools/test_alignment.py --camera upper --images <folder>

Choose markers that are (a) printed on EVERY unit (silkscreen, not a per-unit
sticker or the masking tape "S4"), (b) high-contrast, (c) not symmetric under a
180 deg rotation. The serial-number sticker "MTI 5V PWR21100004" changes from
unit to unit - do not use it as a template.

Use --image FILE instead of --capture to work from a saved raw image.
--save-fixed-homography stores the outline homography of THIS camera in its
calibration file (fallback when the board edge is hard to see).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import config as C  # noqa: E402
from inspection.profile import Profile  # noqa: E402
from inspection.runner import make_canvas  # noqa: E402
from vision import fiducials as fid  # noqa: E402
from vision.board_alignment import BoardAligner, _template_prep  # noqa: E402
from vision.calibration import Undistorter, save_calibration  # noqa: E402
from vision.identification import crop_template  # noqa: E402
from vision.preprocessing import to_gray_normalized  # noqa: E402

OUT = C.PROJECT_DIR / "test_output" / "profile"


def grab(camera):
    import time
    from camera import create_camera
    from lighting import LedController
    with LedController(C.LIGHTING) as leds:
        cam = create_camera(camera, C.CAMERAS[camera])
        cam.open()
        try:
            leds.light(C.CAMERAS[camera].get("led", "top"))
            time.sleep(C.LED_SETTLE_S)
            return cam.capture()
        finally:
            leds.all_off()
            cam.close()


def mm_grid(canvas, geo):
    vis = canvas.copy()
    for x in range(0, int(geo.bw) + 1, 10):
        px = int((x + geo.m) * geo.ppm)
        cv2.line(vis, (px, 0), (px, geo.h), (0, 255, 255), 1)
        cv2.putText(vis, str(x), (px + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
    for y in range(0, int(geo.bh) + 1, 10):
        py = int((y + geo.m) * geo.ppm)
        cv2.line(vis, (0, py), (geo.w, py), (0, 255, 255), 1)
        cv2.putText(vis, str(y), (2, py - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
    return vis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True,
                    help="top = FRONT (Side A), bottom = BACK (Side B)")
    ap.add_argument("--camera", choices=list(C.CAMERAS), default="upper")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--capture", action="store_true")
    src.add_argument("--image", type=Path)
    ap.add_argument("--profile", default=C.ACTIVE_PROFILE)
    ap.add_argument("--rotate180", action="store_true")
    ap.add_argument("--keep", type=int, nargs="*", help="candidate numbers that are fiducials")
    ap.add_argument("--marker", nargs=5, action="append", metavar=("NAME", "X", "Y", "W", "H"))
    ap.add_argument("--barcode", nargs=5, action="append", metavar=("NAME", "X", "Y", "W", "H"))
    ap.add_argument("--select-markers", action="store_true", help="draw rectangles with the mouse")
    ap.add_argument("--clear-markers", action="store_true")
    ap.add_argument("--min-markers", type=int, default=1)
    ap.add_argument("--save-fixed-homography", action="store_true")
    args = ap.parse_args()

    prof = Profile(C.MODELS_DIR, args.profile)
    pdir = prof.dir
    ppath = prof.board_profile_path
    geo = make_canvas(prof)

    raw = grab(args.camera) if args.capture else cv2.imread(str(args.image))
    if raw is None:
        sys.exit("Could not read image")
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / f"{args.side}_raw.jpg"), raw)
    cal_path = C.CALIBRATION_DIR / C.CAMERAS[args.camera]["calibration_file"]
    und = Undistorter(cal_path)
    base = BoardAligner(args.camera, geo, {}, C.ALIGN, und)
    img = und.apply(raw)
    H, corners, how = base.coarse_homography(img)
    if H is None:
        sys.exit(f"Board outline not found ({how}). Improve contrast between the board and the "
                 "tray nest (matte black nest recommended) or check ALIGN outline_* settings.")
    if args.rotate180:
        H = geo.rot180() @ H
    canvas = cv2.warpPerspective(img, H, (geo.w, geo.h))
    cv2.imwrite(str(OUT / f"{args.side}_canvas.jpg"), mm_grid(canvas, geo))

    data = json.loads(ppath.read_text()) if ppath.exists() else {"board": prof.board_name}
    sp = data.setdefault("sides", {}).setdefault(args.side, {})
    sp["min_markers"] = args.min_markers
    tdir = pdir / "templates"
    tdir.mkdir(exist_ok=True)

    # whole-board template (fallback identification)
    t = _template_prep(canvas, C.ALIGN["template_size"]).astype(np.uint8)
    cv2.imwrite(str(tdir / f"{args.side}_whole.png"), t)
    sp["template"] = f"templates/{args.side}_whole.png"

    # fiducial candidates (mounting holes)
    lo, hi = C.ALIGN["fiducial_d_range_mm"]
    cands = fid.find_candidates(to_gray_normalized(canvas), geo.ppm, lo, hi)
    vis = canvas.copy()
    for i, c in enumerate(cands):
        x, y, r = int(c["x_px"]), int(c["y_px"]), int(c["d_px"] / 2) + 3
        cv2.circle(vis, (x, y), r, (0, 0, 255), 2)
        cv2.putText(vis, str(i), (x + r, y - r), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    cv2.imwrite(str(OUT / f"{args.side}_candidates.jpg"), vis)
    print(f"{len(cands)} round candidates - see {OUT / f'{args.side}_candidates.jpg'}")
    for i, c in enumerate(cands[:40]):
        print(f"  [{i:2d}] x={c['x_px'] / geo.ppm - geo.m:7.2f} mm  y={c['y_px'] / geo.ppm - geo.m:6.2f} mm"
              f"  d={c['d_px'] / geo.ppm:.2f} mm  circularity={c['circularity']:.2f}")
    if args.keep is not None:
        sp["fiducials_mm"] = [[round(cands[k]["x_px"] / geo.ppm - geo.m, 3),
                               round(cands[k]["y_px"] / geo.ppm - geo.m, 3),
                               round(cands[k]["d_px"] / geo.ppm, 3)] for k in args.keep]
        print(f"Stored {len(sp['fiducials_mm'])} fiducials")

    # identification markers
    if args.clear_markers:
        sp["markers"] = []
    markers = {m["name"]: m for m in sp.get("markers", [])}
    rects = [(m[0], *map(float, m[1:]), "template") for m in (args.marker or [])]
    rects += [(m[0], *map(float, m[1:]), "barcode") for m in (args.barcode or [])]
    if args.select_markers:
        while True:
            r = cv2.selectROI("drag a marker rectangle, ENTER = ok, ESC = done", canvas, False)
            if r[2] == 0:
                break
            name = input("marker name: ").strip() or f"marker{len(rects) + 1}"
            x, y = (r[0] + r[2] / 2) / geo.ppm - geo.m, (r[1] + r[3] / 2) / geo.ppm - geo.m
            rects.append((name, x, y, r[2] / geo.ppm, r[3] / geo.ppm, "template"))
        cv2.destroyAllWindows()
    for name, x, y, w, h, typ in rects:
        m = {"name": name, "type": typ, "x_mm": round(x, 2), "y_mm": round(y, 2),
             "w_mm": round(w, 2), "h_mm": round(h, 2),
             "min_score": C.ALIGN["marker_min_score"], "search_mm": C.ALIGN["marker_search_mm"]}
        if typ == "template":
            crop = crop_template(canvas, x, y, w, h, geo.ppm, geo.m)
            rel = f"templates/{args.side}_{name}.png"
            cv2.imwrite(str(pdir / rel), crop)
            m["template"] = rel
            # self-check: is the marker unique on this canvas and NOT matched at 180 deg?
            g = to_gray_normalized(canvas)
            s0 = cv2.minMaxLoc(cv2.matchTemplate(g, crop, cv2.TM_CCOEFF_NORMED))[1]
            s180 = cv2.minMaxLoc(cv2.matchTemplate(cv2.rotate(g, cv2.ROTATE_180), crop,
                                                   cv2.TM_CCOEFF_NORMED))[1]
            print(f"  marker {name}: self-score {s0:.2f}, best score on 180-deg view {s180:.2f}"
                  + ("   <-- WARNING: also matches when rotated; choose a less symmetric area"
                     if s180 > C.ALIGN["marker_min_score"] else ""))
        markers[name] = m
    sp["markers"] = list(markers.values())
    if not sp["markers"]:
        print("NOTE: no identification markers yet - add them with --marker (STEP 3).")

    if args.save_fixed_homography:
        calib = json.loads(cal_path.read_text()) if cal_path.exists() else {}
        calib["fixed_homography"] = H.tolist()
        save_calibration(cal_path, calib)
        print(f"Fixed homography stored in {cal_path}")
    ppath.write_text(json.dumps(data, indent=2))
    print(f"Saved {ppath}")


if __name__ == "__main__":
    main()
