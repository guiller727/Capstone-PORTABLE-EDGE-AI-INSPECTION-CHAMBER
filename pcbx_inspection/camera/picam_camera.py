"""
camera/picam_camera.py - CSI camera (Camera Module 3 / Arducam IMX519) via Picamera2.

Picamera2 is installed with apt (python3-picamera2). The virtual environment
must be created with --system-site-packages so it can be imported.

Arducam IMX519 note: according to Arducam's documentation the AUTOFOCUS
version needs Arducam's own libcamera build for focus control. The official
Raspberry Pi Camera Module 3 works with the stock software.
"""
import logging
import time

import numpy as np

from .base import BaseCamera, CameraError

log = logging.getLogger(__name__)


class PiCamera(BaseCamera):
    def open(self) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as exc:  # pragma: no cover - Pi only
            raise CameraError(
                "picamera2 not importable. Install with 'sudo apt install "
                "python3-picamera2' and create the venv with "
                "--system-site-packages") from exc

        num = int(self.cfg.get("camera_num", 0))
        try:
            self.cam = Picamera2(num)
        except Exception as exc:  # pragma: no cover
            raise CameraError(f"Cannot open CSI camera {num}: {exc}") from exc

        size = (int(self.cfg["width"]), int(self.cfg["height"]))
        # RGB888 in Picamera2 is stored B,G,R in memory -> OpenCV-ready BGR.
        config = self.cam.create_still_configuration(
            main={"size": size, "format": "RGB888"}, buffer_count=2)
        self.cam.configure(config)
        controls = dict(self.cfg.get("picamera2", {}))
        # Manual exposure: disable auto-exposure explicitly
        if "ExposureTime" in controls:
            controls.setdefault("AeEnable", False)
        # Drop controls this sensor does not support (e.g. AfMode/LensPosition
        # on a camera without a focus motor) instead of crashing.
        supported = set(self.cam.camera_controls.keys())
        for key in list(controls):
            if key not in supported:
                log.warning("%s: control %s not supported by this camera - ignored",
                            self.name, key)
                controls.pop(key)
        self.cam.set_controls(controls)
        self.cam.start()
        time.sleep(1.0)            # let the controls take effect
        self.cam.set_controls(controls)
        self.is_open = True
        log.info("PiCamera %s opened at %s with %s", num, size, controls)

    def capture(self) -> np.ndarray:
        if not self.is_open:
            raise CameraError(f"{self.name} camera is not open")
        # Throw away frames that may have started before the LEDs were on.
        for _ in range(int(self.cfg.get("flush_frames", 2))):
            self.cam.capture_array("main")
        img = self.cam.capture_array("main")
        if img is None or img.size == 0:
            raise CameraError(f"{self.name}: empty frame")
        if img.ndim == 3 and img.shape[2] == 4:      # XBGR8888 safety
            img = img[:, :, :3]
        return np.ascontiguousarray(img)

    def metadata(self) -> dict:
        return self.cam.capture_metadata() if self.is_open else {}

    def close(self) -> None:
        if self.is_open:
            try:
                self.cam.stop()
                self.cam.close()
            finally:
                self.is_open = False
