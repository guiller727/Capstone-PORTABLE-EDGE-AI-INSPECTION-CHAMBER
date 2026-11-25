"""
inspection/decision_engine.py - rule-based PASS / FAIL / REVIEW decision.

Per expected component (after Hungarian matching), first rule that applies:
  R1  no detection (conf >= T_LOW) inside the gate radius .... MISSING    -> FAIL
  R2  matched detection conf < T_HIGH ........................ UNCERTAIN  -> REVIEW
  R3  conf >= T_HIGH but different class ..................... WRONG_TYPE -> FAIL
  R4  conf >= T_HIGH, same class, offset > tol_mm ............ MISPLACED  -> FAIL
  R5  conf >= T_HIGH, same class, offset <= tol_mm ........... OK

Per unmatched detection:
  R6  overlaps a matched box of the same class (IoU) ......... DUPLICATE  -> ignored
  R7  conf >= T_HIGH ......................................... EXTRA      -> REVIEW
                                              (FAIL if config.EXTRA_IS_FAIL)
  R8  conf <  T_HIGH ......................................... NOISE      -> logged only

Per side (system checks, evaluated BEFORE the rules above):
  S1  alignment only "coarse" (fiducials not found) -> PASS becomes REVIEW

Board verdict (both sides together):
  FAIL   if any component is MISSING / WRONG_TYPE / MISPLACED (or EXTRA when
         EXTRA_IS_FAIL)
  REVIEW else if anything is UNCERTAIN / EXTRA, or S1 applies
  PASS   otherwise

FAIL has priority over REVIEW: a board with a confirmed defect is rejected
even if some other part is uncertain.
"""
from dataclasses import dataclass, field, asdict

OK, MISSING, WRONG_TYPE, MISPLACED, UNCERTAIN, EXTRA, DUPLICATE, NOISE = (
    "OK", "MISSING", "WRONG_TYPE", "MISPLACED", "UNCERTAIN", "EXTRA", "DUPLICATE", "NOISE")
PASS, FAIL, REVIEW = "PASS", "FAIL", "REVIEW"

FAIL_STATUSES = {MISSING, WRONG_TYPE, MISPLACED}
REVIEW_STATUSES = {UNCERTAIN, EXTRA}


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
    offset_mm: float = None
    tol_mm: float = None
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


def evaluate_side(side, components, observed, matches, t_high, duplicate_iou=0.45,
                  extra_is_fail=False, alignment_status="ok"):
    """components: golden list; observed: list of Observed (conf >= T_LOW already);
    matches: list of (comp_idx, obs_idx, dist_mm) from hungarian_match."""
    by_comp = {ci: (oi, d) for ci, oi, d in matches}
    used = {oi for _, oi, _ in matches}
    results = []
    for ci, c in enumerate(components):
        base = dict(id=c["id"], expected_class=c["class"], tol_mm=c.get("tol_mm"),
                    ref_x_mm=c["x_mm"], ref_y_mm=c["y_mm"],
                    ref_w_mm=c.get("w_mm"), ref_h_mm=c.get("h_mm"))
        if ci not in by_comp:
            results.append(ComponentResult(status=MISSING, rule="R1",
                                           message=f"{c['id']} missing", **base))
            continue
        oi, dist = by_comp[ci]
        o = observed[oi]
        det = dict(detected_class=o.cls, conf=round(o.conf, 3), x_mm=round(o.x_mm, 3),
                   y_mm=round(o.y_mm, 3), offset_mm=round(dist, 3), box_px=o.box_px)
        if o.conf < t_high:
            results.append(ComponentResult(status=UNCERTAIN, rule="R2",
                           message=f"{c['id']} uncertain ({o.cls} {o.conf:.2f})", **base, **det))
        elif o.cls != c["class"]:
            results.append(ComponentResult(status=WRONG_TYPE, rule="R3",
                           message=f"{c['id']} wrong type: {o.cls} instead of {c['class']}",
                           **base, **det))
        elif dist > float(c.get("tol_mm", 1.0)):
            results.append(ComponentResult(status=MISPLACED, rule="R4",
                           message=f"{c['id']} shifted {dist:.2f} mm (tol {c['tol_mm']})",
                           **base, **det))
        else:
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
    return SideResult(side, verdict, results, extras, flags)


def combine(side_results):
    verdicts = [s.verdict for s in side_results]
    if FAIL in verdicts:
        return FAIL
    if REVIEW in verdicts:
        return REVIEW
    return PASS


def summary_lines(side_results, max_lines=12):
    """Short human-readable list of flagged parts for the GUI."""
    lines = []
    for s in side_results:
        for c in s.components + s.extras:
            if c.status not in (OK, DUPLICATE, NOISE):
                lines.append(f"[{s.side}] {c.message}")
        for f in s.flags:
            lines.append(f"[{s.side}] {f}")
    return lines[:max_lines] + ([f"... {len(lines) - max_lines} more"] if len(lines) > max_lines else [])
