#!/usr/bin/env python3
"""
tools/prepare_dataset.py - turn a Label Studio "YOLO with Images" export into
the training folder structure, split 70/15/15 BY PHYSICAL BOARD.

  python tools/prepare_dataset.py --export project-3-at-2026-11-25.zip --side bottom
  python tools/prepare_dataset.py --export ls_export_top/ --side top \
         --test-boards B19 B20 B21 --val-boards B16 B17 B18

What it fixes automatically
  * Label Studio's class order (classes.txt) may differ from ours -> class IDs
    are REMAPPED by class NAME to the canonical order in common.py.
  * Label Studio prefixes uploaded file names with a hash ("3f2a9c1d-B07_...").
    The prefix is removed so the board ID (B07) is at the start again.
  * Images without a label file become "background" images (empty .txt),
    with a warning - make sure they really have no parts (e.g. empty tray).

Result:
  datasets/pcbx_<side>/images/{train,val,test}/*.jpg
  datasets/pcbx_<side>/labels/{train,val,test}/*.txt
  datasets/pcbx_<side>/pcbx_<side>.yaml
  datasets/pcbx_<side>/split_report.csv
Choose --test-boards yourself so the test set contains DEFECTIVE boards.
"""
import argparse
import csv
import json
import random
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CLASSES, board_id_from_name, default_dataset_dir, write_data_yaml  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp"}
LS_PREFIX = re.compile(r"^[0-9a-f]{8}-")


def find_one(root: Path, name: str):
    hits = sorted(root.rglob(name), key=lambda p: len(p.parts))
    return hits[0] if hits else None


def read_class_names(root: Path):
    ct = find_one(root, "classes.txt")
    if ct is not None and ct.read_text().strip():
        return [l.strip() for l in ct.read_text().splitlines() if l.strip()]
    nj = find_one(root, "notes.json")
    if nj is not None:
        cats = json.loads(nj.read_text())["categories"]
        return [c["name"] for c in sorted(cats, key=lambda c: c["id"])]
    sys.exit("No classes.txt or notes.json found in the export. Export as 'YOLO with Images'.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", type=Path, required=True, help="Label Studio zip or folder")
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--out", type=Path, help="default: training/datasets/pcbx_<side>")
    ap.add_argument("--ratios", type=float, nargs=3, default=[0.70, 0.15, 0.15])
    ap.add_argument("--val-boards", nargs="*", default=None)
    ap.add_argument("--test-boards", nargs="*", default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--board-regex", default=r"^([A-Za-z]+\d+)_")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    tmp = None
    root = args.export
    if args.export.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp())
        with zipfile.ZipFile(args.export) as z:
            z.extractall(tmp)
        root = tmp

    src_names = read_class_names(root)
    canon = CLASSES[args.side]
    unknown = [n for n in src_names if n not in canon]
    if unknown:
        sys.exit(f"Class names {unknown} are not in the {args.side} class list {canon}.\n"
                 "Fix the Label Studio labeling config (names must match exactly).")
    remap = {i: canon.index(n) for i, n in enumerate(src_names)}
    print("Class remap (Label Studio id -> training id):",
          {f"{i}:{src_names[i]}": j for i, j in remap.items()})

    img_dir = next((p for p in root.rglob("images") if p.is_dir()), None)
    lbl_dir = next((p for p in root.rglob("labels") if p.is_dir()), None)
    if img_dir is None:
        sys.exit("No images/ folder in the export. Use 'YOLO with Images'.")
    images = sorted(p for p in img_dir.rglob("*") if p.suffix.lower() in IMG_EXT)
    print(f"{len(images)} images found")

    items, warnings = [], []
    for img in images:
        clean = LS_PREFIX.sub("", img.name)
        lbl = (lbl_dir / img.relative_to(img_dir)).with_suffix(".txt") if lbl_dir else None
        lines = []
        if lbl is not None and lbl.exists():
            for k, line in enumerate(lbl.read_text().splitlines(), 1):
                parts = line.split()
                if not parts:
                    continue
                if len(parts) != 5:
                    warnings.append(f"{lbl.name}:{k} has {len(parts)} values (not a box) - skipped")
                    continue
                c = int(parts[0])
                vals = [float(v) for v in parts[1:]]
                if not all(0.0 <= v <= 1.0 for v in vals):
                    warnings.append(f"{lbl.name}:{k} coordinates outside 0..1 - clipped")
                    vals = [min(1.0, max(0.0, v)) for v in vals]
                lines.append(f"{remap[c]} " + " ".join(f"{v:.6f}" for v in vals))
        else:
            warnings.append(f"{img.name}: no label file -> background image")
        board = board_id_from_name(clean, args.board_regex)
        if board == "UNKNOWN":
            warnings.append(f"{clean}: name does not start with a board ID (e.g. B07_)")
        items.append((img, clean, lines, board))

    boards = sorted({b for *_, b in items})
    rng = random.Random(args.seed)
    if args.test_boards is not None or args.val_boards is not None:
        test = set(args.test_boards or [])
        val = set(args.val_boards or [])
        missing = (test | val) - set(boards)
        if missing:
            sys.exit(f"Boards {sorted(missing)} not found. Present: {boards}")
    else:
        shuffled = boards[:]
        rng.shuffle(shuffled)
        n = len(shuffled)
        n_test = max(1, round(args.ratios[2] * n))
        n_val = max(1, round(args.ratios[1] * n))
        if n < 3:
            sys.exit(f"Only {n} board ID(s). A board-wise split needs >= 3 boards "
                     "(see docs: what to do with few boards).")
        test, val = set(shuffled[:n_test]), set(shuffled[n_test:n_test + n_val])
    split_of = {b: "test" if b in test else "val" if b in val else "train" for b in boards}

    out = (args.out or default_dataset_dir(args.side)).resolve()
    if out.exists():
        if not args.overwrite:
            sys.exit(f"{out} exists. Use --overwrite to replace it.")
        shutil.rmtree(out)
    for s in ("train", "val", "test"):
        (out / "images" / s).mkdir(parents=True)
        (out / "labels" / s).mkdir(parents=True)

    report = []
    for img, clean, lines, board in items:
        s = split_of[board]
        shutil.copy2(img, out / "images" / s / clean)
        (out / "labels" / s / Path(clean).with_suffix(".txt").name).write_text(
            "\n".join(lines) + ("\n" if lines else ""))
        report.append({"file": clean, "board": board, "split": s, "boxes": len(lines)})
    with open(out / "split_report.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["file", "board", "split", "boxes"])
        w.writeheader()
        w.writerows(report)
    write_data_yaml(out, args.side)

    for s in ("train", "val", "test"):
        bs = sorted(b for b, v in split_of.items() if v == s)
        n_img = sum(1 for r in report if r["split"] == s)
        print(f"{s:5}: {len(bs):2d} boards {bs}  {n_img} images")
    for w_ in warnings[:30]:
        print("WARNING:", w_)
    if len(warnings) > 30:
        print(f"... {len(warnings) - 30} more warnings")
    print(f"\nDataset written to {out}\nNext: python tools/check_dataset.py --side {args.side}")
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
