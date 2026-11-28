#!/usr/bin/env python3
"""
tools/benchmark.py - Package D "performance testing": inference time, RAM,
CPU temperature and throttling on the Raspberry Pi.

  python tools/benchmark.py              # models only, 50 runs per side
  python tools/benchmark.py --full 20    # 20 full inspections with cameras+LEDs

Record the printed table in your paper. All numbers in the PDF are
ESTIMATES until replaced by these measurements.
"""
import argparse
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402
import psutil  # noqa: E402  (installed with ultralytics)

import config as C  # noqa: E402


def pi_status():
    out = {}
    for key, cmd in (("temp", ["vcgencmd", "measure_temp"]),
                     ("throttled", ["vcgencmd", "get_throttled"])):
        try:
            out[key] = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        except FileNotFoundError:
            out[key] = "n/a"
    return out


def pct(values, p):
    return float(np.percentile(values, p))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--full", type=int, default=0, help="number of full inspections")
    ap.add_argument("--compare-pt", action="store_true",
                    help="also time best.pt (PyTorch) to compare with NCNN")
    args = ap.parse_args()
    proc = psutil.Process()
    print("Start:", pi_status(), f"RSS {proc.memory_info().rss / 1e6:.0f} MB")
    from vision.component_detection import Detector
    from inspection.profile import Profile
    from inspection.runner import make_canvas
    prof = Profile(C.MODELS_DIR, C.ACTIVE_PROFILE)
    geo = make_canvas(prof)
    img = (np.random.rand(geo.h, geo.w, 3) * 255).astype(np.uint8)
    runs = [(s, True) for s in prof.sides()] + ([(s, False) for s in prof.sides()]
                                                if args.compare_pt else [])
    for side, ncnn in runs:
        path, fmt, imgsz = prof.model_info(side, prefer_ncnn=ncnn)
        det = Detector(path, imgsz, prof.classes(side))
        det.warmup((geo.h, geo.w, 3))
        times = []
        for _ in range(args.n):
            det.detect(img, conf=C.T_LOW)
            times.append(det.last_ms)
        print(f"{side:6} {fmt:5} imgsz={imgsz}: mean {st.mean(times):.1f} ms  "
              f"p95 {pct(times, 95):.1f} ms  max {max(times):.1f} ms")
    print("After models:", pi_status(), f"RSS {proc.memory_info().rss / 1e6:.0f} MB, "
          f"system used {psutil.virtual_memory().used / 1e9:.2f} GB of "
          f"{psutil.virtual_memory().total / 1e9:.2f} GB")

    if args.full:
        from inspection.runner import InspectionSystem
        s = InspectionSystem()
        s.start(progress=print)
        tot, cap = [], []
        for i in range(args.full):
            out = s.inspect()
            if out.get("state") == "RESULT":
                tot.append(out["timing"]["total_s"])
                cap.append(out["timing"]["capture_s"])
            print(f"  run {i + 1}: {out.get('verdict', out.get('state'))} "
                  f"{out.get('timing', {})}")
            time.sleep(0.5)
        s.close()
        if tot:
            print(f"Full inspection: mean {st.mean(tot):.2f} s, p95 {pct(tot, 95):.2f} s, "
                  f"max {max(tot):.2f} s (capture mean {st.mean(cap):.2f} s)")
        print("End:", pi_status(), f"peak RSS {proc.memory_info().rss / 1e6:.0f} MB")
        print("throttled=0x0 means no under-voltage / thermal throttling occurred.")


if __name__ == "__main__":
    main()
