#!/usr/bin/env python3
"""
tools/run_offline.py - run the COMPLETE inspection logic (identification,
orientation, alignment, YOLO, golden comparison, rules) on saved raw images,
without cameras, and optionally score it against ground truth. This is how
you produce the Chapter 4 decision results on the test boards.

Folder layout (dual mode, pairs share the same file name):
    test_set/upper/<name>.jpg      image from the upper camera
    test_set/lower/<name>.jpg      image from the lower camera
(raw_upper.jpg / raw_lower.jpg from logs/<date>/<board_id>/ can be copied here.)
Ground truth CSV (optional): columns  name,expected   with PASS or FAIL.
(REVIEW is a system output, not a ground-truth class.)

  python tools/run_offline.py --images test_set --truth test_set/truth.csv
Outputs test_output/offline/results.csv, overlays, and a confusion table.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

import config as C  # noqa: E402
from inspection.runner import InspectionSystem  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--truth", type=Path)
    ap.add_argument("--profile", default=C.ACTIVE_PROFILE)
    args = ap.parse_args()

    sysm = InspectionSystem(simulate=True, load_models=False, profile_name=args.profile)
    problems = sysm.load_profile()
    problems += sysm.load_detectors(print)
    if problems:
        sys.exit("Profile not ready:\n  - " + "\n  - ".join(problems))
    truth = {}
    if args.truth:
        with open(args.truth) as f:
            truth = {r["name"]: r["expected"].strip().upper() for r in csv.DictReader(f)}

    out_dir = C.PROJECT_DIR / "test_output" / "offline"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for up in sorted((args.images / "upper").glob("*")):
        low = args.images / "lower" / up.name
        raw = {"upper": cv2.imread(str(up)), "lower": cv2.imread(str(low)) if low.exists() else None}
        res = sysm.process(raw)
        verdict = res.get("verdict", res["state"])
        name = up.stem
        srs = res.get("side_results", {})
        rows.append({"name": name, "system": verdict, "expected": truth.get(name, ""),
                     "front": srs["top"].verdict if "top" in srs else "",
                     "back": srs["bottom"].verdict if "bottom" in srs else "",
                     "flagged": " | ".join(res.get("flagged", [res.get("message", "")])),
                     "inf_top_ms": res.get("timing", {}).get("inference_ms_top"),
                     "inf_bottom_ms": res.get("timing", {}).get("inference_ms_bottom")})
        print(f"{name:40} {verdict:10} expected={truth.get(name, '?')}")
        if res["state"] == "RESULT":
            from gui.overlay import draw_side
            for side, sr in srs.items():
                if side in res["canvases"]:
                    cv2.imwrite(str(out_dir / f"{name}_{side}.jpg"),
                                draw_side(res["canvases"][side], sr, sysm.canvas.ppm, sysm.canvas.m))
    with open(out_dir / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys()) if rows else ["name"])
        w.writeheader()
        w.writerows(rows)

    scored = [r for r in rows if r["expected"] in ("PASS", "FAIL")]
    if scored:
        labels = ["PASS", "FAIL", "REVIEW"]
        table = {(e, s): 0 for e in ("PASS", "FAIL") for s in labels + ["OTHER"]}
        for r in scored:
            table[(r["expected"], r["system"] if r["system"] in labels else "OTHER")] += 1
        print("\nRows = ground truth, columns = system output")
        print(f"{'':8}" + "".join(f"{s:>8}" for s in labels + ["OTHER"]))
        for e in ("PASS", "FAIL"):
            print(f"{e:8}" + "".join(f"{table[(e, s)]:8d}" for s in labels + ["OTHER"]))
        n_fail = sum(table[("FAIL", s)] for s in labels + ["OTHER"])
        n_pass = sum(table[("PASS", s)] for s in labels + ["OTHER"])
        print(f"\nDefect escape rate (FAIL boards judged PASS): {table[('FAIL', 'PASS')]}/{n_fail}"
              "  <- most important, target 0")
        print(f"False reject rate (good boards judged FAIL):  {table[('PASS', 'FAIL')]}/{n_pass}")
        print(f"REVIEW rate: {table[('PASS', 'REVIEW')] + table[('FAIL', 'REVIEW')]}/{len(scored)}")
    print(f"\nSaved {out_dir / 'results.csv'}")


if __name__ == "__main__":
    main()
