"""
gui/overlay.py - draw inspection results on the canvas (colour code from the PDF).

  green solid  = OK
  red dashed   = MISSING (drawn at the golden-reference position)
  red solid    = WRONG TYPE or MISPLACED (with offset in mm)
  orange       = REVIEW (uncertain or extra)
"""
import cv2
import numpy as np

GREEN, RED, ORANGE, GREY = (40, 180, 40), (30, 30, 230), (0, 150, 255), (160, 160, 160)
BANNER = {"PASS": (40, 160, 40), "FAIL": (30, 30, 200), "REVIEW": (0, 140, 255)}


def _dashed_rect(img, p1, p2, color, thick=2, dash=8):
    x1, y1 = map(int, p1)
    x2, y2 = map(int, p2)
    for x in range(x1, x2, dash * 2):
        cv2.line(img, (x, y1), (min(x + dash, x2), y1), color, thick)
        cv2.line(img, (x, y2), (min(x + dash, x2), y2), color, thick)
    for y in range(y1, y2, dash * 2):
        cv2.line(img, (x1, y), (x1, min(y + dash, y2)), color, thick)
        cv2.line(img, (x2, y), (x2, min(y + dash, y2)), color, thick)


def _label(img, text, org, color):
    x, y = int(org[0]), int(max(12, org[1]))
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def draw_side(canvas, side_result, ppm, margin_mm):
    img = canvas.copy()
    for c in side_result.components:
        if c.status == "MISSING":
            w = (c.ref_w_mm or 2.0) * ppm
            h = (c.ref_h_mm or 2.0) * ppm
            cx, cy = (c.ref_x_mm + margin_mm) * ppm, (c.ref_y_mm + margin_mm) * ppm
            p1, p2 = (cx - w / 2, cy - h / 2), (cx + w / 2, cy + h / 2)
            _dashed_rect(img, p1, p2, RED)
            _label(img, f"{c.id} MISSING", (p1[0], p1[1] - 4), RED)
            continue
        x1, y1, x2, y2 = map(int, c.box_px)
        if c.status == "OK":
            cv2.rectangle(img, (x1, y1), (x2, y2), GREEN, 2)
        elif c.status in ("WRONG_TYPE", "MISPLACED"):
            cv2.rectangle(img, (x1, y1), (x2, y2), RED, 2)
            txt = f"{c.id} {c.detected_class}" if c.status == "WRONG_TYPE" \
                else f"{c.id} +{c.offset_mm:.2f}mm"
            _label(img, txt, (x1, y1 - 4), RED)
            # line from expected to detected centre
            ex, ey = (c.ref_x_mm + margin_mm) * ppm, (c.ref_y_mm + margin_mm) * ppm
            cv2.line(img, (int(ex), int(ey)), ((x1 + x2) // 2, (y1 + y2) // 2), RED, 1)
        else:  # UNCERTAIN
            cv2.rectangle(img, (x1, y1), (x2, y2), ORANGE, 2)
            _label(img, f"{c.id} ?{c.conf:.2f}", (x1, y1 - 4), ORANGE)
    for e in side_result.extras:
        if e.status == "EXTRA":
            x1, y1, x2, y2 = map(int, e.box_px)
            cv2.rectangle(img, (x1, y1), (x2, y2), ORANGE, 2)
            _label(img, f"extra {e.detected_class}", (x1, y1 - 4), ORANGE)
    return img


def message_image(text, size=(1200, 500), color=(0, 140, 255)):
    img = np.full((size[1], size[0], 3), 40, np.uint8)
    y = size[1] // 2 - 20 * (text.count("\n"))
    for line in text.split("\n"):
        cv2.putText(img, line, (30, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA)
        y += 45
    return img
