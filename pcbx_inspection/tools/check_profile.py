#!/usr/bin/env python3
"""
tools/check_profile.py - NEW in V2: "is my trained model installed correctly?"
Run this after copying a model / golden reference into models/<profile>/.

  python tools/check_profile.py                         # active profile
  python tools/check_profile.py --profile pcb_x --image some_canvas_or_raw.jpg --side top

Checks, in order:
  1. metadata.json readable and consistent
  2. golden_reference.json valid (schema, classes, tolerances) + warnings
  3. board_profile.json present, markers/templates/fiducials per side
  4. model files present for each side (NCNN preferred, .pt fallback)
  5. each model LOADS, its class list equals metadata.json, one dummy inference
  6. optional: sample inference on --image (raw camera image or canvas)
Exit code 0 = ready, 1 = problems found.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import config as C  # noqa: E402
from inspection.golden_reference import GoldenError, validate_golden  # noqa: E402
from inspection.profile import ModelError, Profile, ProfileError  # noqa: E402


def ok(msg):
    print(f"  [OK]   {msg}")


def bad(msg, problems):
    print(f"  [FAIL] {msg}")
    problems.append(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=C.ACTIVE_PROFILE)
    ap.add_argument("--image", type=Path, help="run a sample inference on this image")
    ap.add_argument("--side", choices=["top", "bottom"], default="top")
    ap.add_argument("--no-load", action="store_true", help="skip loading the models")
    args = ap.parse_args()
    problems = []
    print(f"Profile '{args.profile}' in {C.MODELS_DIR}")
    try:
        prof = Profile(C.MODELS_DIR, args.profile)
        ok(f"metadata.json: {prof.board_name}, board {prof.board_size} mm, sides {prof.sides()}")
    except ProfileError as exc:
        bad(str(exc), problems)
        sys.exit(1)

    print("Golden reference:")
    gp = prof.golden_path
    if not gp.exists():
        bad(f"{gp.name} missing (tools/build_golden_reference.py)", problems)
    else:
        try:
            data = json.loads(gp.read_text())
            errs, warns = validate_golden(data, prof.classes_by_side())
            for e in errs:
                bad(e, problems)
            for w in warns:
                print(f"  [WARN] {w}")
            if not errs:
                for side, sd in data["sides"].items():
                    ok(f"{side}: {len(sd['components'])} components, thresholds "
                       f"{sd.get('thresholds')}, revision {data.get('revision')}")
        except json.JSONDecodeError as exc:
            bad(f"{gp.name}: invalid JSON line {exc.lineno}: {exc.msg}", problems)

    print("Board profile (identification + fiducials):")
    bp = prof.load_board_profile()
    if not bp:
        bad("board_profile.json missing (tools/build_board_profile.py)", problems)
    for side in prof.sides():
        sp = bp.get("sides", {}).get(side, {})
        mk = sp.get("markers", [])
        missing = [m["name"] for m in mk if m.get("type", "template") == "template"
                   and not (prof.dir / m.get("template", "")).exists()]
        if not mk and not sp.get("template"):
            bad(f"{side}: no identification markers", problems)
        elif missing:
            bad(f"{side}: template files missing for {missing}", problems)
        else:
            ok(f"{side}: {len(mk)} markers {[m['name'] for m in mk]}, "
               f"{len(sp.get('fiducials_mm', []))} fiducials")
        if len(sp.get("fiducials_mm", [])) < 2:
            print(f"  [WARN] {side}: fewer than 2 fiducials -> alignment 'coarse' -> REVIEW")

    print("Models:")
    from vision.component_detection import Detector
    from inspection.runner import make_canvas
    geo = make_canvas(prof)
    dets = {}
    for side in prof.sides():
        try:
            info = prof.check_model_files(side, C.PREFER_NCNN)
            ok(f"{side}: {info['format']} at {info['path']} imgsz {info['imgsz']}")
        except ModelError as exc:
            bad(str(exc), problems)
            continue
        if args.no_load:
            continue
        try:
            t0 = time.perf_counter()
            d = Detector(Path(info["path"]), info["imgsz"], prof.classes(side))
            load_s = time.perf_counter() - t0
            d.warmup((geo.h, geo.w, 3))
            d.detect(np.zeros((geo.h, geo.w, 3), np.uint8), conf=0.25)
            ok(f"{side}: loaded in {load_s:.1f} s, classes match, dummy inference "
               f"{d.last_ms:.0f} ms")
            dets[side] = d
        except Exception as exc:
            bad(f"{side}: {exc}", problems)

    if args.image and args.side in dets:
        img = cv2.imread(str(args.image))
        if img is None:
            bad(f"cannot read {args.image}", problems)
        else:
            if img.shape[:2] != (geo.h, geo.w):
                from inspection.runner import make_aligners
                from vision.preprocessing import preprocess_canvas
                al = make_aligners(geo, bp, prof.dir, ["upper"])["upper"]
                r = al.align(img)
                print(f"  sample image aligned: {r.status} side={r.side} ({r.message})")
                if r.canvas is None:
                    sys.exit(1)
                side = r.side or args.side
                img = preprocess_canvas(r.canvas, C.PREPROCESS)
            else:
                side = args.side
            found = dets[side].detect(img, conf=0.25)
            counts = {}
            for f in found:
                counts[f.cls] = counts.get(f.cls, 0) + 1
            ok(f"sample inference ({side}): {len(found)} boxes {counts} in {dets[side].last_ms:.0f} ms")
            vis = img.copy()
            for f in found:
                cv2.rectangle(vis, (int(f.x1), int(f.y1)), (int(f.x2), int(f.y2)), (0, 255, 0), 2)
                cv2.putText(vis, f"{f.cls} {f.conf:.2f}", (int(f.x1), int(f.y1) - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            outp = C.PROJECT_DIR / "test_output" / "check_profile_sample.jpg"
            outp.parent.mkdir(exist_ok=True)
            cv2.imwrite(str(outp), vis)
            print(f"         drawn boxes: {outp}")
    print("\nREADY" if not problems else f"\n{len(problems)} PROBLEM(S) - see [FAIL] lines")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
