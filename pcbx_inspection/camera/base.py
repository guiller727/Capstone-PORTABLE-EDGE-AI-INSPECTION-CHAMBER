"""camera/base.py - common interface every camera backend implements."""
from abc import ABC, abstractmethod

import numpy as np


class CameraError(RuntimeError):
    """Raised when a camera cannot be opened or returns no image."""


class BaseCamera(ABC):
    """All cameras return BGR uint8 images (OpenCV convention)."""

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.cfg = cfg
        self.is_open = False

    @abstractmethod
    def open(self) -> None:
        """Open the device once, apply locked exposure/focus/white balance."""

    @abstractmethod
    def capture(self) -> np.ndarray:
        """Return a FRESH frame (taken after the LEDs were switched on)."""

    @abstractmethod
    def close(self) -> None:
        """Release the device."""

    def describe(self) -> str:
        return f"{self.name} ({self.__class__.__name__})"

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
