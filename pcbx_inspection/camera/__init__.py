"""camera package - create cameras from config.CAMERAS."""
from .base import BaseCamera, CameraError


def create_camera(name: str, cfg: dict, simulate: bool = False) -> BaseCamera:
    backend = "file" if simulate else cfg.get("backend", "uvc")
    if backend == "picamera2":
        from .picam_camera import PiCamera
        return PiCamera(name, cfg)
    if backend == "uvc":
        from .uvc_camera import UvcCamera
        return UvcCamera(name, cfg)
    if backend == "file":
        from .file_camera import FileCamera
        return FileCamera(name, cfg)
    raise ValueError(f"Unknown camera backend {backend!r}")


__all__ = ["BaseCamera", "CameraError", "create_camera"]
