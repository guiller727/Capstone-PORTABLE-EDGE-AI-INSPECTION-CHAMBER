"""
vision/calibration.py - camera calibration (lens distortion) load/save/apply.

Calibration is done ONCE per camera with tools/calibrate_camera.py using a
printed checkerboard. The result (camera matrix K and distortion coefficients)
is stored as JSON in references/calibration/<side>_camera.json.

Speed: cv2.undistort() recomputes a lookup table every call. We compute the
table once (initUndistortRectifyMap) and reuse it with cv2.remap().
"""
import json
import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


def calibrate_from_images(images, pattern=(9, 6), square_mm=8.0):
    """Compute calibration from a list of BGR images of a checkerboard.

    pattern = number of INNER corners (columns, rows).
    Returns (result_dict, used_count).
    """
    objp = np.zeros((pattern[0] * pattern[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square_mm
    obj_pts, img_pts, size = [], [], None
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3)
    for img in images:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        size = gray.shape[::-1]
        ok, corners = cv2.findChessboardCorners(
            gray, pattern, cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if not ok:
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), crit)
        obj_pts.append(objp)
        img_pts.append(corners)
    if len(obj_pts) < 8:
        raise RuntimeError(f"Only {len(obj_pts)} usable checkerboard images; need >= 8 "
                           "(15-20 recommended, tilted and placed over the whole view)")
    rms, K, dist, _, _ = cv2.calibrateCamera(obj_pts, img_pts, size, None, None)
    return {"image_size": list(size), "K": K.tolist(), "dist": dist.ravel().tolist(),
            "rms_px": float(rms), "pattern": list(pattern),
            "square_mm": square_mm, "n_images": len(obj_pts)}, len(obj_pts)


def save_calibration(path: Path, calib: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calib, indent=2))


class Undistorter:
    """Applies lens-distortion correction; does nothing if no calibration."""

    def __init__(self, calib_path: Path):
        self.calib = None
        self._maps = {}
        if calib_path and Path(calib_path).exists():
            self.calib = json.loads(Path(calib_path).read_text())
            self.K = np.array(self.calib["K"], dtype=np.float64)
            self.dist = np.array(self.calib["dist"], dtype=np.float64)
            log.info("Loaded calibration %s (RMS %.3f px)", calib_path,
                     self.calib.get("rms_px", -1))
        else:
            log.warning("No calibration file %s - images are NOT undistorted", calib_path)

    @property
    def enabled(self) -> bool:
        return self.calib is not None

    def _maps_for(self, w, h):
        key = (w, h)
        if key not in self._maps:
            cw, ch = self.calib["image_size"]
            K = self.K.copy()
            if (cw, ch) != (w, h):            # calibration at another resolution
                K[0, :] *= w / cw
                K[1, :] *= h / ch
            m1, m2 = cv2.initUndistortRectifyMap(K, self.dist, None, K, (w, h),
                                                 cv2.CV_16SC2)
            self._maps[key] = (m1, m2)
        return self._maps[key]

    def apply(self, img: np.ndarray) -> np.ndarray:
        if not self.enabled:
            return img
        h, w = img.shape[:2]
        m1, m2 = self._maps_for(w, h)
        return cv2.remap(img, m1, m2, cv2.INTER_LINEAR)
