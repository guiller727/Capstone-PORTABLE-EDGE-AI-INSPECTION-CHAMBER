"""
vision/component_detection.py - run the YOLO model on a canvas.

Works with every format Ultralytics can load: NCNN folders (recommended on
the Pi), .pt files (for testing on a laptop), ONNX, etc. The same code works
for YOLOv8n and YOLO26n models.
"""
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Detection:
    cls: str
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self):
        return (self.x1 + self.x2) / 2

    @property
    def cy(self):
        return (self.y1 + self.y2) / 2

    def to_dict(self):
        return asdict(self)


class Detector:
    def __init__(self, model_path: Path, imgsz, expected_classes=None,
                 iou: float = 0.5, max_det: int = 300):
        from ultralytics import YOLO
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}. Copy the exported "
                                    "*_ncnn_model folder into models/ (see models/README.md)")
        self.model = YOLO(str(model_path), task="detect")
        self.imgsz = list(imgsz) if isinstance(imgsz, (list, tuple)) else int(imgsz)
        self.iou, self.max_det = iou, max_det
        self.names = self.model.names            # {id: name}
        if expected_classes:
            got = [self.names[i] for i in sorted(self.names)]
            if got != list(expected_classes):
                raise ValueError(f"Model classes {got} differ from config {expected_classes}."
                                 " You probably loaded the wrong side's model.")
        self.last_ms = 0.0

    def warmup(self, shape):
        """First inference is slow (memory allocation). Do it at start-up."""
        dummy = np.zeros(shape, np.uint8)
        self.detect(dummy, conf=0.5)

    def detect(self, image_bgr: np.ndarray, conf: float):
        t0 = time.perf_counter()
        res = self.model.predict(image_bgr, imgsz=self.imgsz, conf=conf, iou=self.iou,
                                 max_det=self.max_det, verbose=False)[0]
        self.last_ms = (time.perf_counter() - t0) * 1000
        out = []
        if res.boxes is not None and len(res.boxes):
            xyxy = res.boxes.xyxy.cpu().numpy()
            cls = res.boxes.cls.cpu().numpy().astype(int)
            cf = res.boxes.conf.cpu().numpy()
            for (x1, y1, x2, y2), c, p in zip(xyxy, cls, cf):
                out.append(Detection(self.names[int(c)], float(p), float(x1), float(y1),
                                     float(x2), float(y2)))
        return out
