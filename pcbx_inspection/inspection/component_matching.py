"""
inspection/component_matching.py - pair each EXPECTED component (golden
reference) with at most one DETECTED component.

Why Hungarian assignment instead of "nearest neighbour"?
  Nearest-neighbour looks at each reference separately, so two resistors
  sitting close together can both grab the SAME detection (one detection
  counted twice, the other part wrongly reported OK). The Hungarian
  algorithm (scipy.optimize.linear_sum_assignment) solves all pairs at once
  and guarantees ONE-TO-ONE pairing with the lowest total cost.

Cost of pairing reference r with detection d:
    cost = distance_mm / tol_r  +  class_penalty * (class differs)
Pairs farther than the gate radius are forbidden:
    gate_r = max(gate_factor * tol_r, gate_min_mm)
The class penalty lets a correct-class detection win over a wrong-class one
at similar distance, but still allows a wrong-class detection to be paired
(so we can report WRONG TYPE instead of MISSING + EXTRA).
"""
import numpy as np
from scipy.optimize import linear_sum_assignment

FORBIDDEN = 1e6


def cost_matrix(components, observed, gate_factor=3.0, gate_min_mm=1.5,
                class_penalty=2.0, same_class_only=False):
    n, m = len(components), len(observed)
    C = np.full((n, m), FORBIDDEN, dtype=np.float64)
    D = np.zeros((n, m))
    for i, c in enumerate(components):
        tol = float(c.get("tol_mm", 1.0))
        gate = max(gate_factor * tol, gate_min_mm)
        for j, o in enumerate(observed):
            d = float(np.hypot(o.x_mm - c["x_mm"], o.y_mm - c["y_mm"]))
            D[i, j] = d
            if d > gate:
                continue
            wrong = o.cls != c["class"]
            if wrong and same_class_only:
                continue
            C[i, j] = d / tol + (class_penalty if wrong else 0.0)
    return C, D


def hungarian_match(components, observed, **kw):
    """Return list of (component_index, observed_index, distance_mm)."""
    if not components or not observed:
        return []
    C, D = cost_matrix(components, observed, **kw)
    rows, cols = linear_sum_assignment(C)
    return [(int(r), int(c), float(D[r, c])) for r, c in zip(rows, cols)
            if C[r, c] < FORBIDDEN]


def nearest_neighbour_match(components, observed, **kw):
    """Shown for comparison in the defense - NOT used. Can assign one
    detection to several references."""
    if not components or not observed:
        return []
    C, D = cost_matrix(components, observed, **kw)
    out = []
    for i in range(len(components)):
        j = int(np.argmin(C[i]))
        if C[i, j] < FORBIDDEN:
            out.append((i, j, float(D[i, j])))
    return out


def same_class_matcher(match_cfg):
    """Matcher used when building golden references (pairs only same class)."""
    def _m(components, observed):
        pairs = hungarian_match(components, observed, gate_factor=match_cfg["gate_factor"],
                                gate_min_mm=max(match_cfg["gate_min_mm"], 2.0),
                                class_penalty=0.0, same_class_only=True)
        return [(r, c) for r, c, _ in pairs]
    return _m
