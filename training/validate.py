#!/usr/bin/env python3
"""
validate.py - evaluate a trained model on the validation or (ONCE, at the
end) the test split, and save the numbers for your paper.

  python validate.py --side bottom --weights weights_out/bottom_yolov8n_best.pt
  python validate.py --side bottom --weights ... --split test       # final only!
  python validate.py --side top --weights models/top_best_ncnn_model --imgsz 288 640

Prints per-class Precision, Recall, F1, mAP@50, mAP@50-95 and writes
metrics_<side>_<split>.json + confusion matrix PNG in runs/val/.
"""
import argparse
import json
from pathlib import Path

from common import CLASSES, HERE, default_dataset_dir, load_hyp, pick_device, write_data_yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--weights", type=Path, required=True)
    ap.add_argument("--split", choices=["val", "test"], default="val")
    ap.add_argument("--dataset", type=Path)
    ap.add_argument("--imgsz", type=int, nargs="+", help="default: training imgsz")
    ap.add_argument("--conf", type=float, default=0.001,
                    help="0.001 = standard for mAP. Use T_LOW (0.25) to see P/R at deployment")
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()

    from ultralytics import YOLO
    data = write_data_yaml(args.dataset or default_dataset_dir(args.side), args.side)
    imgsz = args.imgsz if args.imgsz else load_hyp(args.side)["imgsz"]
    if isinstance(imgsz, list) and len(imgsz) == 1:
        imgsz = imgsz[0]
    model = YOLO(str(args.weights), task="detect")
    name = f"{args.side}_{args.split}_{args.weights.stem}"
    m = model.val(data=str(data), split=args.split, imgsz=imgsz, conf=args.conf,
                  device=pick_device(args.device), project=str(HERE / "runs" / "val"),
                  name=name, exist_ok=True, plots=True)
    names = CLASSES[args.side]
    p, r = m.box.p, m.box.r
    ap50, ap = m.box.ap50, m.box.ap
    rows = []
    print(f"\n{'class':18}{'P':>7}{'R':>7}{'F1':>7}{'mAP50':>8}{'mAP50-95':>10}")
    for i, cls_idx in enumerate(m.box.ap_class_index):
        f1 = 2 * p[i] * r[i] / (p[i] + r[i] + 1e-9)
        rows.append({"class": names[int(cls_idx)], "P": float(p[i]), "R": float(r[i]),
                     "F1": float(f1), "mAP50": float(ap50[i]), "mAP50_95": float(ap[i])})
        print(f"{names[int(cls_idx)]:18}{p[i]:7.3f}{r[i]:7.3f}{f1:7.3f}{ap50[i]:8.3f}{ap[i]:10.3f}")
    mp, mr = m.box.mp, m.box.mr
    mf1 = 2 * mp * mr / (mp + mr + 1e-9)
    print(f"{'ALL':18}{mp:7.3f}{mr:7.3f}{mf1:7.3f}{m.box.map50:8.3f}{m.box.map:10.3f}")
    out = HERE / "runs" / "val" / f"metrics_{args.side}_{args.split}_{args.weights.stem}.json"
    out.write_text(json.dumps({"side": args.side, "split": args.split,
                               "weights": str(args.weights), "imgsz": imgsz,
                               "overall": {"P": mp, "R": mr, "F1": mf1, "mAP50": m.box.map50,
                                           "mAP50_95": m.box.map},
                               "per_class": rows,
                               "speed_ms": m.speed}, indent=2, default=float))
    print(f"\nSaved {out}\nConfusion matrix: {HERE / 'runs' / 'val' / name}")
    if args.split == "test":
        print("TEST split used. Do not tune anything based on this result.")


if __name__ == "__main__":
    main()
