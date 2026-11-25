"""
Scenario A/B/C tests of vision/board_alignment.py on synthetic images.
Run:  python -m pytest -q tests
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C  # noqa: E402
from tests.synthetic import FIDUCIALS_A, board_texture, camera_image  # noqa: E402
from vision import fiducials as fid  # noqa: E402
from vision.board_alignment import BoardAligner, Canvas, _template_prep  # noqa: E402
from vision.preprocessing import to_gray_normalized  # noqa: E402


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    ref = tmp_path_factory.mktemp("refs")
    geo = Canvas(115.0, 45.0, 2.5, 10.0)
    A, B = board_texture("A"), board_texture("B")
    # 1) teach: align a normal image with outline only, store fiducials + templates
    base = BoardAligner("top", geo, {}, C.ALIGN)
    ok_img = camera_image(A)
    H, _, _ = base.coarse_homography(ok_img)
    canvas = cv2.warpPerspective(ok_img, H, (geo.w, geo.h))
    cands = fid.find_candidates(to_gray_normalized(canvas), geo.ppm)
    fids = []
    for fx, fy, d in FIDUCIALS_A:   # pick the candidates nearest the true fiducials
        ex, ey = (fx + 2.5) * 10, (fy + 2.5) * 10
        c = min(cands, key=lambda c: np.hypot(c["x_px"] - ex, c["y_px"] - ey))
        fids.append([c["x_px"] / 10 - 2.5, c["y_px"] / 10 - 2.5, c["d_px"] / 10])
    (ref / "templates").mkdir()
    cv2.imwrite(str(ref / "templates/top_ok.png"),
                _template_prep(canvas, C.ALIGN["template_size"]).astype(np.uint8))
    flip_img = camera_image(B)
    Hf, _, _ = base.coarse_homography(flip_img)
    cv2.imwrite(str(ref / "templates/top_flipped.png"),
                _template_prep(cv2.warpPerspective(flip_img, Hf, (geo.w, geo.h)),
                               C.ALIGN["template_size"]).astype(np.uint8))
    profile = {"sides": {"top": {"fiducials_mm": fids, "template_ok": "templates/top_ok.png",
                                 "template_flipped": "templates/top_flipped.png"}}}
    (ref / "board_profile.json").write_text(json.dumps(profile))
    aligner = BoardAligner("top", geo, profile, C.ALIGN, None, ref)
    return aligner, A, B, fids


def _fid_error_mm(aligner, canvas, fids):
    m = fid.locate_fiducials(to_gray_normalized(canvas), fids, 10.0, 2.5, 1.5)
    errs = [np.hypot(f["found_px"][0] - f["ref_px"][0], f["found_px"][1] - f["ref_px"][1]) / 10
            for f in m if f["found_px"] is not None]
    return max(errs)


def test_scenario_a_normal(setup):
    aligner, A, _, fids = setup
    r = aligner.align(camera_image(A, angle_deg=1.5, shift=(30, -20)))
    assert r.status == "ok", r.message
    assert not r.rotated_180
    assert _fid_error_mm(aligner, r.canvas, fids) < 0.2


def test_scenario_b_rotated_180(setup):
    aligner, A, _, fids = setup
    r = aligner.align(camera_image(A, angle_deg=-2.0, shift=(-40, 25), rotate180=True))
    assert r.status == "ok", r.message
    assert r.rotated_180
    assert _fid_error_mm(aligner, r.canvas, fids) < 0.2


def test_scenario_c_flipped(setup):
    aligner, _, B, _ = setup
    r = aligner.align(camera_image(B, angle_deg=1.0))
    assert r.status == "wrong_side", (r.status, r.template_scores)


def test_empty_tray(setup):
    aligner, *_ = setup
    empty = np.full((1296, 2304, 3), 200, np.uint8)
    r = aligner.align(empty)
    assert r.status in ("no_board", "unknown_board")


def test_partially_hidden_fiducial(setup):
    aligner, A, _, _ = setup
    A2 = A.copy()
    cv2.circle(A2, (int(111 * 15), int(4 * 15)), 45, (40, 110, 30), -1)   # cover one
    r = aligner.align(camera_image(A2))
    assert r.status == "ok" and r.fiducials_found == 2


def test_fiducials_decide_orientation_without_templates(setup):
    aligner, A, _, fids = setup
    no_tpl = BoardAligner("top", aligner.cv, {"sides": {"top": {"fiducials_mm": fids}}},
                          C.ALIGN)
    r = no_tpl.align(camera_image(A, rotate180=True))
    assert r.rotated_180 and r.status == "ok"
