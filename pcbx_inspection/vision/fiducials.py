"""
vision/fiducials.py - find the round fiducial marks with classic OpenCV.

Why OpenCV and not YOLO? A fiducial is a simple, well-defined shape (a round
copper pad inside a clear ring). A threshold + contour + circularity test
finds it deterministically, with sub-pixel accuracy, without labelling, and
is easy to explain in the defense. YOLO boxes are only ~1-2 px accurate.

All positions here are in CANVAS pixels; conversion to mm uses PX_PER_MM.
"""
import cv2
import numpy as np


def _blobs(gray_roi: np.ndarray, d_min_px: float, d_max_px: float):
    """Yield (cx, cy, diameter, circularity) of round blobs, both polarities."""
    blur = cv2.GaussianBlur(gray_roi, (5, 5), 0)
    _, bright = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    for mask in (bright, 255 - bright):
        n, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)[-2:]
        contours = n
        for c in contours:
            area = cv2.contourArea(c)
            if area < 4:
                continue
            per = cv2.arcLength(c, True)
            if per <= 0:
                continue
            circ = 4 * np.pi * area / (per * per)
            d = 2 * np.sqrt(area / np.pi)
            if circ < 0.70 or not (d_min_px <= d <= d_max_px):
                continue
            m = cv2.moments(c)
            if m["m00"] == 0:
                continue
            yield m["m10"] / m["m00"], m["m01"] / m["m00"], d, circ


def find_candidates(gray: np.ndarray, px_per_mm: float, d_min_mm=0.6, d_max_mm=3.0):
    """Search the WHOLE canvas (used once when building the board profile)."""
    out = []
    for cx, cy, d, circ in _blobs(gray, d_min_mm * px_per_mm, d_max_mm * px_per_mm):
        out.append({"x_px": cx, "y_px": cy, "d_px": d, "circularity": circ})
    # remove duplicates (same blob found in both polarities / nested contours)
    out.sort(key=lambda b: -b["circularity"])
    kept = []
    for b in out:
        if all(np.hypot(b["x_px"] - k["x_px"], b["y_px"] - k["y_px"]) > b["d_px"] for k in kept):
            kept.append(b)
    return kept


def locate_fiducials(gray: np.ndarray, expected_mm, px_per_mm: float, margin_mm: float,
                     search_mm: float = 3.0):
    """Find each expected fiducial near its expected position.

    expected_mm: list of [x_mm, y_mm, diameter_mm] in board coordinates.
    Returns list of dicts: {"ref_px": (x,y), "found_px": (x,y) or None}.
    """
    results = []
    h, w = gray.shape[:2]
    r = int(round(search_mm * px_per_mm))
    for x_mm, y_mm, d_mm in expected_mm:
        ex = (x_mm + margin_mm) * px_per_mm
        ey = (y_mm + margin_mm) * px_per_mm
        x0, y0 = max(0, int(ex - r)), max(0, int(ey - r))
        x1, y1 = min(w, int(ex + r)), min(h, int(ey + r))
        found = None
        if x1 - x0 > 4 and y1 - y0 > 4:
            d_px = d_mm * px_per_mm
            best = None
            for cx, cy, d, circ in _blobs(gray[y0:y1, x0:x1], 0.6 * d_px, 1.5 * d_px):
                gx, gy = cx + x0, cy + y0
                dist = np.hypot(gx - ex, gy - ey)
                score = circ - 0.5 * abs(d - d_px) / d_px - 0.3 * dist / max(r, 1)
                if best is None or score > best[0]:
                    best = (score, gx, gy)
            if best is not None:
                found = (best[1], best[2])
        results.append({"ref_px": (ex, ey), "found_px": found})
    return results


def similarity_lsq(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares similarity (Umeyama, no reflection). Works for >= 2 points."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    cov = d.T @ s / len(src)
    U, S, Vt = np.linalg.svd(cov)
    D = np.eye(2)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        D[1, 1] = -1
    R = U @ D @ Vt
    var_s = (s ** 2).sum() / len(src)
    scale = np.trace(np.diag(S) @ D) / var_s if var_s > 0 else 1.0
    t = mu_d - scale * R @ mu_s
    return np.hstack([scale * R, t[:, None]])


def fit_similarity(matches):
    """Similarity transform (rotation+scale+shift) mapping found -> reference.

    Returns (A 2x3 or None, rms_px, n_used).
    """
    pairs = [(m["found_px"], m["ref_px"]) for m in matches if m["found_px"] is not None]
    if len(pairs) < 2:
        return None, float("inf"), len(pairs)
    src = np.array([p[0] for p in pairs], np.float64)
    dst = np.array([p[1] for p in pairs], np.float64)
    A = similarity_lsq(src, dst)
    proj = (A[:, :2] @ src.T).T + A[:, 2]
    rms = float(np.sqrt(np.mean(np.sum((proj - dst) ** 2, axis=1))))
    return A, rms, len(pairs)
