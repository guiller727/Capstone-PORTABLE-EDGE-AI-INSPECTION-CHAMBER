"""
vision/identification.py - NEW in V2: which PCB side is in this image, and is
it rotated by 180 deg?  (Answers "WHAT is it?" - NOT "exactly WHERE is it?")

Identification vs alignment (kept separate on purpose):
  * identification  -> side (top=FRONT/bottom=BACK) + coarse orientation (0/180)
                       from the board's own markings ("markers")
  * alignment       -> sub-millimetre position from the mounting holes
                       (vision/fiducials.py) - done AFTER identification.
A matched logo proves which side it is; it does not prove the board is
accurately registered. That is why a separate fine-alignment step follows.

Input is the COARSE canvas: the board outline has already been found and
warped so that its long edge is horizontal (this removes 90/270 deg
rotations). Only 0 deg vs 180 deg remains to be decided here.

Marker types (defined per side in models/<profile>/board_profile.json):
  "template"  normalised cross-correlation (cv2.matchTemplate) of a small
              reference crop - e.g. the SHARP logo, the QPWBP0335PFZZ part
              number, the white "T1" block. Fast (< 5 ms each), no training,
              robust to small lighting changes, easy to explain.
  "barcode"   cv2.barcode detector (OpenCV >= 4.8). Detects a 1-D barcode
              in the search window; decoding (EAN-8/13, UPC) is only recorded
              as extra information - presence + position is what identifies.
OCR is deliberately NOT used: silkscreen text is small, partly covered by
tape on some units, and OCR is slow and error-prone on a Pi CPU.

Search order: FRONT (top) markers first, then BACK (bottom) markers
(config.SIDE_SEARCH_ORDER). If no side is confidently found -> "unknown",
and the inspection result for that image becomes REVIEW (no guessing).
"""
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

import cv2
import numpy as np

from .preprocessing import to_gray_normalized

log = logging.getLogger(__name__)

IDENTIFIED, UNKNOWN, AMBIGUOUS, UNCONFIGURED = "identified", "unknown", "ambiguous", "unconfigured"


@dataclass
class IdentResult:
    status: str
    side: str = None
    rotated_180: bool = False
    method: str = "none"
    confidence: float = 0.0
    markers: list = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    message: str = ""

    def to_dict(self):
        return asdict(self)


def _pyzbar_decode(img):
    """Optional decoder for barcode types OpenCV cannot read (pip install pyzbar +
    sudo apt install libzbar0). Returns a list of strings or None."""
    try:
        from pyzbar import pyzbar
    except Exception:
        return None
    try:
        return [d.data.decode("ascii", "replace") for d in pyzbar.decode(img)] or None
    except Exception:
        return None


def _barcode_detector():
    try:
        return cv2.barcode.BarcodeDetector()
    except AttributeError:
        return None


