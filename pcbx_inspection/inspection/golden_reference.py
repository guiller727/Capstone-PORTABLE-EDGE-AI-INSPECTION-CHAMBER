"""
inspection/golden_reference.py - the list of EXPECTED components per side.

File format (references/golden_<side>.json):
{
  "schema_version": 1,
  "board": "PCB X", "side": "bottom",
  "canvas": {"px_per_mm": 10.0, "margin_mm": 2.5, "width_px": 1200, "height_px": 500},
  "built_from": {"images": 30, "boards": 10, "date": "2026-11-25"},
  "components": [
    {"id": "R3", "class": "resistor", "x_mm": 42.10, "y_mm": 18.60,
     "w_mm": 2.1, "h_mm": 1.3, "tol_mm": 0.50,
     "std_x_mm": 0.06, "std_y_mm": 0.05, "seen": 30}
  ]
}

How a golden reference is BUILT (tools/build_golden_reference.py):
 1. Seed: the hand-checked YOLO label of ONE known-good canvas, or the
    detections on the first known-good capture. Each box becomes one
    expected component and gets an ID (R1, R2, ... - rename them to match
    the silkscreen designators for your defense).
 2. For every known-good capture (10+ boards x 2-3 insertions), detect,
    and match detections to the seed with the SAME Hungarian matching used
    during inspection (same class only).
 3. Expected position = mean of the matched centres; spread = std dev.
 4. tol_mm = max(class default from config.DEFAULT_TOL_MM, 4 x radial std)
    -> tolerance is never tighter than the measured repeatability.
"""
import json
from datetime import date
from pathlib import Path

import numpy as np

ID_PREFIX = {"resistor": "R", "smd_capacitor": "C", "diode": "D", "ic8": "U",
             "electrolytic_cap": "CE", "inductor": "L", "transformer": "T",
             "varistor": "RV", "fuse": "F", "terminal_block": "TB", "connector": "J"}


def load_golden(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    ids = [c["id"] for c in data["components"]]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate component IDs in {path}")
    return data


def save_golden(path: Path, data: dict):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2))


def seed_components(observed):
    """Give each seed observation an ID, ordered by class, then row, then column."""
    counters = {}
    comps = []
    for o in sorted(observed, key=lambda o: (o.cls, round(o.y_mm / 3), o.x_mm)):
        counters[o.cls] = counters.get(o.cls, 0) + 1
        comps.append({"id": f"{ID_PREFIX.get(o.cls, 'X')}{counters[o.cls]}",
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
        c = dict(comp)
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
        out.append(c)
    return out, warnings


def make_golden_file(side, components, canvas, n_images, n_boards, board_name="PCB X"):
    return {"schema_version": 1, "board": board_name, "side": side,
            "canvas": {"px_per_mm": canvas.ppm, "margin_mm": canvas.m,
                       "width_px": canvas.w, "height_px": canvas.h},
            "built_from": {"images": n_images, "boards": n_boards,
                           "date": date.today().isoformat()},
            "components": components}
