"""
tests/synthetic.py - draw a fake PCB X (both sides) inside a fake camera
image, so identification, orientation, alignment and the whole pipeline can
be tested WITHOUT hardware. Not used by the real system.

Side A (front/top):  "SHARP" + "QPWBP0335PFZZ" silkscreen near the bottom-left,
                     big coloured through-hole parts.
Side B (back/bottom): white "T1" block with an EAN-13 barcode, small SMD parts.
Both sides: four mounting holes at the corners (180-deg symmetric, like the
real board) - so orientation MUST come from the markings.
"""
import cv2
import numpy as np

BOARD_W, BOARD_H = 115.0, 45.0
HOLES = [(4.0, 4.0, 3.2), (111.0, 4.0, 3.2), (4.0, 41.0, 3.2), (111.0, 41.0, 3.2)]
# marker rectangles (x_mm, y_mm centre, w_mm, h_mm) used by the test profile
MARKERS = {
    "top": [("sharp_logo", 22.0, 39.5, 14.0, 4.0), ("part_number", 50.0, 39.5, 30.0, 4.0)],
    "bottom": [("t1_block", 38.0, 20.0, 12.0, 24.0), ("t1_label", 38.0, 5.5, 6.0, 4.0)],
}
BARCODE = ("barcode", 92.0, 38.0, 22.0, 8.0)       # barcode sticker area
# component layout (class, x_mm, y_mm, w_mm, h_mm, BGR colour)
LAYOUT = {
    "top": [("fuse", 18, 7, 22, 6, (200, 200, 210)), ("transformer", 70, 20, 24, 22, (30, 30, 30)),
            ("electrolytic_cap", 40, 15, 9, 9, (60, 40, 190)), ("electrolytic_cap", 98, 12, 10, 10, (60, 40, 190)),
            ("varistor", 14, 21, 6, 9, (170, 90, 30))],
    "bottom": [("resistor", 60, 12, 3, 1.6, (20, 20, 20)), ("resistor", 64, 12, 3, 1.6, (20, 20, 20)),
               ("diode", 77, 15, 2.2, 4.5, (25, 25, 25)), ("ic8", 50, 26, 5, 4, (15, 15, 15)),
               ("smd_capacitor", 70, 30, 2.0, 1.25, (90, 140, 180))],
}

_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011",
      "0110111", "0001011"]
_R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100",
      "1001000", "1110100"]
_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG",
           "LGLGGL", "LGGLGL"]


def ean13_bits(digits12: str) -> str:
    d = [int(c) for c in digits12]
    check = (10 - (sum(d[0::2]) + 3 * sum(d[1::2])) % 10) % 10
    d.append(check)
    bits = "101"
    for i, x in enumerate(d[1:7]):
        bits += _L[x] if _PARITY[d[0]][i] == "L" else _R[x][::-1]
    bits += "01010"
    for x in d[7:]:
        bits += _R[x]
    return bits + "101"


