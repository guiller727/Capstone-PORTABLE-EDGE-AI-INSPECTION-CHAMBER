#!/usr/bin/env python3
"""
train.py - train one side's detector (local PC or Colab terminal).

  python train.py --side top
  python train.py --side bottom
  python train.py --side bottom --model yolo26n.pt          # try YOLO26n
  python train.py --side top --model yolov8s.pt --name top_v8s
  python train.py --side top --epochs 3 --name smoke        # quick pipeline test

Settings come from configs/hyp_<side>.yaml; command-line values override.
Results: runs/<side>/<name>/ (weights/best.pt, results.csv, plots).
"""
import argparse
import shutil
from pathlib import Path

from common import HERE, default_dataset_dir, load_hyp, pick_device, safe_workers, write_data_yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--model", default="yolov8n.pt",
                    help="yolov8n.pt (baseline), yolo26n.pt, yolov8s.pt, ...")
    ap.add_argument("--dataset", type=Path, help="default datasets/pcbx_<side>")
    ap.add_argument("--data", type=Path, help="use this data YAML instead (learning curve)")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--imgsz", type=int)
    ap.add_argument("--batch", type=int)
    ap.add_argument("--device", default="auto", help="auto, 0, cpu, mps")
    ap.add_argument("--name")
    ap.add_argument("--project", type=Path, default=HERE / "runs")
    ap.add_argument("--resume", action="store_true", help="continue an interrupted run")
    args = ap.parse_args()

    from ultralytics import YOLO
    hyp = load_hyp(args.side)
    for k in ("epochs", "imgsz", "batch"):
        if getattr(args, k) is not None:
            hyp[k] = getattr(args, k)
    hyp["workers"] = safe_workers(hyp.get("workers", 2))
    device = pick_device(args.device)
    if device == "cpu":
        hyp["batch"] = min(hyp["batch"], 4)
        print("No GPU found - training on CPU (slow). Use Colab for full training.")
    data = args.data or write_data_yaml(args.dataset or default_dataset_dir(args.side), args.side)
    name = args.name or f"{args.side}_{Path(args.model).stem}"
    project = Path(args.project) / args.side

    if args.resume:
        last = project / name / "weights" / "last.pt"
        print("Resuming", last)
        YOLO(str(last)).train(resume=True)
    else:
        model = YOLO(args.model)
        model.train(data=str(data), device=device, project=str(project), name=name,
                    exist_ok=True, **hyp)
    best = project / name / "weights" / "best.pt"
    out = HERE / "weights_out" / f"{args.side}_{Path(args.model).stem}_best.pt"
    out.parent.mkdir(exist_ok=True)
    shutil.copy2(best, out)
    print(f"\nBest weights: {best}\nCopied to:    {out}")
    print(f"Next: python validate.py --side {args.side} --weights {out}")


if __name__ == "__main__":      # required on Windows (data-loader processes)
    main()
