#!/usr/bin/env python3
"""
tools/test_alignment.py - Stage 6c / Package D "fiducial detection testing".

Runs the aligner on raw images and reports, per image: status, orientation,
template scores, fiducials found and residual. With many insertions of the
SAME board it also reports repeatability (how much a fixed feature moves in
the canvas) - this is the floor for your position tolerance.

  python tools/test_alignment.py --side bottom --images dataset_capture/raw/bottom
  python tools/test_alignment.py --side top --images test_raw/top --expect wrong_side

PASS criteria (suggested - agree final values with your adviser):
  * correct side, normal orientation:   100 % "ok"
  * correct side, rotated 180 deg:      100 % "ok" with rotated_180 = True
  * flipped board:                      100 % "wrong_side"
  * empty tray / other board:           100 % "unknown_board" or "no_board"
  * fiducial residual mean < 0.15 mm, repeatability (std) < 0.10 mm
"""
import argparse
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import config as C  # noqa: E402
from inspection.runner import make_aligners, make_canvas  # noqa: E402
from vision import fiducials as fid  # noqa: E402
from vision.preprocessing import to_gray_normalized  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--expect", help="expected status, e.g. ok, wrong_side, unknown_board")
    args = ap.parse_args()
    geo = make_canvas()
    aligner = make_aligners(geo)[args.side]
    out = C.PROJECT_DIR / "test_output" / "alignment" / args.side
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in args.images.glob("*") if p.suffix.lower() in (".jpg", ".png"))
    statuses, rms, fid_pos = [], [], []
    for p in files:
        r = aligner.align(cv2.imread(str(p)))
        statuses.append(r.status)
        sc = " ".join(f"{k}={v:.2f}" for k, v in r.template_scores.items())
        print(f"{p.name:45} {r.status:14} rot180={r.rotated_180!s:5} "
              f"fid={r.fiducials_found}/{r.fiducials_expected} "
              f"rms={r.fiducial_rms_mm if r.fiducial_rms_mm is None else round(r.fiducial_rms_mm, 3)}"
              f"  {sc}")
        if r.canvas is not None:
            cv2.imwrite(str(out / p.name), r.canvas)
        if r.fiducial_rms_mm is not None and r.usable:
            rms.append(r.fiducial_rms_mm)
            # where do the fiducials land AFTER alignment? (repeatability)
            m = fid.locate_fiducials(to_gray_normalized(r.canvas), aligner.fiducials_mm,
                                     geo.ppm, geo.m, 1.5)
            fid_pos.append([f["found_px"] for f in m])
    print(f"\n{len(files)} images: " + ", ".join(f"{s}={statuses.count(s)}"
                                                 for s in sorted(set(statuses))))
    if args.expect:
        hit = statuses.count(args.expect)
        print(f"Expected '{args.expect}': {hit}/{len(files)} = {hit / max(1, len(files)) * 100:.1f} %")
    if rms:
        print(f"Fiducial residual: mean {st.mean(rms):.3f} mm, max {max(rms):.3f} mm")
    complete = [f for f in fid_pos if all(x is not None for x in f)]
    if len(complete) >= 3:
        arr = np.array(complete) / geo.ppm          # (n, k, 2) in mm
        std = arr.std(axis=0)
        print("Repeatability of fiducial positions after alignment (std, mm):")
        for i, (sx, sy) in enumerate(std):
            print(f"  fiducial {i}: x {sx:.3f}  y {sy:.3f}")
    print(f"Canvases saved in {out}")


if __name__ == "__main__":
    main()