def draw_barcode(img, x0, y0, module_px, height_px, digits="480123456789"):
    bits = ean13_bits(digits)
    pad = 10 * module_px
    cv2.rectangle(img, (x0 - pad, y0 - pad // 2),
                  (x0 + len(bits) * module_px + pad, y0 + height_px + pad // 2), (255, 255, 255), -1)
    for i, b in enumerate(bits):
        if b == "1":
            cv2.rectangle(img, (x0 + i * module_px, y0),
                          (x0 + (i + 1) * module_px - 1, y0 + height_px), (0, 0, 0), -1)


def board_texture(side="top", ppm=15, seed=0, remove=(), shift=None, barcode=True):
    """Return (image, ppm). remove = indices of LAYOUT parts to leave out;
    shift = {index: (dx_mm, dy_mm)}."""
    rng = np.random.default_rng(seed + (0 if side == "top" else 99))
    w, h = int(BOARD_W * ppm), int(BOARD_H * ppm)
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (40, 110, 30) if side == "top" else (50, 120, 35)
    for _ in range(50):                                             # copper traces
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        cv2.line(img, (x, y), (x + int(rng.integers(-250, 250)), y + int(rng.integers(-40, 40))),
                 (55, 140, 45), 3)
    for fx, fy, d in HOLES:                                         # mounting holes
        c = (int(fx * ppm), int(fy * ppm))
        cv2.circle(img, c, int(d * ppm * 0.95), (215, 225, 225), -1)     # ring
        cv2.circle(img, c, int(d * ppm / 2), (20, 20, 20), -1)           # hole
    shift = shift or {}
    for i, (cls, x, y, cw, ch, col) in enumerate(LAYOUT[side]):
        if i in remove:
            continue
        dx, dy = shift.get(i, (0, 0))
        x0, y0 = int((x + dx - cw / 2) * ppm), int((y + dy - ch / 2) * ppm)
        cv2.rectangle(img, (x0, y0), (x0 + int(cw * ppm), y0 + int(ch * ppm)), col, -1)
        cv2.rectangle(img, (x0, y0), (x0 + int(cw * ppm), y0 + int(ch * ppm)), (200, 200, 200), 1)
    if side == "top":
        cv2.putText(img, "SHARP", (int(15.5 * ppm), int(41 * ppm)), cv2.FONT_HERSHEY_DUPLEX,
                    0.024 * ppm * 2.2, (235, 235, 235), 2)
        cv2.putText(img, "QPWBP0335PFZZ", (int(36 * ppm), int(41 * ppm)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.024 * ppm * 1.55, (235, 235, 235), 1)
    else:
        bx, by, bw, bh = 38.0, 20.0, 12.0, 24.0
        cv2.rectangle(img, (int((bx - bw / 2) * ppm), int((by - bh / 2) * ppm)),
                      (int((bx + bw / 2) * ppm), int((by + bh / 2) * ppm)), (240, 240, 240), -1)
        cv2.putText(img, "T1", (int(36 * ppm), int(7 * ppm)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.024 * ppm * 2.0, (235, 235, 235), 2)
        if barcode:
            draw_barcode(img, int(82.5 * ppm), int(35.5 * ppm), 3, int(5 * ppm))
    return img


def camera_image(board, angle_deg=0.0, shift=(0, 0), size=(2304, 1296),
                 bg=(25, 25, 25), rotate180=False, rotate90=False):
    """Place the board texture in a camera-sized image (matte black nest)."""
    if rotate180:
        board = cv2.rotate(board, cv2.ROTATE_180)
    if rotate90:
        board = cv2.rotate(board, cv2.ROTATE_90_CLOCKWISE)
    W, H = size
    out = np.full((H, W, 3), bg, np.uint8)
    bh, bw = board.shape[:2]
    cx, cy = W / 2 + shift[0], H / 2 + shift[1]
    M = cv2.getRotationMatrix2D((bw / 2, bh / 2), angle_deg, 1.0)
    M[0, 2] += cx - bw / 2
    M[1, 2] += cy - bh / 2
    mask = cv2.warpAffine(np.full((bh, bw), 255, np.uint8), M, (W, H))
    warped = cv2.warpAffine(board, M, (W, H))
    out[mask > 0] = warped[mask > 0]
    noise = np.random.default_rng(1).normal(0, 3, out.shape)
    return np.clip(out + noise, 0, 255).astype(np.uint8)


def build_test_profile(profile_dir, canvas, align_cfg, with_barcode=False):
    """Create board_profile.json + templates for the synthetic board using the
    SAME code path as tools/build_board_profile.py."""
    import json
    from pathlib import Path
    from vision.board_alignment import BoardAligner
    from vision.identification import crop_template
    profile_dir = Path(profile_dir)
    (profile_dir / "templates").mkdir(parents=True, exist_ok=True)
    base = BoardAligner("upper", canvas, {}, align_cfg)
    sides = {}
    for side in ("top", "bottom"):
        raw = camera_image(board_texture(side))
        H, _, _ = base.coarse_homography(raw)
        cnv = cv2.warpPerspective(raw, H, (canvas.w, canvas.h))
        markers = []
        for name, x, y, w, h in MARKERS[side]:
            t = crop_template(cnv, x, y, w, h, canvas.ppm, canvas.m)
            rel = f"templates/{side}_{name}.png"
            cv2.imwrite(str(profile_dir / rel), t)
            markers.append({"name": name, "type": "template", "x_mm": x, "y_mm": y,
                            "w_mm": w, "h_mm": h, "template": rel})
        if side == "bottom" and with_barcode:
            n, x, y, w, h = BARCODE
            markers.append({"name": n, "type": "barcode", "x_mm": x, "y_mm": y, "w_mm": w,
                            "h_mm": h, "search_mm": 3.0})
        sides[side] = {"markers": markers, "min_markers": 1,
                       "fiducials_mm": [list(hh) for hh in HOLES]}
    prof = {"board": "PCB X", "sides": sides}
    (profile_dir / "board_profile.json").write_text(json.dumps(prof, indent=2))
    return prof


def golden_for_layout():
    """Golden reference matching LAYOUT exactly (test use)."""
    sides = {}
    for side, parts in LAYOUT.items():
        comps = [{"id": f"{side[0].upper()}{i + 1}", "class": cls, "x_mm": float(x), "y_mm": float(y),
                  "w_mm": float(w), "h_mm": float(h)} for i, (cls, x, y, w, h, _) in enumerate(parts)]
        sides[side] = {"label": side, "thresholds": {"t_low": 0.25, "t_high": 0.60},
                       "default_tolerance": {"tol_mm": 0.5, "tol_x_mm": None, "tol_y_mm": None},
                       "class_tolerance": {}, "components": comps}
    return {"schema_version": 2, "profile": "test", "board": "PCB X",
            "board_size_mm": [BOARD_W, BOARD_H], "canvas": {"px_per_mm": 10.0, "margin_mm": 2.5},
            "revision": 1, "sides": sides}
