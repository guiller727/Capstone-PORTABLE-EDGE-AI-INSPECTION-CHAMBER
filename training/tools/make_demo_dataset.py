#!/usr/bin/env python3
"""
tools/make_demo_dataset.py - create a FAKE Label Studio export (coloured
rectangles on a green canvas) so you can test the whole training pipeline
(prepare -> check -> zip -> Colab/local train -> export) before you have real
images. The resulting model is useless for real boards.

  python tools/make_demo_dataset.py --side bottom --boards 8 --per-board 4
  python tools/prepare_dataset.py --export demo_export_bottom.zip --side bottom
"""
import argparse
import random
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

from common import CANVAS_H, CANVAS_W, CLASSES, HERE  # noqa: E402

COL = [(30, 30, 30), (200, 120, 40), (40, 40, 200), (180, 180, 180), (40, 200, 200),
       (200, 40, 200), (90, 160, 60)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--boards", type=int, default=8)
    ap.add_argument("--per-board", type=int, default=4)
    args = ap.parse_args()
    names = CLASSES[args.side]
    rng = random.Random(1)
    # fixed "layout" shared by all boards (like a real PCB)
    layout = []
    for i in range(12 if args.side == "bottom" else 8):
        c = i % len(names)
        w, h = (rng.randint(18, 50), rng.randint(12, 40)) if args.side == "bottom" \
            else (rng.randint(60, 140), rng.randint(50, 120))
        layout.append((c, rng.randint(40, CANVAS_W - 200), rng.randint(40, CANVAS_H - 160), w, h))
    out = HERE / f"demo_export_{args.side}.zip"
    ls_order = sorted(names)                  # Label Studio-like alphabetical order
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("classes.txt", "\n".join(ls_order) + "\n")
        for b in range(1, args.boards + 1):
            for k in range(args.per_board):
                img = np.zeros((CANVAS_H, CANVAS_W, 3), np.uint8)
                img[:] = (40, 110, 30)
                noise = np.random.default_rng(b * 100 + k).normal(0, 6, img.shape)
                lines = []
                for c, x, y, w, h in layout:
                    if rng.random() < 0.05:           # 5 % "missing part" boards
                        continue
                    dx, dy = rng.randint(-3, 3), rng.randint(-3, 3)
                    cv2.rectangle(img, (x + dx, y + dy), (x + dx + w, y + dy + h), COL[c], -1)
                    cx, cy = (x + dx + w / 2) / CANVAS_W, (y + dy + h / 2) / CANVAS_H
                    lines.append(f"{ls_order.index(names[c])} {cx:.6f} {cy:.6f} "
                                 f"{w / CANVAS_W:.6f} {h / CANVAS_H:.6f}")
                img = np.clip(img + noise, 0, 255).astype(np.uint8)
                stem = f"{rng.getrandbits(32):08x}-B{b:02d}_demo_n{k + 1:02d}"
                ok, buf = cv2.imencode(".jpg", img)
                z.writestr(f"images/{stem}.jpg", buf.tobytes())
                z.writestr(f"labels/{stem}.txt", "\n".join(lines) + "\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
