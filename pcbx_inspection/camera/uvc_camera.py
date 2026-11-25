"""
camera/uvc_camera.py - USB webcam (EMEET C60E) through OpenCV + V4L2.

Why v4l2-ctl? OpenCV's CAP_PROP_AUTO_EXPOSURE / CAP_PROP_FOCUS behave
differently per driver. Calling v4l2-ctl (package v4l-utils) with the exact
control names reported by the camera is more predictable.

Stale frames: webcams keep a small queue of frames. After switching the LED
on we grab() and discard several frames, so the frame we keep was exposed
under the LED.
"""
import glob
import logging
import platform
import shutil
import subprocess
import time

import cv2
import numpy as np

from .base import BaseCamera, CameraError

log = logging.getLogger(__name__)


def find_device(match: str) -> str:
    """Return a stable /dev/v4l/by-id path whose name contains `match`.

    On the Raspberry Pi 5 many /dev/videoN nodes belong to the ISP, so the
    plain index of a USB webcam is not predictable. by-id paths are.
    """
    candidates = sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))
    for path in candidates:
        if match.lower() in path.lower():
            return path
    if candidates:
        log.warning("No by-id device contains %r, using %s", match, candidates[0])
        return candidates[0]
    raise CameraError(f"No USB camera found (looked for {match!r} in /dev/v4l/by-id)")


def apply_v4l2_controls(device: str, controls: dict) -> None:
    if not controls:
        return
    if shutil.which("v4l2-ctl") is None:
        log.warning("v4l2-ctl not installed (sudo apt install v4l-utils); "
                    "camera controls NOT locked")
        return
    # Apply auto modes first (so manual values are accepted afterwards).
    order = sorted(controls.items(),
                   key=lambda kv: 0 if ("auto" in kv[0] or "automatic" in kv[0]) else 1)
    for name, value in order:
        cmd = ["v4l2-ctl", "-d", device, f"--set-ctrl={name}={value}"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            log.warning("v4l2 control %s=%s rejected: %s", name, value,
                        res.stderr.strip())


def read_v4l2_controls(device: str) -> str:
    if shutil.which("v4l2-ctl") is None:
        return "v4l2-ctl not installed"
    res = subprocess.run(["v4l2-ctl", "-d", device, "--list-ctrls"],
                         capture_output=True, text=True)
    return res.stdout


class UvcCamera(BaseCamera):
    def open(self) -> None:
        dev = self.cfg.get("device", "auto")
        if platform.system() != "Linux":
            dev = int(self.cfg.get("index", 0)) if dev == "auto" else dev
            self.cap = cv2.VideoCapture(dev)
        else:
            if dev == "auto":
                dev = find_device(self.cfg.get("match", "EMEET"))
            self.cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        self.device = dev
        if not self.cap.isOpened():
            raise CameraError(f"Cannot open USB camera {dev}")

        fourcc = self.cfg.get("fourcc", "MJPG")
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.cfg["width"]))
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.cfg["height"]))
        self.cap.set(cv2.CAP_PROP_FPS, int(self.cfg.get("fps", 30)))
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # not honoured by every driver

        # Read a few frames so the stream is running, then lock the controls.
        for _ in range(10):
            self.cap.read()
        if isinstance(dev, str):
            apply_v4l2_controls(dev, self.cfg.get("v4l2_controls", {}))
        time.sleep(0.5)
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (w, h) != (int(self.cfg["width"]), int(self.cfg["height"])):
            log.warning("%s: requested %sx%s but camera gives %sx%s",
                        self.name, self.cfg["width"], self.cfg["height"], w, h)
        self.is_open = True
        log.info("UVC camera %s opened at %dx%d", dev, w, h)

    def capture(self) -> np.ndarray:
        if not self.is_open:
            raise CameraError(f"{self.name} camera is not open")
        for _ in range(int(self.cfg.get("flush_frames", 5))):
            self.cap.grab()                 # discard queued (old) frames
        ok, img = self.cap.read()
        if not ok or img is None or img.size == 0:
            raise CameraError(f"{self.name}: failed to read frame")
        return img

    def close(self) -> None:
        if getattr(self, "cap", None) is not None:
            self.cap.release()
        self.is_open = False
