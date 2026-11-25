#!/usr/bin/env python3
"""
tools/run_offline.py - run the COMPLETE inspection logic on saved raw images
(no cameras needed) and, optionally, score it against ground truth.
This is how you produce the Chapter 4 decision results on the test boards.

Folder layout expected (pairs share the same file name):
    test_set/top/<name>.jpg
    test_set/bottom/<name>.jpg
Ground truth CSV (optional): columns  name,expected   (expected = PASS/FAIL/REVIEW)
  - "PASS" for known-good boards, "FAIL" for boards with a real defect.
    (REVIEW is a system output, not a ground-truth class - use PASS/FAIL.)

  python tools/run_offline.py --images test_set --truth test_set/truth.csv
Outputs test_output/offline/results.csv and a confusion table on screen.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

import config as C  # noqa: E402
from inspection.golden_reference import load_golden  # noqa: E402
from inspection.runner import InspectionSystem  # noqa: E402
from vision.component_detection import Detector  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--truth", type=Path)
    args = ap.parse_args()

    sysm = InspectionSystem(simulate=True, load_models=False)
    for side in ("top", "bottom"):
        sysm.golden[side] = load_golden(C.REFERENCES_DIR / f"golden_{side}.json")
        m = C.MODELS[side]
        sysm.detectors[side] = Detector(C.MODELS_DIR / m["path"], m["imgsz"], m["classes"])
    truth = {}
    if args.truth:
        with open(args.truth) as f:
            truth = {r["name"]: r["expected"].strip().upper() for r in csv.DictReader(f)}

    out_dir = C.PROJECT_DIR / "test_output" / "offline"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for top_path in sorted((args.images / "top").glob("*")):
        bot_path = args.images / "bottom" / top_path.name
        if not bot_path.exists():
            print("no bottom image for", top_path.name)
            continue
        raw = {"top": cv2.imread(str(top_path)), "bottom": cv2.imread(str(bot_path))}
        res = sysm.process(raw)
        verdict = res.get("verdict", res["state"])
        name = top_path.stem
        rows.append({"name": name, "system": verdict, "expected": truth.get(name, ""),
                     "flagged": " | ".join(res.get("flagged", [res.get("message", "")])),
                     "inf_top_ms": res["timing"].get("inference_ms_top"),
                     "inf_bottom_ms": res["timing"].get("inference_ms_bottom")})
        print(f"{name:40} {verdict:14} expected={truth.get(name, '?')}")
        if res["state"] == "RESULT":
            from gui.overlay import draw_side
            for sr in res["side_results"]:
                cv2.imwrite(str(out_dir / f"{name}_{sr.side}.jpg"),
                            draw_side(res["canvases"][sr.side], sr, sysm.canvas.ppm,
                                      sysm.canvas.m))
    with open(out_dir / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys()) if rows else ["name"])
        w.writeheader()
        w.writerows(rows)

    scored = [r for r in rows if r["expected"] in ("PASS", "FAIL")]
    if scored:
        labels = ["PASS", "FAIL", "REVIEW"]
        table = {(e, s): 0 for e in ("PASS", "FAIL") for s in labels + ["OTHER"]}
        for r in scored:
            s = r["system"] if r["system"] in labels else "OTHER"
            table[(r["expected"], s)] += 1
        print("\nRows = ground truth, columns = system output")
        print(f"{'':8}" + "".join(f"{s:>8}" for s in labels + ["OTHER"]))
        for e in ("PASS", "FAIL"):
            print(f"{e:8}" + "".join(f"{table[(e, s)]:8d}" for s in labels + ["OTHER"]))
        n_fail = sum(table[("FAIL", s)] for s in labels + ["OTHER"])
        n_pass = sum(table[("PASS", s)] for s in labels + ["OTHER"])
        escape = table[("FAIL", "PASS")]
        false_rej = table[("PASS", "FAIL")]
        print(f"\nDefect escape rate (FAIL boards passed): {escape}/{n_fail}"
              f"  <- most important, must be 0 or very low")
        print(f"False reject rate (good boards failed):  {false_rej}/{n_pass}")
        print(f"REVIEW rate: {table[('PASS', 'REVIEW')] + table[('FAIL', 'REVIEW')]}/{len(scored)}")
    print(f"\nSaved {out_dir / 'results.csv'}")


if __name__ == "__main__":
    main()
