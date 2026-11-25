"""
vision/preprocessing.py - photometric preprocessing of the aligned canvas.

THIS IS THE ONLY PLACE where CLAHE/gamma are applied. The dataset tool
(tools/capture_dataset.py) and the inspection runner both call
`preprocess_canvas`, so training images and inspection images are processed
identically - a requirement stated in the project PDF.

Deliberately NOT done: denoising, sharpening, thresholding of the image
given to YOLO. They can erase or invent fine detail on small SMD parts.
"""
import cv2
import numpy as np


def apply_clahe_lab(img: np.ndarray, clip: float = 2.0, tiles=(8, 8)) -> np.ndarray:
    """CLAHE on the L (lightness) channel only - colours are preserved."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=clip, tileGridSize=tuple(tiles)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def apply_gamma(img: np.ndarray, gamma: float) -> np.ndarray:
    """gamma > 1 brightens dark areas, gamma < 1 darkens. 1.0 = unchanged."""
    if abs(gamma - 1.0) < 1e-6:
        return img
    table = ((np.arange(256) / 255.0) ** (1.0 / gamma) * 255).clip(0, 255).astype(np.uint8)
    return cv2.LUT(img, table)


def preprocess_canvas(canvas: np.ndarray, cfg: dict) -> np.ndarray:
    """Photometric steps applied to the aligned board canvas before YOLO."""
    out = canvas
    if cfg.get("gamma", 1.0) != 1.0:
        out = apply_gamma(out, float(cfg["gamma"]))
    if cfg.get("clahe", True):
        out = apply_clahe_lab(out, cfg.get("clahe_clip", 2.0), cfg.get("clahe_tiles", (8, 8)))
    return out


def to_gray_normalized(img: np.ndarray) -> np.ndarray:
    """Grey image with CLAHE - used for fiducials and template matching only."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
