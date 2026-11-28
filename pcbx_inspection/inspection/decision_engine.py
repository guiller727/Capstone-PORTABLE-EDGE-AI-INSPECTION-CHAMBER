"""
inspection/decision_engine.py - rule-based PASS / FAIL / REVIEW decision.
(V1 rules R1-R8 + S1 kept; V2 adds per-axis tolerance, optional parts,
ambiguous matches and side-level REVIEW reasons.)

Per expected component (after Hungarian matching), first rule that applies:
  R1  no detection (conf >= t_low) inside the gate radius
        required part ......................................... MISSING      -> FAIL
        part marked "required": false ......................... MISSING_OPT  -> REVIEW
  R2  matched detection conf < t_high ......................... UNCERTAIN    -> REVIEW
  R3  conf >= t_high but different class ...................... WRONG_TYPE   -> FAIL
  R4  conf >= t_high, same class, offset outside tolerance
        (radial > tol_mm, or |dx| > tol_x_mm, or |dy| > tol_y_mm)  MISPLACED    -> FAIL
  R9  conf >= t_high, same class, inside tolerance, but the detection
        also lies inside the tolerance of ANOTHER same-class part  AMBIGUOUS    -> REVIEW
  R5  otherwise ............................................... OK

Per unmatched detection:
  R6  overlaps a matched box of the same class (IoU) .......... DUPLICATE    -> ignored
  R7  conf >= t_high .......................................... EXTRA        -> REVIEW
                                              (FAIL if config.EXTRA_IS_FAIL)
  R8  conf <  t_high .......................................... NOISE        -> logged only

Per side (system conditions):
  S1  fine alignment unavailable (fiducials not found) ........ PASS becomes REVIEW
  S2  side could not be inspected: capture unusable, side not identified,
      orientation ambiguous, model missing, conflicting identification
      ...................................................... side verdict REVIEW
      (reason recorded; never a guessed PASS or FAIL)

Low confidence is NEVER a FAIL by itself (R2 -> REVIEW).

Board verdict = combine(front, back), precedence FAIL > REVIEW > PASS:
  | front  | back   | overall |
  | PASS   | PASS   | PASS    |
  | PASS   | FAIL   | FAIL    |
  | FAIL   | PASS   | FAIL    |
  | PASS   | REVIEW | REVIEW  |
  | REVIEW | FAIL   | FAIL    |   a confirmed defect is not hidden by an
  | REVIEW | REVIEW | REVIEW  |   uncertainty elsewhere
"""
from dataclasses import dataclass, field, asdict

OK, MISSING, WRONG_TYPE, MISPLACED, UNCERTAIN, EXTRA, DUPLICATE, NOISE = (
    "OK", "MISSING", "WRONG_TYPE", "MISPLACED", "UNCERTAIN", "EXTRA", "DUPLICATE", "NOISE")
MISSING_OPT, AMBIGUOUS = "MISSING_OPTIONAL", "AMBIGUOUS"
PASS, FAIL, REVIEW = "PASS", "FAIL", "REVIEW"

FAIL_STATUSES = {MISSING, WRONG_TYPE, MISPLACED}
REVIEW_STATUSES = {UNCERTAIN, EXTRA, MISSING_OPT, AMBIGUOUS}

# side-level REVIEW reasons (S2)
R_CAPTURE = "capture unusable"
R_NOT_IDENTIFIED = "PCB side not identified"
R_AMBIGUOUS_ORIENT = "orientation ambiguous"
R_NOT_CAPTURED = "side not captured"
R_MODEL = "model not available"
R_CONFLICT = "conflicting identification"


@dataclass
class ComponentResult:
    id: str
    expected_class: str
    status: str
    rule: str
    detected_class: str = None
    conf: float = None
    x_mm: float = None
    y_mm: float = None
    dx_mm: float = None
    dy_mm: float = None
    offset_mm: float = None
    tol_mm: float = None
    tol_x_mm: float = None
    tol_y_mm: float = None
    ref_x_mm: float = None
    ref_y_mm: float = None
    ref_w_mm: float = None
    ref_h_mm: float = None
    box_px: tuple = None
    message: str = ""


@dataclass
class SideResult:
    side: str
    verdict: str
    components: list = field(default_factory=list)
    extras: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    camera: str = None
    inspected: bool = True

    def counts(self):
        out = {}
        for c in self.components + self.extras:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    def to_dict(self):
        d = asdict(self)
        d["counts"] = self.counts()
        return d


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _outside(c, dx, dy, dist):
    """Which tolerance is exceeded (None if inside)."""
    if dist > float(c.get("tol_mm") or 1.0):
        return f"radial {dist:.2f} > {c.get('tol_mm')} mm"
    if c.get("tol_x_mm") is not None and abs(dx) > float(c["tol_x_mm"]):
        return f"|dx| {abs(dx):.2f} > {c['tol_x_mm']} mm"
    if c.get("tol_y_mm") is not None and abs(dy) > float(c["tol_y_mm"]):
        return f"|dy| {abs(dy):.2f} > {c['tol_y_mm']} mm"
    return None


