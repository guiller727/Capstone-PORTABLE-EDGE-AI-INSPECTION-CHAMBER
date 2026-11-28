"""
vision/board_alignment.py - turn a raw camera image into the standard
"canvas": the board straightened, cropped and scaled to PX_PER_MM, with the
board's top-left corner at (margin, margin). After this step a pixel position
converts directly to millimetres on the board.

Pipeline (one call to BoardAligner.align) - V2:
  1. Undistort with THIS CAMERA's lens calibration.
  2. COARSE: find the 4 board corners (outline) or use the camera's fixed
     homography -> perspective warp to the canvas. The long board edge is
     always made horizontal, so a board rotated 90/270 deg in the camera image
     becomes 0 or 180 deg here.
  3. IDENTIFICATION (vision/identification.py): which side is this (front
     markers searched first, then back markers) and is it rotated 180 deg?
       identified        -> rotate if needed, continue
       unknown           -> UNKNOWN_BOARD   (inspection result REVIEW)
       ambiguous         -> AMBIGUOUS       (inspection result REVIEW)
       expected_side set and different -> WRONG_SIDE (flip-mode/strict use)
  4. FINE: locate that side's fiducials (PCB X: the mounting holes), fit a
     similarity transform, re-warp once. < 2 fiducials -> status "coarse"
     (a would-be PASS becomes REVIEW).
Images are never mirrored: a camera looking at a board face always sees it
un-mirrored; a "mirrored-looking" image is simply the OTHER side, and that
is decided by identification, not by flipping pixels.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import fiducials as fid
from .identification import IDENTIFIED, AMBIGUOUS as ID_AMBIGUOUS, UNCONFIGURED as ID_UNCONF, MarkerSet
from .preprocessing import to_gray_normalized

log = logging.getLogger(__name__)

OK, COARSE, NO_BOARD, WRONG_SIDE, UNKNOWN_BOARD, AMBIGUOUS, UNCONFIGURED = (
    "ok", "coarse", "no_board", "wrong_side", "unknown_board", "ambiguous", "unconfigured")


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
    camera: str = None
    side: str = None                   # identified side ("top"/"bottom") or None
    identification: dict = None        # IdentResult.to_dict()
    rotation_deg: int = 0              # correction applied (0/90/180/270)

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
    """One aligner per CAMERA. It knows the fiducials and markers of BOTH sides,
    because either side may face the camera."""

    def __init__(self, camera: str, canvas: Canvas, profile: dict, align_cfg: dict,
                 undistorter=None, profile_dir: Path = None, fixed_H=None,
                 order=("top", "bottom")):
        self.camera = camera
        self.cv = canvas
        self.cfg = align_cfg
        self.und = undistorter
        self.order = tuple(order)
        self.sides = (profile or {}).get("sides", {})
        self.fixed_H = np.array(fixed_H) if fixed_H is not None else None
        self.markers = MarkerSet(profile, profile_dir, canvas, align_cfg)

    def fiducials_for(self, side):
        return (self.sides.get(side) or {}).get("fiducials_mm", [])

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

    def _fine(self, canvas, side):
        """Fiducial refinement. Returns (A 3x3 or None, rms_mm, n_found)."""
        fids = self.fiducials_for(side)
        if not fids:
            return None, None, 0
        gray = to_gray_normalized(canvas)
        matches = fid.locate_fiducials(gray, fids, self.cv.ppm, self.cv.m,
                                       self.cfg["fiducial_search_mm"])
        A, rms_px, n = fid.fit_similarity(matches)
        if A is None:
            return None, None, n
        return np.vstack([A, [0, 0, 1]]), rms_px / self.cv.ppm, n

    @staticmethod
    def _quad_angle(corners):
        """Angle (deg, image coords) of the board's long edge TL->TR, rounded to 90."""
        if not corners:
            return 0
        (x0, y0), (x1, y1) = corners[0], corners[1]
        ang = np.degrees(np.arctan2(y1 - y0, x1 - x0))
        return int(round(ang / 90.0)) * 90 % 360

    # ------------------------------------------------------------------
    def align(self, raw_bgr: np.ndarray, expected_side: str = None) -> AlignResult:
        img = self.und.apply(raw_bgr) if self.und is not None else raw_bgr
        H, corners, how = self.coarse_homography(img)
        if H is None:
            return AlignResult(NO_BOARD, camera=self.camera,
                               message=f"Board not detected ({how}). Check that the board is "
                                       "in the tray and the door is closed.")
        canvas = self._warp(img, H)
        base_rot = self._quad_angle(corners)

        ident = self.markers.identify(canvas, self.order)
        idd = ident.to_dict()
        common = dict(camera=self.camera, corners=corners, identification=idd,
                      template_scores=ident.scores)
        side, rotated = ident.side, ident.rotated_180

        if ident.status == ID_UNCONF:
            # Setup phase only (no markers yet): trust the caller's expected side and
            # let the fiducials decide 0/180 (works if they are not 180-deg symmetric).
            side = expected_side
            if side is None:
                return AlignResult(UNCONFIGURED, canvas=canvas, H=H, message=ident.message, **common)
            A0, r0, n0 = self._fine(canvas, side)
            H180 = self.cv.rot180() @ H
            A1, r1, n1 = self._fine(self._warp(img, H180), side)
            rotated = A1 is not None and (A0 is None or n1 > n0 or (n1 == n0 and r1 < r0))
        elif ident.status == ID_AMBIGUOUS:
            return AlignResult(AMBIGUOUS, canvas=canvas, H=H, side=side,
                               message=f"Orientation ambiguous: {ident.message}", **common)
        elif ident.status != IDENTIFIED:
            return AlignResult(UNKNOWN_BOARD, canvas=canvas, H=H,
                               message=f"Board side not identified: {ident.message}", **common)
        if expected_side is not None and side != expected_side:
            return AlignResult(WRONG_SIDE, canvas=canvas, H=H, side=side,
                               message=f"{side} side found but {expected_side} expected - "
                                       "flip the board over.", **common)
        if rotated:
            H = self.cv.rot180() @ H
            canvas = self._warp(img, H)
        rotation = (base_rot + (180 if rotated else 0)) % 360

        A, rms_mm, n_found = self._fine(canvas, side)
        n_exp = len(self.fiducials_for(side))
        status, msg = OK, f"{side} aligned ({how})"
        if A is not None and n_found >= self.cfg["min_fiducials"] and \
                rms_mm <= self.cfg["max_fiducial_rms_mm"]:
            H = A @ H
            canvas = self._warp(img, H)
            msg += f", {n_found}/{n_exp} fiducials, residual {rms_mm:.2f} mm"
        else:
            status = COARSE
            msg += (f", fine alignment unavailable ({n_found}/{n_exp} fiducials"
                    + (f", residual {rms_mm:.2f} mm" if rms_mm is not None else "") + ")")
        if ident.status == ID_UNCONF:
            msg += "; side NOT identified (no markers configured)"
        return AlignResult(status, canvas=canvas, H=H, rotated_180=rotated, side=side,
                           fiducials_found=n_found, fiducials_expected=n_exp,
                           fiducial_rms_mm=rms_mm, rotation_deg=rotation,
                           message=msg, **common)


def load_profile(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        log.warning("Board profile %s not found - identification/fiducials unavailable", path)
        return {}
    return json.loads(path.read_text())
