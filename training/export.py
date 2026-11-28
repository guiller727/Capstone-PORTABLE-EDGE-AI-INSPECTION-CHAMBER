#!/usr/bin/env python3
"""
export.py - convert best.pt into an NCNN model folder for the Raspberry Pi 5
and check that the exported model gives the same detections as the .pt.

  python export.py --side top    --weights weights_out/top_yolov8n_best.pt
  python export.py --side bottom --weights weights_out/bottom_yolo26n_best.pt
  python export.py --side bottom --weights ... --square      # square input instead

Output: export_out/<side>_best_ncnn_model/

V2 - install straight into a PCB profile (recommended):
  python export.py --side top --weights weights_out/top_yolov8n_best.pt \
         --profile-dir ../pcbx_inspection/models/pcb_x
  -> models/pcb_x/top/best.pt + models/pcb_x/top/best_ncnn_model/, and
     metadata.json (imgsz, training info) updated. Class names are checked
     against metadata.json (use --update-classes only if you changed classes
     on purpose). Then copy the pcbx_inspection/models/pcb_x folder to the Pi
     and run tools/check_profile.py there.

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
    ap.add_argument("--train-imgsz", type=int, help="imgsz used in training (default: hyp)")
    ap.add_argument("--profile-dir", type=Path, help="install into this PCB profile folder")
    ap.add_argument("--update-classes", action="store_true")
    args = ap.parse_args()

    from ultralytics import YOLO
    train_imgsz = args.train_imgsz or load_hyp(args.side)["imgsz"]
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
    if args.profile_dir:
        install(args, target, imgsz, train_imgsz)
    else:
        shape = tuple(imgsz) if isinstance(imgsz, list) else (imgsz, imgsz)
        print(f"\nNext: copy {target.name} to pcbx_inspection/models/<profile>/{args.side}/"
              f"best_ncnn_model and set imgsz {list(shape)} in metadata.json "
              "(or re-run with --profile-dir to do it automatically).")


def install(args, target, imgsz, train_imgsz):
    """Copy the models into a PCB profile and update its metadata.json."""
    import json
    from datetime import date

    import ultralytics
    from ultralytics import YOLO
    meta_p = args.profile_dir / "metadata.json"
    if not meta_p.exists():
        raise SystemExit(f"{meta_p} not found - is --profile-dir a PCB profile folder?")
    meta = json.loads(meta_p.read_text())
    names = YOLO(str(args.weights)).names
    names = [names[k] for k in sorted(names)]
    sd = meta["sides"][args.side]
    if names != sd["classes"]:
        if not args.update_classes:
            raise SystemExit(f"Model classes {names} differ from metadata.json {sd['classes']}.\n"
                             "Wrong side? If the class list changed on purpose, add "
                             "--update-classes (and rebuild the golden reference).")
        sd["classes"] = names
    side_dir = args.profile_dir / args.side
    side_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.weights, side_dir / "best.pt")
    if args.format == "ncnn":
        dst = side_dir / "best_ncnn_model"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(target, dst)
        sd["model"]["ncnn"] = f"{args.side}/best_ncnn_model"
        sd["model"]["imgsz"] = imgsz if isinstance(imgsz, list) else [imgsz, imgsz]
    sd["model"]["pt"] = f"{args.side}/best.pt"
    sd["model"]["pt_imgsz"] = train_imgsz
    meta.setdefault("training", {}).update({
        "ultralytics": ultralytics.__version__, f"{args.side}_weights": args.weights.name,
        f"{args.side}_exported": date.today().isoformat()})
    meta_p.write_text(json.dumps(meta, indent=2))
    print(f"\nInstalled into {side_dir} and updated {meta_p}.\n"
          "On the Pi: python tools/check_profile.py")


if __name__ == "__main__":
    main()
