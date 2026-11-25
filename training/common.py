"""
common.py - shared helpers for train.py / validate.py / export.py /
learning_curve.py and the dataset tools. Works on Windows, Linux and Colab.
"""
import math
import platform
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent

# Canonical class lists. The ORDER defines the class IDs (0, 1, 2, ...).
# Must match pcbx_inspection/config.py MODELS[side]["classes"].
CLASSES = {
    "top": ["electrolytic_cap", "inductor", "transformer", "varistor",
            "fuse", "terminal_block", "connector"],
    "bottom": ["resistor", "smd_capacitor", "diode", "ic8"],
}

# Canvas produced by the Pi software (config.py): 1200 x 500 px at 10 px/mm.
CANVAS_W, CANVAS_H = 1200, 500


def load_hyp(side: str) -> dict:
    return yaml.safe_load((HERE / "configs" / f"hyp_{side}.yaml").read_text())


def default_dataset_dir(side: str) -> Path:
    return HERE / "datasets" / f"pcbx_{side}"


def write_data_yaml(dataset_dir: Path, side: str) -> Path:
    """Write pcbx_<side>.yaml INSIDE the dataset folder and return an
    ABSOLUTE-path copy for training.

    Why absolute? If 'path' in a data YAML is relative, Ultralytics resolves
    it against its own 'datasets_dir' setting, not against your current
    folder - the most common cause of "images not found" errors.
    """
    dataset_dir = Path(dataset_dir).resolve()
    names = {i: n for i, n in enumerate(CLASSES[side])}
    portable = {"train": "images/train", "val": "images/val", "test": "images/test",
                "names": names}
    (dataset_dir / f"pcbx_{side}.yaml").write_text(
        "# Portable version (no absolute path). train.py creates the resolved copy.\n"
        + yaml.safe_dump(portable, sort_keys=False))
    resolved = dict(portable)
    resolved = {"path": dataset_dir.as_posix(), **resolved}
    out = dataset_dir / f"_resolved_pcbx_{side}.yaml"
    out.write_text(yaml.safe_dump(resolved, sort_keys=False))
    return out


def pick_device(requested: str = "auto"):
    if requested != "auto":
        return requested
    import torch
    if torch.cuda.is_available():
        return 0
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def safe_workers(hyp_workers: int) -> int:
    """Windows multiprocessing data loaders are a common source of crashes."""
    return 0 if platform.system() == "Windows" else hyp_workers


def rect_export_size(imgsz: int, canvas_w=CANVAS_W, canvas_h=CANVAS_H):
    """(h, w) for a rectangular export matching the canvas aspect ratio.

    Validation in Ultralytics already letterboxes rectangularly (rect=True),
    so a rectangular NCNN model sees images exactly like validation did,
    while computing ~60 % fewer pixels than a square imgsz x imgsz input.
    """
    scale = imgsz / max(canvas_w, canvas_h)
    h = int(math.ceil(canvas_h * scale / 32) * 32)
    w = int(math.ceil(canvas_w * scale / 32) * 32)
    return h, w


def board_id_from_name(name: str, regex: str = r"^([A-Za-z]+\d+)_") -> str:
    import re
    m = re.match(regex, name)
    return m.group(1) if m else "UNKNOWN"
