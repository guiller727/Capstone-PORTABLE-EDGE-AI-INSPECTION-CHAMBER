#!/usr/bin/env python3
"""
tools/test_alignment.py - Stage 6c / Package D "identification + orientation +
fiducial testing" (V2).

Runs identification and alignment on raw images of ONE camera and reports,
per image: status, identified side, orientation correction, marker scores,
fiducials found and residual. With many insertions of the SAME board it also
reports repeatability (how much the holes move in the canvas).

  python tools/test_alignment.py --camera upper --images test_raw/front_normal --expect top
  python tools/test_alignment.py --camera upper --images test_raw/front_rot180 --expect top
  python tools/test_alignment.py --camera upper --images test_raw/back_up      --expect bottom
  python tools/test_alignment.py --camera lower --images test_raw/other_board  --expect unknown

--expect: top | bottom | unknown | ambiguous | no_board
PASS criteria (suggested): 100 % expected result per set, mean fiducial
residual < 0.15 mm, repeatability std < 0.10 mm.
"""
import argparse
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import config as C  # noqa: E402
from inspection.profile import Profile  # noqa: E402
from inspection.runner import make_aligners, make_canvas  # noqa: E402
from vision import fiducials as fid  # noqa: E402
from vision.preprocessing import to_gray_normalized  # noqa: E402


def outcome(r):
    if r.usable and r.side:
        return r.side
    return {"unknown_board": "unknown", "ambiguous": "ambiguous"}.get(r.status, r.status)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", choices=list(C.CAMERAS), required=True)
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--expect", help="top | bottom | unknown | ambiguous | no_board")
    ap.add_argument("--profile", default=C.ACTIVE_PROFILE)
    args = ap.parse_args()
    prof = Profile(C.MODELS_DIR, args.profile)
    geo = make_canvas(prof)
    aligner = make_aligners(geo, prof.load_board_profile(), prof.dir, [args.camera])[args.camera]
    out = C.PROJECT_DIR / "test_output" / "alignment" / args.camera
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in args.images.glob("*") if p.suffix.lower() in (".jpg", ".png"))
    results, rms, fid_pos = [], [], []
    for p in files:
        r = aligner.align(cv2.imread(str(p)))
        o = outcome(r)
        results.append(o)
        marks = " ".join(f"{m['name']}={m['score']:.2f}{'*' if m['found'] else ''}"
                         for m in (r.identification or {}).get("markers", [])[:4])
        print(f"{p.name:42} {o:10} {r.status:13} rot={r.rotation_deg:3d} "
              f"fid={r.fiducials_found}/{r.fiducials_expected} "
              f"rms={'-' if r.fiducial_rms_mm is None else f'{r.fiducial_rms_mm:.3f}'}  {marks}")
        if r.canvas is not None:
            cv2.imwrite(str(out / p.name), r.canvas)
        if r.fiducial_rms_mm is not None and r.usable and r.side:
            rms.append(r.fiducial_rms_mm)
            m = fid.locate_fiducials(to_gray_normalized(r.canvas), aligner.fiducials_for(r.side),
                                     geo.ppm, geo.m, 1.5)
            fid_pos.append([f["found_px"] for f in m])
    print(f"\n{len(files)} images: " + ", ".join(f"{s}={results.count(s)}" for s in sorted(set(results))))
    if args.expect:
        hit = results.count(args.expect)
        print(f"Expected '{args.expect}': {hit}/{len(files)} = {hit / max(1, len(files)) * 100:.1f} %")
    if rms:
        print(f"Fiducial residual: mean {st.mean(rms):.3f} mm, max {max(rms):.3f} mm")
    complete = [f for f in fid_pos if all(x is not None for x in f)]
    if len(complete) >= 3 and len({len(f) for f in complete}) == 1:
        std = (np.array(complete) / geo.ppm).std(axis=0)
        print("Repeatability of fiducial positions after alignment (std, mm):")
        for i, (sx, sy) in enumerate(std):
            print(f"  fiducial {i}: x {sx:.3f}  y {sy:.3f}")
    print(f"Canvases saved in {out}")


if __name__ == "__main__":
    main()
