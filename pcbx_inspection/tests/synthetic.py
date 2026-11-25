"""
tests/synthetic.py - draw a fake PCB in a fake camera image, so the
alignment code can be tested without hardware. Not used by the real system.
"""
import cv2
import numpy as np

BOARD_W, BOARD_H = 115.0, 45.0
FIDUCIALS_A = [(4.0, 4.0, 1.5), (111.0, 4.0, 1.5), (4.0, 41.0, 1.5)]   # L-shape
FIDUCIALS_B = [(6.0, 6.0, 1.5), (109.0, 39.0, 1.5)]


def board_texture(side="A", ppm=15, seed=0):
    rng = np.random.default_rng(seed if side == "A" else seed + 99)
    w, h = int(BOARD_W * ppm), int(BOARD_H * ppm)
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (40, 110, 30) if side == "A" else (60, 90, 30)        # solder mask
    for _ in range(60):                                             # traces
        x, y = rng.integers(0, w), rng.integers(0, h)
        cv2.line(img, (int(x), int(y)), (int(x + rng.integers(-300, 300)), int(y)),
                 (50, 140, 40), 3)
    for _ in range(25 if side == "A" else 40):                       # components
        x, y = rng.integers(80, w - 160), rng.integers(80, h - 120)
        cw, chh = rng.integers(30, 140), rng.integers(20, 90)
        col = tuple(int(c) for c in rng.integers(20, 230, 3))
        cv2.rectangle(img, (int(x), int(y)), (int(x + cw), int(y + chh)), col, -1)
    fids = FIDUCIALS_A if side == "A" else FIDUCIALS_B
    for fx, fy, d in fids:
        c = (int(fx * ppm), int(fy * ppm))
        cv2.circle(img, c, int(d * ppm * 1.4), (25, 60, 20), -1)    # clearance ring
        cv2.circle(img, c, int(d * ppm / 2), (200, 220, 230), -1)   # copper pad
    return img


def camera_image(board, angle_deg=0.0, shift=(0, 0), size=(2304, 1296), ppm=15,
                 bg=(200, 200, 200), rotate180=False):
    """Place the board texture in a camera-sized image with rotation/shift."""
    if rotate180:
        board = cv2.rotate(board, cv2.ROTATE_180)
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
