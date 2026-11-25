"""
vision/board_alignment.py - turn a raw camera image into the standard
"canvas": the board straightened, cropped and scaled to PX_PER_MM, with the
board's top-left corner at (margin, margin). After this step a pixel position
converts directly to millimetres on the board.

Pipeline (one call to BoardAligner.align):
  1. Undistort (lens calibration).
  2. COARSE: find the 4 board corners (outline method) or use a fixed,
     pre-measured homography (fixed method) -> perspective warp to canvas.
     A rectangle's corners cannot tell 0 deg from 180 deg, so...
  3. ORIENTATION + SIDE: compare the canvas (and its 180-deg rotation) with
     reference templates of the correct side and of the flipped board.
       best = correct side, 0 deg   -> continue
       best = correct side, 180 deg -> rotate, continue  (Scenario B)
       best = flipped board         -> WRONG_SIDE        (Scenario C)
       all scores low               -> UNKNOWN_BOARD (not PCB X / empty tray)
     If no templates exist yet, the fiducial fit is tried at 0 and 180 deg
     and the better fit wins (works when fiducials are not 180-deg symmetric).
  4. FINE: locate the fiducials, fit a similarity transform, and re-warp the
     original image once with the combined transform (one interpolation).
     If fewer than 2 fiducials are found -> status "coarse" (the decision
     engine turns a would-be PASS into REVIEW).
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import fiducials as fid
from .preprocessing import to_gray_normalized

log = logging.getLogger(__name__)

OK, COARSE, NO_BOARD, WRONG_SIDE, UNKNOWN_BOARD = (
    "ok", "coarse", "no_board", "wrong_side", "unknown_board")


@dataclass
class AlignResult:
    status: str
    canvas: np.ndarray = None          # BGR canvas (before CLAHE)
    H: np.ndarray = None               # 3x3 undistorted-image -> canvas
    rotated_180: bool = False
    template_scores: dict = field(default_factory=dict)
    fiducials_found: int = 0
    fiducials_expected: int = 0
    fiducial_rms_mm: float = None
    corners: list = None
    message: str = ""

    @property
    def usable(self) -> bool:
        return self.status in (OK, COARSE)


class Canvas:
    """Geometry of the standard canvas."""

    def __init__(self, board_w_mm, board_h_mm, margin_mm, px_per_mm):
        self.bw, self.bh, self.m, self.ppm = board_w_mm, board_h_mm, margin_mm, px_per_mm
        self.w = int(round((board_w_mm + 2 * margin_mm) * px_per_mm))
        self.h = int(round((board_h_mm + 2 * margin_mm) * px_per_mm))

    def board_corners_px(self):
        m, p = self.m * self.ppm, self.ppm
        return np.float32([[m, m], [m + self.bw * p, m],
                           [m + self.bw * p, m + self.bh * p], [m, m + self.bh * p]])

    def rot180(self):
        """3x3 matrix rotating the canvas by 180 deg about its centre."""
        return np.array([[-1, 0, self.w - 1], [0, -1, self.h - 1], [0, 0, 1]], np.float64)


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points TL, TR, BR, BL with the LONG edge first (TL->TR)."""
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    c = pts.mean(0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]                         # clockwise in image coords
    # start from the point closest to top-left
    start = int(np.argmin(pts.sum(1)))
    pts = np.roll(pts, -start, axis=0)
    if np.linalg.norm(pts[1] - pts[0]) < np.linalg.norm(pts[3] - pts[0]):
        pts = np.roll(pts, -1, axis=0)                 # make TL->TR the long edge
        # keep "top-left-ish" start after the roll
    return pts


def find_board_quad(img: np.ndarray, cfg: dict, aspect: float):
    """Find the 4 corners of the board outline. Returns (corners or None, msg).

    Requires contrast between the board and the tray nest around it
    (e.g. green/blue solder mask on a light-grey matte nest).
    """
    h, w = img.shape[:2]
    scale = 1000.0 / max(h, w)
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    area_img = small.shape[0] * small.shape[1]
    best = None
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    for mask in (th, 255 - th):
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)   # fill holes/parts
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
        for c in contours:
            a = cv2.contourArea(c)
            frac = a / area_img
            if not (cfg["outline_min_area_frac"] <= frac <= cfg["outline_max_area_frac"]):
                continue
            (cx, cy), (rw, rh), _ = cv2.minAreaRect(c)
            if min(rw, rh) == 0:
                continue
            ratio = max(rw, rh) / min(rw, rh)
            if abs(ratio - aspect) / aspect > cfg["aspect_tolerance"]:
                continue
            rectness = a / (rw * rh)                   # 1.0 = perfect rectangle
            if rectness < 0.80:
                continue
            score = rectness * a
            if best is None or score > best[0]:
                best = (score, c)
    if best is None:
        return None, "board outline not found"
    c = best[1]
    approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    quad = approx.reshape(-1, 2) if len(approx) == 4 else cv2.boxPoints(cv2.minAreaRect(c))
    quad = order_corners(np.float32(quad) / scale)
    return quad, "ok"


