"""
camera/file_camera.py - "camera" that returns images from a folder.

Used for simulation (--simulate) so the whole program, including the GUI,
can be developed and demonstrated on a Windows laptop without hardware.
Images are returned in sorted order and the sequence loops.
"""
from pathlib import Path

import cv2
import numpy as np

from .base import BaseCamera, CameraError

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp"}


class FileCamera(BaseCamera):
    def open(self) -> None:
        from config import PROJECT_DIR
        folder = Path(self.cfg.get("simulate_folder", f"sim_images/{self.name}"))
        if not folder.is_absolute():
            folder = PROJECT_DIR / folder
        self.files = sorted(p for p in folder.glob("*") if p.suffix.lower() in IMG_EXT)
        if not self.files:
            raise CameraError(f"No images in {folder} for simulated {self.name} camera")
        self.index = 0
        self.is_open = True

    def capture(self) -> np.ndarray:
        path = self.files[self.index % len(self.files)]
        self.index += 1
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise CameraError(f"Cannot read {path}")
        self.last_path = path
        return img

    def close(self) -> None:
        self.is_open = False
