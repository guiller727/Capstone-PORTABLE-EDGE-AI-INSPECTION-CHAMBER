#!/usr/bin/env python3
"""
tools/build_golden_reference.py - Stage 9: build references/golden_<side>.json.

Input: a folder of CANVAS images of KNOWN-GOOD boards (from
tools/capture_dataset.py, folder dataset_capture/canvas/<side>/), e.g.
10 boards x 3 insertions = 30 images. Do NOT use boards from your test set.

  python tools/build_golden_reference.py --side bottom \
      --images dataset_capture/canvas/bottom --seed-label B01_..._n01.txt

--seed-label (recommended): the YOLO label file of ONE known-good canvas that
you checked by hand (from your Label Studio export). Every box becomes one
expected component. Without it, the detections on the first image are used.

After building: open the JSON, rename IDs to the silkscreen designators
(R3, C7, U1...), and check the printed spread table. Re-run with a different
--k-sigma or edit tol_mm per component if the partner company specifies
tolerances (IPC-A-610).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

import config as C  # noqa: E402
from inspection import golden_reference as gr  # noqa: E402
from inspection.component_matching import same_class_matcher  # noqa: E402
from inspection.runner import make_canvas  # noqa: E402
from vision.component_detection import Detector  # noqa: E402
from vision.coordinate_extraction import detections_to_mm, yolo_label_to_mm  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--seed-label", type=Path)
    ap.add_argument("--model", type=Path, help="default: config MODELS[side]")
    ap.add_argument("--k-sigma", type=float, default=4.0)
    ap.add_argument("--conf", type=float, default=C.T_HIGH,
                    help="only confident detections are used for statistics")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    cv_geo = make_canvas()
    m = C.MODELS[args.side]
    det = Detector(args.model or C.MODELS_DIR / m["path"], m["imgsz"], m["classes"])
    files = sorted(p for p in args.images.glob("*") if p.suffix.lower() in (".jpg", ".png"))
    if len(files) < 10:
        print(f"WARNING: only {len(files)} images; 20-30 (10+ boards) recommended")
    runs = []
    boards = set()
    for p in files:
        img = cv2.imread(str(p))
        if img.shape[1] != cv_geo.w or img.shape[0] != cv_geo.h:
            sys.exit(f"{p.name} is {img.shape[1]}x{img.shape[0]}, expected canvas "
                     f"{cv_geo.w}x{cv_geo.h}. Use canvas images, not raw images.")
        # images are canvases that were already CLAHE-processed by capture_dataset.py
        runs.append(detections_to_mm(det.detect(img, conf=args.conf), cv_geo.ppm, cv_geo.m))
        boards.add(p.name.split("_")[0])

    if args.seed_label:
        seed_obs = yolo_label_to_mm(args.seed_label, m["classes"], cv_geo.w, cv_geo.h,
                                    cv_geo.ppm, cv_geo.m)
    else:
        seed_obs = runs[0]
        print("NOTE: seeding from detections on the first image - verify the count!")
    seed = gr.seed_components(seed_obs)
    matcher = same_class_matcher(C.MATCH)
    comps, warnings = gr.build_statistics(seed, runs, matcher, C.DEFAULT_TOL_MM, args.k_sigma)
    # second pass: re-seed with the averaged positions (more robust matching)
    comps, warnings = gr.build_statistics(comps, runs, matcher, C.DEFAULT_TOL_MM, args.k_sigma)

    data = gr.make_golden_file(args.side, comps, cv_geo, len(runs), len(boards), C.BOARD_NAME)
    out = args.out or C.REFERENCES_DIR / f"golden_{args.side}.json"
    gr.save_golden(out, data)

    print(f"\n{'ID':6} {'class':16} {'x_mm':>8} {'y_mm':>7} {'std_x':>6} {'std_y':>6} "
          f"{'tol':>5} {'seen':>5}")
    for c in comps:
        sx = f"{c['std_x_mm']:.3f}" if c["std_x_mm"] is not None else "  -  "
        sy = f"{c['std_y_mm']:.3f}" if c["std_y_mm"] is not None else "  -  "
        print(f"{c['id']:6} {c['class']:16} {c['x_mm']:8.2f} {c['y_mm']:7.2f} {sx:>6} {sy:>6} "
              f"{c['tol_mm']:5.2f} {c['seen']:5d}")
    for w in warnings:
        print("WARNING:", w)
    counts = {}
    for c in comps:
        counts[c["class"]] = counts.get(c["class"], 0) + 1
    print(f"\n{len(comps)} components {counts} from {len(runs)} images of {len(boards)} boards")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