def _template_prep(img: np.ndarray, size) -> np.ndarray:
    g = to_gray_normalized(img)
    g = cv2.resize(g, tuple(size), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(g, (5, 5), 0).astype(np.float32)


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised cross-correlation of two equal-size images (-1..1)."""
    return float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])


class BoardAligner:
    def __init__(self, side: str, canvas: Canvas, profile: dict, align_cfg: dict,
                 undistorter=None, references_dir: Path = None):
        self.side = side
        self.cv = canvas
        self.cfg = align_cfg
        self.und = undistorter
        sp = (profile or {}).get("sides", {}).get(side, {})
        self.fiducials_mm = sp.get("fiducials_mm", [])
        self.fixed_H = np.array(sp["fixed_homography"]) if sp.get("fixed_homography") else None
        self.templates = {}
        for key in ("template_ok", "template_flipped"):
            rel = sp.get(key)
            if rel and references_dir is not None:
                p = Path(references_dir) / rel
                t = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                if t is not None:
                    self.templates[key] = cv2.resize(
                        t, tuple(align_cfg["template_size"])).astype(np.float32)
                else:
                    log.warning("Template %s missing", p)

    # ------------------------------------------------------------------
    def coarse_homography(self, img):
        if self.cfg.get("coarse_method", "outline") == "fixed" and self.fixed_H is not None:
            return self.fixed_H.copy(), None, "fixed homography"
        aspect = self.cv.bw / self.cv.bh
        quad, msg = find_board_quad(img, self.cfg, aspect)
        if quad is None:
            if self.fixed_H is not None:
                return self.fixed_H.copy(), None, "outline not found - used fixed homography"
            return None, None, msg
        H = cv2.getPerspectiveTransform(quad, self.cv.board_corners_px())
        return H, quad.tolist(), "outline"

    def _warp(self, img, H):
        return cv2.warpPerspective(img, H, (self.cv.w, self.cv.h), flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))

    def _orientation(self, canvas):
        """Return (decision, scores). decision in {'0','180','flipped','unknown','none'}."""
        if "template_ok" not in self.templates:
            return "none", {}
        size = self.cfg["template_size"]
        c0 = _template_prep(canvas, size)
        c180 = cv2.rotate(c0, cv2.ROTATE_180)
        scores = {"ok_0": ncc(c0, self.templates["template_ok"]),
                  "ok_180": ncc(c180, self.templates["template_ok"])}
        if "template_flipped" in self.templates:
            scores["flip_0"] = ncc(c0, self.templates["template_flipped"])
            scores["flip_180"] = ncc(c180, self.templates["template_flipped"])
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        best_key, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else -1
        if best < self.cfg["min_template_score"]:
            return "unknown", scores
        if best_key.startswith("flip"):
            return "flipped", scores
        if best - second < self.cfg["min_score_margin"] and not ranked[1][0].startswith("ok"):
            return "unknown", scores
        return ("180" if best_key == "ok_180" else "0"), scores

    def _fine(self, canvas):
        """Fiducial refinement. Returns (A 3x3 or None, rms_mm, n_found)."""
        if not self.fiducials_mm:
            return None, None, 0
        gray = to_gray_normalized(canvas)
        matches = fid.locate_fiducials(gray, self.fiducials_mm, self.cv.ppm, self.cv.m,
                                       self.cfg["fiducial_search_mm"])
        A, rms_px, n = fid.fit_similarity(matches)
        if A is None:
            return None, None, n
        return np.vstack([A, [0, 0, 1]]), rms_px / self.cv.ppm, n

    # ------------------------------------------------------------------
    def align(self, raw_bgr: np.ndarray) -> AlignResult:
        img = self.und.apply(raw_bgr) if self.und is not None else raw_bgr
        H, corners, how = self.coarse_homography(img)
        if H is None:
            return AlignResult(NO_BOARD, message=f"Board not detected ({how}). "
                               "Check that the board is in the tray and the door is closed.")
        canvas = self._warp(img, H)

        decision, scores = self._orientation(canvas)
        rotated = False
        if decision == "flipped":
            return AlignResult(WRONG_SIDE, canvas=canvas, H=H, template_scores=scores,
                               corners=corners,
                               message="Wrong side facing the camera - flip the board over.")
        if decision == "unknown":
            return AlignResult(UNKNOWN_BOARD, canvas=canvas, H=H, template_scores=scores,
                               corners=corners,
                               message="Board not recognised as PCB X (or tray empty).")
        if decision == "180":
            H = self.cv.rot180() @ H
            canvas = self._warp(img, H)
            rotated = True

        A, rms_mm, n_found = self._fine(canvas)
        if decision == "none" and self.fiducials_mm:
            # no templates yet: let the fiducials decide between 0 and 180 deg
            H180 = self.cv.rot180() @ H
            A2, rms2, n2 = self._fine(self._warp(img, H180))
            if A2 is not None and (A is None or n2 > n_found or
                                   (n2 == n_found and rms2 < rms_mm)):
                H, A, rms_mm, n_found, rotated = H180, A2, rms2, n2, True

        n_exp = len(self.fiducials_mm)
        status, msg = OK, f"aligned ({how})"
        if A is not None and n_found >= self.cfg["min_fiducials"] and \
                rms_mm <= self.cfg["max_fiducial_rms_mm"]:
            H = A @ H
            canvas = self._warp(img, H)
            msg += f", {n_found}/{n_exp} fiducials, residual {rms_mm:.2f} mm"
        else:
            status = COARSE
            msg += (f", fine alignment unavailable ({n_found}/{n_exp} fiducials"
                    + (f", residual {rms_mm:.2f} mm" if rms_mm is not None else "") + ")")
        if decision == "none":
            msg += "; orientation not template-verified"
        return AlignResult(status, canvas=canvas, H=H, rotated_180=rotated,
                           template_scores=scores, fiducials_found=n_found,
                           fiducials_expected=n_exp, fiducial_rms_mm=rms_mm,
                           corners=corners, message=msg)


def load_profile(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        log.warning("Board profile %s not found - alignment uses outline only", path)
        return {}
    return json.loads(path.read_text())
