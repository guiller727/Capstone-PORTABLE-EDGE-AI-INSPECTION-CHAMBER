"""
vision/coordinate_extraction.py - convert YOLO boxes (canvas pixels) into
board coordinates in millimetres.

Canvas convention (see config.py):
    x_mm = x_px / PX_PER_MM - MARGIN_MM
    y_mm = y_px / PX_PER_MM - MARGIN_MM
(0, 0) is the board's top-left corner as seen by that side's camera.
Bottom-side coordinates are therefore MIRRORED compared with a CAD "top view"
of the bottom layer - this does not matter because the golden reference is
built with the same camera.
"""
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Observed:
    cls: str
    conf: float
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float
    box_px: tuple

    def to_dict(self):
        return asdict(self)


def px_to_mm(x_px, y_px, ppm, margin_mm):
    return x_px / ppm - margin_mm, y_px / ppm - margin_mm


def mm_to_px(x_mm, y_mm, ppm, margin_mm):
    return (x_mm + margin_mm) * ppm, (y_mm + margin_mm) * ppm


def detections_to_mm(detections, ppm, margin_mm):
    out = []
    for d in detections:
        x, y = px_to_mm(d.cx, d.cy, ppm, margin_mm)
        out.append(Observed(d.cls, d.conf, x, y, (d.x2 - d.x1) / ppm, (d.y2 - d.y1) / ppm,
                            (d.x1, d.y1, d.x2, d.y2)))
    return out


def yolo_label_to_mm(label_path: Path, class_names, canvas_w, canvas_h, ppm, margin_mm):
    """Read a YOLO .txt label (class cx cy w h, normalised) as Observed objects.

    Used to seed a golden reference from one hand-labelled known-good image.
    """
    out = []
    for line in Path(label_path).read_text().splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        c, cx, cy, w, h = int(parts[0]), *map(float, parts[1:])
        xp, yp = cx * canvas_w, cy * canvas_h
        wp, hp = w * canvas_w, h * canvas_h
        x, y = px_to_mm(xp, yp, ppm, margin_mm)
        out.append(Observed(class_names[c], 1.0, x, y, wp / ppm, hp / ppm,
                            (xp - wp / 2, yp - hp / 2, xp + wp / 2, yp + hp / 2)))
    return out
