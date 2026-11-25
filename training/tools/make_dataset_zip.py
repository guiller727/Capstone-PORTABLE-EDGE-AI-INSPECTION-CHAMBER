#!/usr/bin/env python3
"""
tools/make_dataset_zip.py - pack datasets/pcbx_top and datasets/pcbx_bottom
into ONE zip for Google Drive / Colab.

  python tools/make_dataset_zip.py            -> pcbx_dataset.zip

Why not Windows "Send to > Compressed folder" or PowerShell Compress-Archive?
Some versions store paths with backslashes, which Linux (Colab) then extracts
as file names like "images\\train\\B01.jpg" instead of folders. Python's
zipfile always writes forward slashes.
"""
import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import HERE  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", type=Path, default=HERE / "datasets")
    ap.add_argument("--out", type=Path, default=HERE / "pcbx_dataset.zip")
    args = ap.parse_args()
    n = 0
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_STORED) as z:   # JPEGs don't compress
        for side in ("top", "bottom"):
            d = args.datasets / f"pcbx_{side}"
            if not d.is_dir():
                print(f"skip {d} (not found)")
                continue
            for p in sorted(d.rglob("*")):
                if p.is_file() and "_previews" not in p.parts and not p.name.startswith("_resolved"):
                    z.write(p, p.relative_to(args.datasets).as_posix())
                    n += 1
    print(f"Wrote {n} files to {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")
    print("Upload it to Google Drive as  MyDrive/PCBX/pcbx_dataset.zip")


if __name__ == "__main__":
    main()