class MarkerSet:
    """Loads and matches the identification markers of every side."""

    def __init__(self, board_profile: dict, profile_dir: Path, canvas, align_cfg: dict):
        self.cv = canvas
        self.cfg = align_cfg
        self.sides = {}
        self.whole = {}
        self._bar = None
        sides = (board_profile or {}).get("sides", {})
        for side, sp in sides.items():
            markers = []
            for m in sp.get("markers", []):
                m = dict(m)
                m.setdefault("type", "template")
                m.setdefault("min_score", align_cfg["marker_min_score"])
                m.setdefault("search_mm", align_cfg["marker_search_mm"])
                if m["type"] == "template":
                    img = self._load(profile_dir, m.get("template"))
                    if img is None:
                        log.warning("marker %s/%s: template missing - skipped", side, m.get("name"))
                        continue
                    m["_img"] = img
                markers.append(m)
            self.sides[side] = {"markers": markers, "min_markers": int(sp.get("min_markers", 1))}
            tpl = sp.get("template") or sp.get("template_ok")       # V1 key accepted
            img = self._load(profile_dir, tpl)
            if img is not None:
                self.whole[side] = cv2.resize(img, tuple(align_cfg["template_size"])).astype(np.float32)

    @staticmethod
    def _load(profile_dir, rel):
        if not rel or profile_dir is None:
            return None
        p = Path(profile_dir) / rel
        return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None

    @property
    def configured(self) -> bool:
        return any(s["markers"] for s in self.sides.values()) or bool(self.whole)

    # ------------------------------------------------------------------
    def _window(self, gray, m):
        ppm, mg = self.cv.ppm, self.cv.m
        cx, cy = (m["x_mm"] + mg) * ppm, (m["y_mm"] + mg) * ppm
        hw, hh = m["w_mm"] * ppm / 2, m["h_mm"] * ppm / 2
        r = m["search_mm"] * ppm
        h, w = gray.shape[:2]
        x0, y0 = int(max(0, cx - hw - r)), int(max(0, cy - hh - r))
        x1, y1 = int(min(w, cx + hw + r)), int(min(h, cy + hh + r))
        return x0, y0, x1, y1, cx, cy

    def match(self, gray, bgr, m):
        x0, y0, x1, y1, cx, cy = self._window(gray, m)
        hit = {"name": m.get("name"), "type": m["type"], "score": -1.0, "found": False,
               "dx_mm": None, "dy_mm": None, "decoded": None}
        if m["type"] == "template":
            t = m["_img"]
            win = gray[y0:y1, x0:x1]
            if win.shape[0] < t.shape[0] or win.shape[1] < t.shape[1]:
                return hit
            res = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            fx, fy = x0 + loc[0] + t.shape[1] / 2, y0 + loc[1] + t.shape[0] / 2
            hit.update(score=round(float(score), 3), found=bool(score >= m["min_score"]),
                       dx_mm=round((fx - cx) / self.cv.ppm, 2), dy_mm=round((fy - cy) / self.cv.ppm, 2))
        elif m["type"] == "barcode":
            if self._bar is None:
                self._bar = _barcode_detector()
            if self._bar is None:
                hit["decoded"] = "barcode detector unavailable (OpenCV < 4.8)"
                return hit
            win = bgr[y0:y1, x0:x1]
            try:
                ok, decoded, _, points = self._bar.detectAndDecodeWithType(win)
            except Exception:               # older API
                ok, points = self._bar.detect(win)
                decoded = None
            if ok and points is not None and len(points):
                pts = np.array(points).reshape(-1, 2)
                fx, fy = x0 + pts[:, 0].mean(), y0 + pts[:, 1].mean()
                if not any(decoded or []):
                    decoded = _pyzbar_decode(win)       # e.g. Code 128 (OpenCV: EAN/UPC only)
                hit.update(score=1.0, found=True,
                           dx_mm=round((fx - cx) / self.cv.ppm, 2),
                           dy_mm=round((fy - cy) / self.cv.ppm, 2),
                           decoded=[d for d in (decoded or []) if d] or None)
            else:
                hit["score"] = 0.0
        return hit

    # ------------------------------------------------------------------
    def identify(self, canvas_bgr, order=("top", "bottom")) -> IdentResult:
        if not self.configured:
            return IdentResult(UNCONFIGURED, message="no identification markers or templates "
                               "in board_profile.json - run tools/build_board_profile.py")
        gray0 = to_gray_normalized(canvas_bgr)
        views = {0: (gray0, canvas_bgr),
                 180: (cv2.rotate(gray0, cv2.ROTATE_180), cv2.rotate(canvas_bgr, cv2.ROTATE_180))}
        margin = self.cfg["orientation_margin"]
        all_hits = {}
        for side in order:
            sp = self.sides.get(side)
            if not sp or not sp["markers"]:
                continue
            per_rot = {}
            for rot, (g, b) in views.items():
                hits = [self.match(g, b, m) for m in sp["markers"]]
                per_rot[rot] = hits
            all_hits[side] = per_rot
            found = {rot: sum(h["found"] for h in hits) for rot, hits in per_rot.items()}
            mean = {rot: float(np.mean([max(h["score"], 0) for h in hits]))
                    for rot, hits in per_rot.items()}
            ok = [rot for rot in (0, 180) if found[rot] >= sp["min_markers"]]
            if not ok:
                continue                      # try the next side (front first, then back)
            if len(ok) == 2:
                if found[0] == found[180] and abs(mean[0] - mean[180]) < margin:
                    return IdentResult(AMBIGUOUS, side=side, method="markers",
                                       markers=per_rot[0] + per_rot[180],
                                       scores={"mean_0": mean[0], "mean_180": mean[180]},
                                       message=f"{side} markers match at 0 and 180 deg - "
                                               "orientation ambiguous")
                rot = max(ok, key=lambda r: (found[r], mean[r]))
            else:
                rot = ok[0]
            hits = per_rot[rot]
            names = ", ".join(f"{h['name']} {h['score']:.2f}" for h in hits if h["found"])
            return IdentResult(IDENTIFIED, side=side, rotated_180=(rot == 180), method="markers",
                               confidence=round(mean[rot], 3), markers=hits,
                               scores={"mean_0": round(mean[0], 3), "mean_180": round(mean[180], 3)},
                               message=f"{side} identified by {names}")
        # ------ fallback: whole-board templates (V1 method) --------------
        if self.whole:
            size = tuple(self.cfg["template_size"])
            g = cv2.GaussianBlur(cv2.resize(gray0, size, interpolation=cv2.INTER_AREA),
                                 (5, 5), 0).astype(np.float32)
            g180 = cv2.rotate(g, cv2.ROTATE_180)
            scores = {}
            for side, t in self.whole.items():
                scores[f"{side}_0"] = float(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)[0, 0])
                scores[f"{side}_180"] = float(cv2.matchTemplate(g180, t, cv2.TM_CCOEFF_NORMED)[0, 0])
            ranked = sorted(scores.items(), key=lambda kv: -kv[1])
            (k1, s1), (k2, s2) = ranked[0], ranked[1] if len(ranked) > 1 else ("", -1)
            side, rot = k1.rsplit("_", 1)
            if s1 >= self.cfg["min_template_score"]:
                if s1 - s2 < self.cfg["min_score_margin"]:
                    return IdentResult(AMBIGUOUS, side=side, method="whole_board", scores=scores,
                                       markers=_flat(all_hits),
                                       message=f"whole-board match ambiguous ({k1} {s1:.2f} vs {k2} {s2:.2f})")
                return IdentResult(IDENTIFIED, side=side, rotated_180=(rot == "180"),
                                   method="whole_board", confidence=round(s1, 3), scores=scores,
                                   markers=_flat(all_hits),
                                   message=f"{side} identified by whole-board template {s1:.2f}")
            return IdentResult(UNKNOWN, method="whole_board", scores=scores, markers=_flat(all_hits),
                               message="board not recognised (no markers found, "
                                       f"best whole-board score {s1:.2f})")
        return IdentResult(UNKNOWN, method="markers", markers=_flat(all_hits),
                           message="no identification marker found on either side")


def _flat(all_hits):
    out = []
    for side, per_rot in all_hits.items():
        for rot, hits in per_rot.items():
            out += [dict(h, side=side, rot=rot) for h in hits]
    return out


def crop_template(canvas_bgr, x_mm, y_mm, w_mm, h_mm, ppm, margin_mm):
    """Cut a marker template (grey, CLAHE) from a canvas - used by the setup tool."""
    g = to_gray_normalized(canvas_bgr)
    cx, cy = (x_mm + margin_mm) * ppm, (y_mm + margin_mm) * ppm
    x0, y0 = int(round(cx - w_mm * ppm / 2)), int(round(cy - h_mm * ppm / 2))
    x1, y1 = int(round(cx + w_mm * ppm / 2)), int(round(cy + h_mm * ppm / 2))
    if x0 < 0 or y0 < 0 or x1 > g.shape[1] or y1 > g.shape[0]:
        raise ValueError("marker rectangle lies outside the canvas")
    crop = g[y0:y1, x0:x1]
    if crop.std() < 8:
        log.warning("marker crop has very little texture (std %.1f) - choose a more "
                    "distinctive area", crop.std())
    return crop
