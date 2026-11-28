"""
inspection/golden_reference.py - expected components, tolerances and
thresholds for BOTH sides of a PCB (V2: one file per PCB profile).

File: models/<profile>/golden_reference.json   (schema_version 2)
{
  "schema_version": 2,
  "profile": "pcb_x",  "board": "PCB X",
  "board_size_mm": [115.0, 45.0],
  "canvas": {"px_per_mm": 10.0, "margin_mm": 2.5},
  "coordinate_system": "...",           # documentation string
  "revision": 4, "modified": "2026-11-27T21:30:00", "modified_by": "gui",
  "sides": {
    "top": {
      "label": "FRONT - Side A",
      "thresholds": {"t_low": 0.25, "t_high": 0.60},
      "default_tolerance": {"tol_mm": 1.0, "tol_x_mm": null, "tol_y_mm": null},
      "class_tolerance": {"transformer": {"tol_mm": 1.5}},
      "built_from": {"images": 30, "boards": 10, "date": "2026-12-10"},
      "components": [
        {"id": "T1", "class": "transformer", "x_mm": 66.2, "y_mm": 19.8,
         "w_mm": 24.0, "h_mm": 22.0, "x_norm": 0.5757, "y_norm": 0.44,
         "tol_mm": null, "tol_x_mm": null, "tol_y_mm": null, "required": true,
         "std_x_mm": 0.05, "std_y_mm": 0.04, "seen": 30}
      ]
    },
    "bottom": { ... same structure ... }
  }
}

Coordinates: millimetres on the BOARD, origin at the board's top-left corner
in the normalised (identified + orientation-corrected) view of that side,
x to the right, y down. Millimetres are already independent of camera
resolution and px/mm; x_norm/y_norm (0..1 of board width/height) are written
automatically for readability and are not used for matching.

Tolerance resolution for one component (first non-null wins):
  component field  ->  class_tolerance[class]  ->  default_tolerance  ->  1.0 mm
tol_mm   = maximum RADIAL offset sqrt(dx^2 + dy^2)
tol_x_mm = maximum |dx| (optional, null = not checked)
tol_y_mm = maximum |dy| (optional, null = not checked)

Saving (GUI, tools) goes through save_golden_safe(): validate -> backup the
current file to backups/ -> write to a temp file -> atomic rename. An
invalid golden reference can therefore never replace a valid one.
"""
import copy
import hashlib
import json
import math
import os
import shutil
from datetime import date, datetime
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 2
ID_PREFIX = {"resistor": "R", "smd_capacitor": "C", "diode": "D", "ic8": "IC",
             "electrolytic_cap": "C", "film_capacitor": "C", "ceramic_capacitor": "C",
             "inductor": "L", "transformer": "T", "varistor": "VAR", "fuse": "F",
             "connector": "CN", "terminal_block": "TB"}
TOL_KEYS = ("tol_mm", "tol_x_mm", "tol_y_mm")
TOL_RANGE = (0.05, 10.0)
MAX_BACKUPS = 30


class GoldenError(ValueError):
    """Raised when a golden reference is missing or invalid."""


# ----------------------------------------------------------------------------- load
def load_golden(path: Path, classes_by_side: dict = None) -> dict:
    path = Path(path)
    if not path.exists():
        raise GoldenError(f"{path} not found - build it with tools/build_golden_reference.py")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise GoldenError(f"{path.name} is not valid JSON: line {exc.lineno}: {exc.msg}") from exc
    errors, _ = validate_golden(data, classes_by_side)
    if errors:
        raise GoldenError(f"{path.name} is invalid:\n  - " + "\n  - ".join(errors[:15]))
    return data


def side_section(data: dict, side: str) -> dict:
    return (data.get("sides") or {}).get(side) or {}


def thresholds(data: dict, side: str, fallback=(0.25, 0.60)):
    th = side_section(data, side).get("thresholds") or {}
    return float(th.get("t_low", fallback[0])), float(th.get("t_high", fallback[1]))


