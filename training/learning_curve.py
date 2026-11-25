#!/usr/bin/env python3
"""
learning_curve.py - "do we have enough images?" test from the PDF (Section 3.4).

Trains on 25 %, 50 %, 75 % and 100 % of the TRAINING images (random subsets,
fixed seed; validation set unchanged) and plots val mAP@50 against the number
of training images. Rule of thumb from the PDF: if mAP@50 still rises by
more than ~2 points between 75 % and 100 %, capture more images.

  python learning_curve.py --side bottom
  python learning_curve.py --side top --fractions 0.25 0.5 1.0 --epochs 80

Note: Ultralytics' built-in `fraction=` takes the FIRST N files in name order
(= the first boards only), so we build random subset lists instead.
"""
import argparse
import csv
import random
from pathlib import Path

import yaml

from common import HERE, default_dataset_dir, load_hyp, pick_device, safe_workers, write_data_yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--fractions", type=float, nargs="+", default=[0.25, 0.5, 0.75, 1.0])
    ap.add_argument("--epochs", type=int, help="default: hyp epochs")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dataset", type=Path)
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()

    from ultralytics import YOLO
    ds = (args.dataset or default_dataset_dir(args.side)).resolve()
    base = yaml.safe_load(write_data_yaml(ds, args.side).read_text())
    train_imgs = sorted((ds / "images" / "train").glob("*"))
    rng = random.Random(args.seed)
    shuffled = train_imgs[:]
    rng.shuffle(shuffled)
    hyp = load_hyp(args.side)
    hyp["workers"] = safe_workers(hyp.get("workers", 2))
    if args.epochs:
        hyp["epochs"] = args.epochs
    out_dir = HERE / "runs" / "learning_curve" / args.side
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in args.fractions:
        n = max(1, round(len(shuffled) * f))
        lst = out_dir / f"train_{int(f * 100)}.txt"
        lst.write_text("\n".join(p.as_posix() for p in shuffled[:n]) + "\n")
        data = dict(base, train=lst.as_posix())
        dyaml = out_dir / f"data_{int(f * 100)}.yaml"
        dyaml.write_text(yaml.safe_dump(data, sort_keys=False))
        model = YOLO(args.model)
        model.train(data=str(dyaml), device=pick_device(args.device), project=str(out_dir),
                    name=f"frac_{int(f * 100)}", exist_ok=True, **hyp)
        best = out_dir / f"frac_{int(f * 100)}" / "weights" / "best.pt"
        m = YOLO(str(best)).val(data=str(dyaml), split="val", imgsz=hyp["imgsz"],
                                device=pick_device(args.device), verbose=False, plots=False)
        rows.append({"fraction": f, "train_images": n, "mAP50": round(float(m.box.map50), 4),
                     "mAP50_95": round(float(m.box.map), 4)})
        print(rows[-1])
    with open(out_dir / "learning_curve.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.figure(figsize=(5, 3.5))
        plt.plot([r["train_images"] for r in rows], [r["mAP50"] * 100 for r in rows], "o-")
        plt.xlabel("training images")
        plt.ylabel("val mAP@50 (%)")
        plt.title(f"Learning curve - {args.side}")
        plt.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_dir / "learning_curve.png", dpi=150)
    except Exception as exc:          # plotting is optional
        print("plot skipped:", exc)
    if len(rows) >= 2:
        gain = (rows[-1]["mAP50"] - rows[-2]["mAP50"]) * 100
        print(f"\nGain from last step: {gain:+.1f} mAP50 points -> "
              + ("capture MORE images" if gain > 2 else "dataset size looks sufficient"))
    print(f"Saved {out_dir / 'learning_curve.csv'}")


if __name__ == "__main__":
    main()
