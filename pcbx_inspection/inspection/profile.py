"""
inspection/profile.py - NEW in V2: a "PCB profile" is one folder that holds
everything specific to one PCB model, so a new board or a new trained model
can be installed WITHOUT changing program code.

models/
└── pcb_x/                         <- profile name (config.ACTIVE_PROFILE)
    ├── metadata.json              board size, sides, model files, classes
    ├── golden_reference.json      expected components + tolerances (both sides)
    ├── board_profile.json         identification markers + fiducials (both sides)
    ├── templates/                 marker / whole-board template images
    ├── top/                       FRONT (Side A) model
    │   ├── best.pt                trained PyTorch weights (keep: source of truth)
    │   └── best_ncnn_model/       NCNN export (used on the Pi when present)
    └── bottom/                    BACK (Side B) model

Model format decision (Raspberry Pi 5):
  Ultralytics' Pi 5 benchmark (YOLO26n, 640 px, CPU) lists ~299 ms/image for
  PyTorch and ~67 ms/image for NCNN (network only), with the same accuracy.
  So the Pi uses the NCNN folder when it exists (config.PREFER_NCNN) and falls
  back to best.pt, which also works - just slower. ONNX (~126 ms) offers no
  advantage over NCNN on this CPU.
"""
import json
import logging
import re
from pathlib import Path

from .golden_reference import GoldenError, load_golden

log = logging.getLogger(__name__)


class ProfileError(RuntimeError):
    pass


class ModelError(RuntimeError):
    pass


def list_profiles(models_dir: Path):
    out = []
    for meta in sorted(Path(models_dir).glob("*/metadata.json")):
        try:
            m = json.loads(meta.read_text())
            out.append({"name": meta.parent.name, "board": m.get("board_name", "?"),
                        "description": m.get("description", "")})
        except Exception as exc:
            out.append({"name": meta.parent.name, "board": "INVALID", "description": str(exc)})
    return out


def _ncnn_names(folder: Path):
    """Read class names from an Ultralytics NCNN export's metadata.yaml."""
    meta = folder / "metadata.yaml"
    if not meta.exists():
        return None
    text = meta.read_text()
    try:
        import yaml
        names = yaml.safe_load(text).get("names")
        return [names[k] for k in sorted(names)] if isinstance(names, dict) else names
    except Exception:
        block = re.search(r"names:\s*\n((?:\s+\d+:.*\n?)+)", text)
        if not block:
            return None
        return [ln.split(":", 1)[1].strip().strip("'\"") for ln in block.group(1).splitlines()
                if ":" in ln]


