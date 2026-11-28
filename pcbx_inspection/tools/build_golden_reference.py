#!/usr/bin/env python3
"""
tools/build_golden_reference.py - Stage 9 (V2): build the expected component
list of ONE side inside models/<profile>/golden_reference.json.

Input: CANVAS images of KNOWN-GOOD boards for that side
(dataset_capture/canvas/top/ or .../bottom/), e.g. 10 boards x 3 insertions.
Do NOT use boards from your test set.

  python tools/build_golden_reference.py --side bottom \
      --images dataset_capture/canvas/bottom --seed-label B01_..._n01_lower.txt
  python tools/build_golden_reference.py --side top --images dataset_capture/canvas/top

--seed-label (recommended): the YOLO label file of ONE known-good canvas that
you checked by hand (from your labelled dataset). Every box becomes one
expected component. Without it, the detections on the first image are used.

The file is written with the safe-save procedure (validated, old file kept in
models/<profile>/backups/). If golden_reference.json does not exist yet, it
is created; the other side is left untouched. Afterwards: rename the IDs to
the silkscreen designators (Settings > Golden JSON in the GUI, or a text
editor), check the spread table, and set tolerances with the partner company.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

import config as C  # noqa: E402
from inspection import golden_reference as gr  # noqa: E402
from inspection.component_matching import same_class_matcher  # noqa: E402
from inspection.profile import Profile  # noqa: E402
from inspection.runner import make_canvas  # noqa: E402
from vision.component_detection import Detector  # noqa: E402
from vision.coordinate_extraction import detections_to_mm, yolo_label_to_mm  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--seed-label", type=Path)
    ap.add_argument("--profile", default=C.ACTIVE_PROFILE)
    ap.add_argument("--k-sigma", type=float, default=4.0)
    ap.add_argument("--conf", type=float, default=C.T_HIGH)
    args = ap.parse_args()

    prof = Profile(C.MODELS_DIR, args.profile)
    geo = make_canvas(prof)
    path, fmt, imgsz = prof.model_info(args.side, C.PREFER_NCNN)
    det = Detector(path, imgsz, prof.classes(args.side))
    files = sorted(p for p in args.images.glob("*") if p.suffix.lower() in (".jpg", ".png"))
    if not files:
        sys.exit(f"No images in {args.images}")
    if len(files) < 10:
        print(f"WARNING: only {len(files)} images; 20-30 (10+ boards) recommended")
    runs, boards = [], set()
    for p in files:
        img = cv2.imread(str(p))
        if img.shape[1] != geo.w or img.shape[0] != geo.h:
            sys.exit(f"{p.name} is {img.shape[1]}x{img.shape[0]}, expected canvas {geo.w}x{geo.h}. "
                     "Use canvas images (dataset_capture/canvas/...), not raw images.")
        runs.append(detections_to_mm(det.detect(img, conf=args.conf), geo.ppm, geo.m))
        boards.add(p.name.split("_")[0])

    if args.seed_label:
        seed_obs = yolo_label_to_mm(args.seed_label, prof.classes(args.side), geo.w, geo.h,
                                    geo.ppm, geo.m)
    else:
        seed_obs = runs[0]
        print("NOTE: seeding from detections on the first image - verify the count!")
    seed = gr.seed_components(seed_obs)
    matcher = same_class_matcher(C.MATCH)
    comps, warnings = gr.build_statistics(seed, runs, matcher, C.DEFAULT_TOL_MM, args.k_sigma)
    comps, warnings = gr.build_statistics(comps, runs, matcher, C.DEFAULT_TOL_MM, args.k_sigma)

    gpath = prof.golden_path
    if gpath.exists():
        data = json.loads(gpath.read_text())
    else:
        data = gr.new_golden(prof.name, prof.board_name, prof.board_size, geo,
                             {s: prof.label(s) for s in prof.sides()})
    data = gr.set_side_components(data, args.side, comps, len(runs), len(boards))
    other = "bottom" if args.side == "top" else "top"
    if not data["sides"].get(other, {}).get("components"):
        # the other side is not built yet: validation would reject an empty side
        data["sides"].pop(other, None)
        print(f"NOTE: {other} side not built yet - run this tool for --side {other} too.")
    saved = gr.save_golden_safe(gpath, data, modified_by="build_golden_reference",
                                classes_by_side=prof.classes_by_side())

    print(f"\n{'ID':6} {'class':18} {'x_mm':>8} {'y_mm':>7} {'std_x':>6} {'std_y':>6} {'tol':>5} {'seen':>5}")
    for c in comps:
        sx = f"{c['std_x_mm']:.3f}" if c["std_x_mm"] is not None else "  -  "
        sy = f"{c['std_y_mm']:.3f}" if c["std_y_mm"] is not None else "  -  "
        print(f"{c['id']:6} {c['class']:18} {c['x_mm']:8.2f} {c['y_mm']:7.2f} {sx:>6} {sy:>6} "
              f"{c['tol_mm']:5.2f} {c['seen']:5d}")
    for w in warnings:
        print("WARNING:", w)
    _, warns = gr.validate_golden(saved, prof.classes_by_side())
    for w in warns:
        print("WARNING:", w)
    print(f"\n{len(comps)} components from {len(runs)} images of {len(boards)} boards. "
          f"Saved {gpath} (revision {saved['revision']})")


if __name__ == "__main__":
    main()