def evaluate_side(side, components, observed, matches, t_high, duplicate_iou=0.45,
                  extra_is_fail=False, alignment_status="ok", camera=None):
    """components: RESOLVED golden list (golden_reference.resolved_components);
    observed: list of Observed (conf >= t_low already);
    matches: list of (comp_idx, obs_idx, dist_mm) from hungarian_match."""
    by_comp = {ci: (oi, d) for ci, oi, d in matches}
    used = {oi for _, oi, _ in matches}
    results = []
    for ci, c in enumerate(components):
        base = dict(id=c["id"], expected_class=c["class"], tol_mm=c.get("tol_mm"),
                    tol_x_mm=c.get("tol_x_mm"), tol_y_mm=c.get("tol_y_mm"),
                    ref_x_mm=c["x_mm"], ref_y_mm=c["y_mm"],
                    ref_w_mm=c.get("w_mm"), ref_h_mm=c.get("h_mm"))
        if ci not in by_comp:
            if c.get("required", True):
                results.append(ComponentResult(status=MISSING, rule="R1",
                                               message=f"{c['id']} missing", **base))
            else:
                results.append(ComponentResult(status=MISSING_OPT, rule="R1",
                                               message=f"{c['id']} (optional) not found", **base))
            continue
        oi, dist = by_comp[ci]
        o = observed[oi]
        dx, dy = o.x_mm - c["x_mm"], o.y_mm - c["y_mm"]
        det = dict(detected_class=o.cls, conf=round(o.conf, 3), x_mm=round(o.x_mm, 3),
                   y_mm=round(o.y_mm, 3), dx_mm=round(dx, 3), dy_mm=round(dy, 3),
                   offset_mm=round(dist, 3), box_px=o.box_px)
        if o.conf < t_high:
            results.append(ComponentResult(status=UNCERTAIN, rule="R2",
                           message=f"{c['id']} uncertain ({o.cls} {o.conf:.2f})", **base, **det))
            continue
        if o.cls != c["class"]:
            results.append(ComponentResult(status=WRONG_TYPE, rule="R3",
                           message=f"{c['id']} wrong type: {o.cls} instead of {c['class']}",
                           **base, **det))
            continue
        why = _outside(c, dx, dy, dist)
        if why:
            results.append(ComponentResult(status=MISPLACED, rule="R4",
                           message=f"{c['id']} shifted dx {dx:+.2f} dy {dy:+.2f} mm ({why})",
                           **base, **det))
            continue
        others = [k for k, oc in enumerate(components) if k != ci and oc["class"] == c["class"]
                  and _outside(oc, o.x_mm - oc["x_mm"], o.y_mm - oc["y_mm"],
                               ((o.x_mm - oc["x_mm"]) ** 2 + (o.y_mm - oc["y_mm"]) ** 2) ** 0.5)
                  is None]
        if others:
            names = ", ".join(components[k]["id"] for k in others)
            results.append(ComponentResult(status=AMBIGUOUS, rule="R9",
                           message=f"{c['id']} match ambiguous (also within tolerance of {names})",
                           **base, **det))
            continue
        results.append(ComponentResult(status=OK, rule="R5", message=f"{c['id']} OK",
                                       **base, **det))

    matched_boxes = [(observed[oi].cls, observed[oi].box_px) for _, oi, _ in matches]
    extras = []
    for oi, o in enumerate(observed):
        if oi in used:
            continue
        common = dict(id=f"extra{len(extras) + 1}", expected_class=None,
                      detected_class=o.cls, conf=round(o.conf, 3),
                      x_mm=round(o.x_mm, 3), y_mm=round(o.y_mm, 3), box_px=o.box_px)
        if any(cls == o.cls and _iou(box, o.box_px) >= duplicate_iou
               for cls, box in matched_boxes):
            extras.append(ComponentResult(status=DUPLICATE, rule="R6",
                          message="duplicate box ignored", **common))
        elif o.conf >= t_high:
            extras.append(ComponentResult(status=EXTRA, rule="R7",
                          message=f"unexpected {o.cls} at ({o.x_mm:.1f}, {o.y_mm:.1f}) mm",
                          **common))
        else:
            extras.append(ComponentResult(status=NOISE, rule="R8",
                          message="low-confidence extra ignored", **common))

    statuses = {r.status for r in results + extras}
    flags = []
    fail_set = FAIL_STATUSES | ({EXTRA} if extra_is_fail else set())
    if statuses & fail_set:
        verdict = FAIL
    elif statuses & REVIEW_STATUSES:
        verdict = REVIEW
    else:
        verdict = PASS
    if alignment_status == "coarse":
        flags.append("S1: fine alignment unavailable (fiducials not found)")
        if verdict == PASS:
            verdict = REVIEW
    return SideResult(side, verdict, results, extras, flags, camera=camera)


def review_side(side, reason, detail="", camera=None):
    """S2: a side that could not be inspected -> REVIEW with the reason."""
    msg = f"S2: {reason}" + (f" - {detail}" if detail else "")
    return SideResult(side, REVIEW, flags=[msg], camera=camera, inspected=False)


def combine(side_results):
    verdicts = [s.verdict for s in side_results]
    if FAIL in verdicts:
        return FAIL
    if REVIEW in verdicts or not verdicts:
        return REVIEW
    return PASS


def summary_lines(side_results, max_lines=14, labels=None):
    """Short human-readable list of flagged parts for the GUI."""
    lines = []
    for s in side_results:
        tag = (labels or {}).get(s.side, s.side)
        for f in s.flags:
            lines.append(f"[{tag}] {f}")
        for c in s.components + s.extras:
            if c.status not in (OK, DUPLICATE, NOISE):
                lines.append(f"[{tag}] {c.message}")
    return lines[:max_lines] + ([f"... {len(lines) - max_lines} more"] if len(lines) > max_lines else [])
