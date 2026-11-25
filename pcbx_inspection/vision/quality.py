"""
vision/quality.py - reject blurry, too dark or over-exposed captures BEFORE
running YOLO, so a bad photo is recaptured instead of producing a wrong FAIL.
"""
import cv2
import numpy as np


def image_metrics(img: np.ndarray, centre_frac: float = 0.6) -> dict:
    """Sharpness and exposure measured on the central part of the image."""
    h, w = img.shape[:2]
    ch, cw = int(h * centre_frac), int(w * centre_frac)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    roi = img[y0:y0 + ch, x0:x0 + cw]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    # Downscale to a fixed width so the sharpness number does not depend on
    # the camera resolution.
    scale = 800.0 / gray.shape[1]
    if scale < 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return {
        "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        "mean": float(gray.mean()),
        "saturated_frac": float((gray >= 250).mean()),
    }


def check_quality(img: np.ndarray, cfg: dict) -> tuple:
    """Return (ok, metrics, reasons)."""
    m = image_metrics(img)
    reasons = []
    if m["sharpness"] < cfg["min_sharpness"]:
        reasons.append(f"blurry (sharpness {m['sharpness']:.0f} < {cfg['min_sharpness']})")
    if m["mean"] < cfg["min_mean"]:
        reasons.append(f"too dark (mean {m['mean']:.0f})")
    if m["mean"] > cfg["max_mean"]:
        reasons.append(f"too bright (mean {m['mean']:.0f})")
    if m["saturated_frac"] > cfg["max_saturated_frac"]:
        reasons.append(f"over-exposed ({m['saturated_frac'] * 100:.1f}% saturated)")
    return (not reasons), m, reasons
