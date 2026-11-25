#!/usr/bin/env python3
"""
export.py - convert best.pt into an NCNN model folder for the Raspberry Pi 5
and check that the exported model gives the same detections as the .pt.

  python export.py --side top    --weights weights_out/top_yolov8n_best.pt
  python export.py --side bottom --weights weights_out/bottom_yolo26n_best.pt
  python export.py --side bottom --weights ... --square      # square input instead

Output: export_out/<side>_best_ncnn_model/   -> copy this FOLDER to
        pcbx_inspection/models/ on the Pi. Put the printed imgsz in config.py.

NCNN files (.param/.bin) are platform-independent, so exporting on Colab or
a Windows PC and running on the Pi's ARM CPU is the normal workflow. If the
export ever fails on your PC, run this same script on the Pi itself.
"""
import argparse
import shutil
from pathlib import Path

from common import HERE, default_dataset_dir, load_hyp, rect_export_size


def compare(pt_path, ncnn_dir, images, imgsz_pt, imgsz_ncnn, conf=0.25):
    """Compare detections of the .pt and the NCNN model on a few images."""
    from ultralytics import YOLO
    a, b = YOLO(str(pt_path)), YOLO(str(ncnn_dir), task="detect")
    worst = 0
    for img in images:
        ra = a.predict(str(img), imgsz=imgsz_pt, conf=conf, verbose=False)[0]
        rb = b.predict(str(img), imgsz=imgsz_ncnn, conf=conf, verbose=False)[0]
        na, nb = len(ra.boxes), len(rb.boxes)
        worst = max(worst, abs(na - nb))
        print(f"  {img.name:40} pt={na:3d} boxes  ncnn={nb:3d} boxes")
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--weights", type=Path, required=True)
    ap.add_argument("--format", default="ncnn", help="ncnn (Pi), onnx, openvino, ...")
    ap.add_argument("--square", action="store_true", help="export imgsz x imgsz")
    ap.add_argument("--half", action="store_true", help="FP16 weights (test accuracy!)")
    ap.add_argument("--dataset", type=Path)
    args = ap.parse_args()

    from ultralytics import YOLO
    train_imgsz = load_hyp(args.side)["imgsz"]
    imgsz = train_imgsz if args.square else list(rect_export_size(train_imgsz))
    print(f"Exporting {args.weights} to {args.format} with imgsz={imgsz}")
    exported = Path(YOLO(str(args.weights)).export(format=args.format, imgsz=imgsz,
                                                    half=args.half))
    out_dir = HERE / "export_out"
    out_dir.mkdir(exist_ok=True)
    target = out_dir / f"{args.side}_best_{args.format}_model"
    if target.exists():
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    shutil.move(str(exported), str(target))
    print(f"Saved {target}")

    val_dir = (args.dataset or default_dataset_dir(args.side)) / "images" / "val"
    imgs = sorted(val_dir.glob("*.jpg"))[:5] if val_dir.is_dir() else []
    if imgs and args.format == "ncnn":
        print("Checking exported model against the .pt on validation images:")
        diff = compare(args.weights, target, imgs, train_imgsz, imgsz)
        print("  OK - same number of boxes" if diff <= 1 else
              f"  WARNING: box count differs by up to {diff}. Validate the NCNN model with "
              f"validate.py --weights {target} --imgsz {' '.join(map(str, imgsz)) if isinstance(imgsz, list) else imgsz}")
    shape = tuple(imgsz) if isinstance(imgsz, list) else (imgsz, imgsz)
    print(f"\nIn pcbx_inspection/config.py set MODELS['{args.side}'] = "
          f"path '{target.name}', imgsz {shape}")


if __name__ == "__main__":
    main()
