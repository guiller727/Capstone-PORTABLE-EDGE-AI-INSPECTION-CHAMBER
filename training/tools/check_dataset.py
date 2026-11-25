#!/usr/bin/env python3
"""
tools/check_dataset.py - verify a YOLO dataset BEFORE spending GPU time.

  python tools/check_dataset.py --side bottom
  python tools/check_dataset.py --dataset datasets/pcbx_top --side top --previews 20

Checks
  * folder structure images/{train,val,test} + labels/{train,val,test}
  * every image has a label file and vice versa
  * label lines: 5 values, class id in range, coordinates in 0..1, w,h > 0
  * image size (warns if not the 1200x500 canvas)
  * the SAME board ID does not appear in two splits (data leakage)
  * instances per class per split (a class with 0 val instances cannot be scored)
  * writes preview images with drawn boxes -> look at them! (_previews/)
Exit code 1 if an ERROR was found.
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

from common import CANVAS_H, CANVAS_W, CLASSES, board_id_from_name, default_dataset_dir  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp"}
COLORS = [(0, 255, 0), (0, 0, 255), (255, 0, 0), (0, 255, 255), (255, 0, 255),
          (255, 255, 0), (0, 128, 255)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=["top", "bottom"], required=True)
    ap.add_argument("--dataset", type=Path)
    ap.add_argument("--previews", type=int, default=12)
    args = ap.parse_args()
    root = (args.dataset or default_dataset_dir(args.side)).resolve()
    names = CLASSES[args.side]
    errors, warns = [], []
    counts = {s: Counter() for s in ("train", "val", "test")}
    n_imgs = Counter()
    boards_in = defaultdict(set)
    sizes = Counter()
    prev_dir = root / "_previews"
    prev_dir.mkdir(exist_ok=True)
    made = 0

    for s in ("train", "val", "test"):
        idir, ldir = root / "images" / s, root / "labels" / s
        if not idir.is_dir() or not ldir.is_dir():
            errors.append(f"missing folder {idir} or {ldir}")
            continue
        imgs = {p.stem: p for p in idir.iterdir() if p.suffix.lower() in IMG_EXT}
        lbls = {p.stem: p for p in ldir.glob("*.txt")}
        for stem in sorted(set(lbls) - set(imgs)):
            errors.append(f"{s}: label without image: {stem}.txt")
        for stem, ip in sorted(imgs.items()):
            n_imgs[s] += 1
            boards_in[board_id_from_name(ip.name)].add(s)
            lp = lbls.get(stem)
            if lp is None:
                errors.append(f"{s}: image without label file: {ip.name}")
                continue
            boxes = []
            for k, line in enumerate(lp.read_text().splitlines(), 1):
                p = line.split()
                if not p:
                    continue
                if len(p) != 5:
                    errors.append(f"{lp.name}:{k}: expected 5 values, got {len(p)}")
                    continue
                c, x, y, w, h = int(p[0]), *map(float, p[1:])
                if not 0 <= c < len(names):
                    errors.append(f"{lp.name}:{k}: class id {c} out of range 0..{len(names) - 1}")
                    continue
                if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
                    errors.append(f"{lp.name}:{k}: coordinates not normalised 0..1")
                counts[s][names[c]] += 1
                boxes.append((c, x, y, w, h))
            if made < args.previews:
                img = cv2.imread(str(ip))
                if img is None:
                    errors.append(f"unreadable image {ip}")
                    continue
                H, W = img.shape[:2]
                sizes[(W, H)] += 1
                for c, x, y, w, h in boxes:
                    p1 = (int((x - w / 2) * W), int((y - h / 2) * H))
                    p2 = (int((x + w / 2) * W), int((y + h / 2) * H))
                    cv2.rectangle(img, p1, p2, COLORS[c % len(COLORS)], 2)
                    cv2.putText(img, names[c], (p1[0], max(10, p1[1] - 3)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLORS[c % len(COLORS)], 1)
                cv2.imwrite(str(prev_dir / f"{s}_{ip.stem}.jpg"), img)
                made += 1

    for b, splits in boards_in.items():
        if len(splits) > 1:
            errors.append(f"board {b} appears in {sorted(splits)} -> data leakage")
    for (w, h), n in sizes.items():
        if (w, h) != (CANVAS_W, CANVAS_H):
            warns.append(f"{n} preview images are {w}x{h}, not the {CANVAS_W}x{CANVAS_H} canvas")

    print(f"Dataset: {root}")
    print(f"{'class':18}" + "".join(f"{s:>8}" for s in ("train", "val", "test")))
    for n in names:
        print(f"{n:18}" + "".join(f"{counts[s][n]:8d}" for s in ("train", "val", "test")))
        if counts["val"][n] == 0:
            warns.append(f"class '{n}' has 0 validation instances")
        if counts["train"][n] < 30:
            warns.append(f"class '{n}' has only {counts['train'][n]} training instances (< 30)")
    print(f"{'images':18}" + "".join(f"{n_imgs[s]:8d}" for s in ("train", "val", "test")))
    print(f"boards: {len(boards_in)}")
    for w in warns:
        print("WARNING:", w)
    for e in errors[:50]:
        print("ERROR:", e)
    print(f"Previews with boxes: {prev_dir}")
    if errors:
        print(f"\n{len(errors)} ERROR(S) - fix before training.")
        sys.exit(1)
    print("\nDataset OK.")


if __name__ == "__main__":
    main()