class Profile:
    def __init__(self, models_dir: Path, name: str):
        self.name = name
        self.dir = Path(models_dir) / name
        mp = self.dir / "metadata.json"
        if not mp.exists():
            raise ProfileError(f"Profile '{name}' not found: {mp} is missing")
        try:
            self.meta = json.loads(mp.read_text())
        except json.JSONDecodeError as exc:
            raise ProfileError(f"{mp} is not valid JSON (line {exc.lineno}: {exc.msg})") from exc
        errs = self.validate_metadata()
        if errs:
            raise ProfileError(f"{mp} invalid: " + "; ".join(errs))

    # ---------------------------------------------------------------- metadata
    def validate_metadata(self):
        m, errs = self.meta, []
        size = m.get("board_size_mm")
        if not (isinstance(size, list) and len(size) == 2 and all(
                isinstance(v, (int, float)) and v > 0 for v in size)):
            errs.append("board_size_mm must be [width, height]")
        sides = m.get("sides")
        if not isinstance(sides, dict) or not sides:
            errs.append("sides missing")
            return errs
        for side, sd in sides.items():
            if side not in ("top", "bottom"):
                errs.append(f"unknown side {side!r}")
            cls = sd.get("classes")
            if not (isinstance(cls, list) and cls and all(isinstance(c, str) for c in cls)):
                errs.append(f"sides.{side}.classes must be a list of class names")
            elif len(set(cls)) != len(cls):
                errs.append(f"sides.{side}.classes has duplicates")
            if not isinstance(sd.get("model"), dict):
                errs.append(f"sides.{side}.model missing")
        return errs

    @property
    def board_name(self):
        return self.meta.get("board_name", self.name)

    @property
    def board_size(self):
        return tuple(self.meta["board_size_mm"])

    def canvas_params(self, default_ppm=10.0, default_margin=2.5):
        c = self.meta.get("canvas", {})
        return float(c.get("px_per_mm", default_ppm)), float(c.get("margin_mm", default_margin))

    def sides(self):
        return [s for s in ("top", "bottom") if s in self.meta["sides"]]

    def classes(self, side):
        return list(self.meta["sides"][side]["classes"])

    def classes_by_side(self):
        return {s: self.classes(s) for s in self.sides()}

    def label(self, side):
        return self.meta["sides"][side].get("label", side)

    def file(self, key, default):
        return self.dir / self.meta.get("files", {}).get(key, default)

    @property
    def golden_path(self):
        return self.file("golden_reference", "golden_reference.json")

    @property
    def board_profile_path(self):
        return self.file("board_profile", "board_profile.json")

    # ---------------------------------------------------------------- data files
    def load_golden(self):
        return load_golden(self.golden_path, self.classes_by_side())

    def load_board_profile(self):
        p = self.board_profile_path
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError as exc:
            raise ProfileError(f"{p.name} is not valid JSON (line {exc.lineno})") from exc

    # ---------------------------------------------------------------- models
    def model_info(self, side, prefer_ncnn=True):
        """Return (path, format, imgsz) of the model to load. Raises ModelError."""
        md = self.meta["sides"][side]["model"]
        imgsz = md.get("imgsz", 640)
        cands = []
        if md.get("ncnn"):
            cands.append((self.dir / md["ncnn"], "ncnn"))
        if md.get("pt"):
            cands.append((self.dir / md["pt"], "pt"))
        if not prefer_ncnn:
            cands.reverse()
        tried = []
        for path, fmt in cands:
            if fmt == "ncnn":
                need = ["model.ncnn.param", "model.ncnn.bin", "metadata.yaml"]
                if path.is_dir() and all((path / f).exists() for f in need):
                    return path, fmt, imgsz
                tried.append(f"{path.relative_to(self.dir)} (needs {', '.join(need)})")
            else:
                if path.is_file() and path.stat().st_size > 100_000:
                    return path, fmt, md.get("pt_imgsz", imgsz)
                tried.append(f"{path.relative_to(self.dir)}"
                             + (" (file too small - not a trained model)" if path.is_file() else ""))
        raise ModelError(f"No usable {side} model in profile '{self.name}'. Looked for: "
                         + "; ".join(tried) + ". Train the model and copy it there "
                         "(docs/MODEL_INTEGRATION.md).")

    def check_model_files(self, side, prefer_ncnn=True):
        """Validate without loading PyTorch/NCNN (fast; used by the GUI)."""
        path, fmt, imgsz = self.model_info(side, prefer_ncnn)
        if fmt == "ncnn":
            names = _ncnn_names(path)
            if names is not None and names != self.classes(side):
                raise ModelError(f"{side} NCNN model classes {names} differ from metadata "
                                 f"classes {self.classes(side)} - wrong model or wrong side?")
        return {"path": str(path), "format": fmt, "imgsz": imgsz}

    def problems(self, prefer_ncnn=True):
        """Every reason this profile cannot inspect yet (empty list = ready)."""
        out = []
        try:
            g = self.load_golden()
            for side in self.sides():
                if side not in g.get("sides", {}):
                    out.append(f"golden_reference.json has no '{side}' side yet - "
                               f"run tools/build_golden_reference.py --side {side}")
        except GoldenError as exc:
            out.append(str(exc))
        if not self.board_profile_path.exists():
            out.append(f"{self.board_profile_path.name} missing - run tools/build_board_profile.py")
        for side in self.sides():
            try:
                self.check_model_files(side, prefer_ncnn)
            except ModelError as exc:
                out.append(str(exc))
        return out