def effective_tolerance(side_data: dict, comp: dict) -> dict:
    """Resolve tol_mm / tol_x_mm / tol_y_mm for one component."""
    cls_tol = (side_data.get("class_tolerance") or {}).get(comp.get("class"), {}) or {}
    default = side_data.get("default_tolerance") or {}
    out = {}
    for k in TOL_KEYS:
        for source in (comp, cls_tol, default):
            v = source.get(k)
            if v is not None:
                out[k] = float(v)
                break
        else:
            out[k] = 1.0 if k == "tol_mm" else None
    return out


def resolved_components(side_data: dict):
    """Copies of the components with their EFFECTIVE tolerances filled in -
    this is what matching and the decision rules use."""
    out = []
    for c in side_data.get("components", []):
        r = dict(c)
        r.update(effective_tolerance(side_data, c))
        r.setdefault("required", True)
        out.append(r)
    return out


def golden_hash(data: dict) -> str:
    """Short fingerprint stored with every inspection result."""
    core = {k: v for k, v in data.items() if k not in ("modified", "modified_by")}
    return hashlib.sha1(json.dumps(core, sort_keys=True).encode()).hexdigest()[:10]


# ----------------------------------------------------------------------------- validate
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_golden(data: dict, classes_by_side: dict = None):
    """Return (errors, warnings). errors -> file must not be used/saved."""
    errors, warns = [], []
    if not isinstance(data, dict):
        return ["top level must be a JSON object"], warns
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION} "
                      f"(found {data.get('schema_version')!r})")
    size = data.get("board_size_mm")
    if not (isinstance(size, list) and len(size) == 2 and all(_num(v) and v > 0 for v in size)):
        errors.append("board_size_mm must be [width, height] in mm")
        size = [1e9, 1e9]
    sides = data.get("sides")
    if not isinstance(sides, dict) or not sides:
        errors.append("'sides' must contain 'top' and/or 'bottom'")
        return errors, warns
    for side, sd in sides.items():
        where = f"sides.{side}"
        if side not in ("top", "bottom"):
            errors.append(f"{where}: unknown side (use 'top' = front, 'bottom' = back)")
            continue
        th = sd.get("thresholds", {})
        t_low, t_high = th.get("t_low", 0.25), th.get("t_high", 0.60)
        if not (_num(t_low) and _num(t_high) and 0.0 < t_low < t_high < 1.0):
            errors.append(f"{where}.thresholds: need 0 < t_low < t_high < 1 "
                          f"(got {t_low}, {t_high})")
        for name, block in [("default_tolerance", sd.get("default_tolerance", {}))] + \
                [(f"class_tolerance.{c}", v) for c, v in (sd.get("class_tolerance") or {}).items()]:
            if not isinstance(block, dict):
                errors.append(f"{where}.{name} must be an object")
                continue
            for k in TOL_KEYS:
                v = block.get(k)
                if v is not None and not (_num(v) and TOL_RANGE[0] <= v <= TOL_RANGE[1]):
                    errors.append(f"{where}.{name}.{k} must be {TOL_RANGE[0]}..{TOL_RANGE[1]} mm "
                                  f"or null (got {v!r})")
        comps = sd.get("components")
        if not isinstance(comps, list):
            errors.append(f"{where}.components must be a list")
            continue
        if not comps:
            errors.append(f"{where}.components is empty - an empty reference would PASS "
                          "every board. Build it with tools/build_golden_reference.py")
        ids = set()
        allowed = (classes_by_side or {}).get(side)
        for i, c in enumerate(comps):
            cw = f"{where}.components[{i}]"
            cid = c.get("id")
            if not isinstance(cid, str) or not cid.strip():
                errors.append(f"{cw}: id must be a non-empty text")
            elif cid in ids:
                errors.append(f"{cw}: duplicate id {cid!r}")
            ids.add(cid)
            cls = c.get("class")
            if not isinstance(cls, str):
                errors.append(f"{cw} ({cid}): class missing")
            elif allowed and cls not in allowed:
                errors.append(f"{cw} ({cid}): class {cls!r} is not a class of the {side} model "
                              f"{allowed}")
            for k in ("x_mm", "y_mm", "w_mm", "h_mm"):
                if not _num(c.get(k)):
                    errors.append(f"{cw} ({cid}): {k} must be a number")
            if _num(c.get("x_mm")) and _num(c.get("y_mm")):
                if not (-5 <= c["x_mm"] <= size[0] + 5 and -5 <= c["y_mm"] <= size[1] + 5):
                    errors.append(f"{cw} ({cid}): position ({c['x_mm']}, {c['y_mm']}) is "
                                  "outside the board")
            for k in ("w_mm", "h_mm"):
                if _num(c.get(k)) and c[k] <= 0:
                    errors.append(f"{cw} ({cid}): {k} must be > 0")
            for k in TOL_KEYS:
                v = c.get(k)
                if v is not None and not (_num(v) and TOL_RANGE[0] <= v <= TOL_RANGE[1]):
                    errors.append(f"{cw} ({cid}): {k} must be {TOL_RANGE[0]}..{TOL_RANGE[1]} mm "
                                  f"or null (got {v!r})")
            if "required" in c and not isinstance(c["required"], bool):
                errors.append(f"{cw} ({cid}): required must be true/false")
        # ambiguity check: same-class parts whose tolerance circles overlap
        valid = [c for c in comps if _num(c.get("x_mm")) and _num(c.get("y_mm"))]
        for a in range(len(valid)):
            for b in range(a + 1, len(valid)):
                ca, cb = valid[a], valid[b]
                if ca.get("class") != cb.get("class"):
                    continue
                d = math.hypot(ca["x_mm"] - cb["x_mm"], ca["y_mm"] - cb["y_mm"])
                ta = effective_tolerance(sd, ca)["tol_mm"]
                tb = effective_tolerance(sd, cb)["tol_mm"]
                if d < ta + tb:
                    warns.append(f"{side}: {ca.get('id')} and {cb.get('id')} ({ca.get('class')}) "
                                 f"are {d:.2f} mm apart but tolerances add to {ta + tb:.2f} mm - "
                                 "matches between them may be AMBIGUOUS (REVIEW)")
    return errors, warns


# ----------------------------------------------------------------------------- save
def _with_norm(data):
    out = copy.deepcopy(data)
    w, h = out["board_size_mm"]
    for sd in out["sides"].values():
        for c in sd.get("components", []):
            c["x_norm"] = round(c["x_mm"] / w, 5)
            c["y_norm"] = round(c["y_mm"] / h, 5)
    return out


def save_golden_safe(path: Path, data: dict, modified_by: str = "tool",
                     classes_by_side: dict = None) -> dict:
    """Validate, back up the old file, write atomically. Returns the saved data."""
    errors, _ = validate_golden(data, classes_by_side)
    if errors:
        raise GoldenError("Not saved - fix these first:\n  - " + "\n  - ".join(errors[:15]))
    path = Path(path)
    out = _with_norm(data)
    out["revision"] = int(data.get("revision", 0)) + 1
    out["modified"] = datetime.now().isoformat(timespec="seconds")
    out["modified_by"] = modified_by
    if path.exists():
        bdir = path.parent / "backups"
        bdir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, bdir / f"{path.stem}.rev{data.get('revision', 0)}.{stamp}.json")
        old = sorted(bdir.glob(f"{path.stem}.rev*.json"), key=os.path.getmtime)
        for f in old[:-MAX_BACKUPS]:
            f.unlink()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2))
    os.replace(tmp, path)
    return out


def list_backups(path: Path):
    bdir = Path(path).parent / "backups"
    return sorted(bdir.glob(f"{Path(path).stem}.rev*.json"), key=os.path.getmtime, reverse=True)


def restore_backup(path: Path, backup: Path, classes_by_side: dict = None) -> dict:
    data = json.loads(Path(backup).read_text())
    data["revision"] = json.loads(Path(path).read_text()).get("revision", 0) if Path(path).exists() else 0
    return save_golden_safe(path, data, modified_by=f"restore:{Path(backup).name}",
                            classes_by_side=classes_by_side)


def new_golden(profile: str, board: str, size_mm, canvas, side_labels: dict) -> dict:
    """Empty, valid golden reference skeleton for a new profile."""
    return {"schema_version": SCHEMA_VERSION, "profile": profile, "board": board,
            "board_size_mm": [float(size_mm[0]), float(size_mm[1])],
            "canvas": {"px_per_mm": canvas.ppm, "margin_mm": canvas.m},
            "coordinate_system": "mm on the board; origin = top-left corner of the "
                                 "identified, orientation-corrected side; x right, y down",
            "revision": 0,
            "sides": {s: {"label": side_labels.get(s, s),
                          "thresholds": {"t_low": 0.25, "t_high": 0.60},
                          "default_tolerance": {"tol_mm": 1.0, "tol_x_mm": None, "tol_y_mm": None},
                          "class_tolerance": {}, "components": []}
                      for s in ("top", "bottom")}}


# ----------------------------------------------------------------------------- build
def seed_components(observed):
    """Give each seed observation an ID, ordered by class, then row, then column."""
    counters = {}
    comps = []
    for o in sorted(observed, key=lambda o: (o.cls, round(o.y_mm / 3), o.x_mm)):
        prefix = ID_PREFIX.get(o.cls, "X")          # counted per prefix -> no C1/C1 clash
        counters[prefix] = counters.get(prefix, 0) + 1
        comps.append({"id": f"{prefix}{counters[prefix]}",
                      "class": o.cls, "x_mm": o.x_mm, "y_mm": o.y_mm,
                      "w_mm": o.w_mm, "h_mm": o.h_mm})
    return comps


def build_statistics(seed, runs, matcher, default_tol, k_sigma=4.0):
    """seed: list of component dicts. runs: list of lists of Observed.
    matcher(components, observed) -> list of (ref_index, obs_index) pairs.
    """
    samples = {i: [] for i in range(len(seed))}
    for obs in runs:
        for ri, oi in matcher(seed, obs):
            samples[ri].append((obs[oi].x_mm, obs[oi].y_mm, obs[oi].w_mm, obs[oi].h_mm))
    out, warnings = [], []
    for i, comp in enumerate(seed):
        s = np.array(samples[i]) if samples[i] else None
        c = {k: v for k, v in comp.items() if not k.startswith("_")}
        if s is None or len(s) == 0:
            warnings.append(f"{comp['id']} ({comp['class']}) was never detected on the "
                            "known-good boards - check the model or remove it")
            c.update(std_x_mm=None, std_y_mm=None, seen=0,
                     tol_mm=default_tol.get(comp["class"], 1.0))
        else:
            c["x_mm"], c["y_mm"] = float(s[:, 0].mean()), float(s[:, 1].mean())
            c["w_mm"], c["h_mm"] = float(s[:, 2].mean()), float(s[:, 3].mean())
            sx, sy = float(s[:, 0].std()), float(s[:, 1].std())
            radial = float(np.sqrt(sx ** 2 + sy ** 2))
            c.update(std_x_mm=round(sx, 4), std_y_mm=round(sy, 4), seen=int(len(s)))
            c["tol_mm"] = round(max(default_tol.get(comp["class"], 1.0), k_sigma * radial), 3)
            if len(s) < 0.9 * len(runs):
                warnings.append(f"{comp['id']} detected in only {len(s)}/{len(runs)} images")
        for k in ("x_mm", "y_mm", "w_mm", "h_mm"):
            c[k] = round(float(c[k]), 3)
        c.setdefault("tol_x_mm", None)
        c.setdefault("tol_y_mm", None)
        c.setdefault("required", True)
        out.append(c)
    return out, warnings


def set_side_components(data: dict, side: str, components, n_images, n_boards) -> dict:
    out = copy.deepcopy(data)
    sd = out["sides"].setdefault(side, {})
    sd["components"] = components
    sd["built_from"] = {"images": n_images, "boards": n_boards, "date": date.today().isoformat()}
    return out
