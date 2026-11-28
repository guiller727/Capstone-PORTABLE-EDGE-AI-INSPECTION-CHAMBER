"""
V2 scenario tests - the 15 cases required for the capstone (all SIMULATED:
synthetic board images, file cameras, fake detectors). Physical validation
on the real chamber is still required (docs/D_Testing_and_Validation.md).

  1 front identification        9 low-confidence detection
  2 back identification        10 invalid golden reference JSON
  3 unknown PCB                11 missing .pt model
  4 correct orientation        12 camera initialisation failure
  5 rotated PCB (90/180)       13 front PASS + back PASS
  6 flipped PCB                14 front FAIL + back PASS
  7 missing component          15 front PASS + back REVIEW
  8 incorrect placement
"""
import json

import numpy as np
import pytest

import config as C
from inspection import decision_engine as de
from inspection.golden_reference import (GoldenError, list_backups, load_golden,
                                         save_golden_safe, validate_golden)
from inspection.profile import ModelError, Profile
from tests import synthetic as S
from tests.conftest import FakeDetector

A = lambda **kw: S.camera_image(S.board_texture("top", **kw))          # noqa: E731
B = lambda **kw: S.camera_image(S.board_texture("bottom", **kw))       # noqa: E731


def run_dual(sim, upper, lower, top=None, bottom=None):
    s = sim.system(top, bottom)
    return s, s.process({"upper": upper, "lower": lower})


# 1, 2, 4 -------------------------------------------------------------------
def test_01_front_identification_and_04_correct_orientation(sim):
    s, out = run_dual(sim, A(), B())
    info = out["side_info"]["top"]
    assert info["camera"] == "upper" and "sharp_logo" in info["identification"]
    assert info["rotation_deg"] == 0 and info["status"] == "ok"


def test_02_back_identification(sim):
    s, out = run_dual(sim, A(), B())
    info = out["side_info"]["bottom"]
    assert info["camera"] == "lower" and "t1_block" in info["identification"]
    assert "barcode" in info["identification"]          # optional barcode marker read too


def test_03_unknown_pcb_gives_review(sim):
    other = S.camera_image(np.full((675, 1725, 3), (40, 110, 30), np.uint8))
    s, out = run_dual(sim, other, B())
    assert out["side_results"]["top"].verdict == "REVIEW"
    assert any(de.R_NOT_IDENTIFIED in f for f in out["side_results"]["top"].flags)
    assert out["verdict"] == "REVIEW"


# 5 -------------------------------------------------------------------------
@pytest.mark.parametrize("kw,deg", [({"rotate180": True}, 180), ({"angle_deg": 2.0}, 0)])
def test_05_rotated_pcb_is_corrected(sim, kw, deg):
    s, out = run_dual(sim, S.camera_image(S.board_texture("top"), **kw), B())
    assert out["side_info"]["top"]["rotation_deg"] % 360 == deg
    assert out["verdict"] == "PASS"


def test_05b_rotated_90_in_camera_image(sim):
    img = S.camera_image(S.board_texture("top", ppm=10), rotate90=True)
    s = sim.system()
    a = s.analyze("upper", img)
    assert a.align.status == "ok" and a.side == "top" and a.align.rotation_deg in (90, 270)


def test_05c_ambiguous_orientation_is_review(sim):
    s = sim.system()
    # make the 0 and 180 deg views identical -> markers cannot decide
    sym = S.board_texture("top")
    half = sym[:, : sym.shape[1] // 2]
    sym = np.hstack([half, np.rot90(np.rot90(half))])
    sym = np.vstack([sym[: sym.shape[0] // 2], np.rot90(np.rot90(sym[: sym.shape[0] // 2]))])
    out = s.process({"upper": S.camera_image(sym), "lower": B()})
    assert out["side_results"]["top"].verdict == "REVIEW"


# 6 -------------------------------------------------------------------------
def test_06_flipped_pcb_dual_mode_handled(sim):
    s, out = run_dual(sim, B(), A())                # back side faces the UPPER camera
    assert out["side_info"]["top"]["camera"] == "lower"
    assert out["side_info"]["bottom"]["camera"] == "upper"
    assert out["verdict"] == "PASS" and out["notes"]


def test_06b_flipped_pcb_rejected_when_not_allowed(sim, monkeypatch):
    monkeypatch.setattr(C, "ALLOW_FLIPPED_INSERTION", False)
    s, out = run_dual(sim, B(), A())
    assert out["state"] == "WRONG_SIDE"


def test_06c_flip_mode_workflow(sim, monkeypatch):
    monkeypatch.setattr(C, "INSPECTION_MODE", "flip")
    sim.put_images("upper", S.camera_image(S.board_texture("top"), rotate180=True), A(), B())  # front, front again, back
    s = sim.system()
    o1 = s.inspect()
    assert o1["state"] == "FLIP_PROMPT" and "Flip" in o1["message"]
    o2 = s.inspect()
    assert o2["state"] == "SAME_SIDE"
    o3 = s.inspect()
    assert o3["state"] == "RESULT" and o3["verdict"] == "PASS"
    assert set(o3["side_info"]) == {"top", "bottom"}


def test_06d_flip_mode_finish_early_is_review(sim, monkeypatch):
    monkeypatch.setattr(C, "INSPECTION_MODE", "flip")
    sim.put_images("upper", A())
    s = sim.system()
    s.inspect()
    out = s.finish_flip()
    assert out["side_results"]["bottom"].verdict == "REVIEW" and out["verdict"] == "REVIEW"


# 7, 8, 9 -------------------------------------------------------------------
def test_07_missing_component_fail(sim):
    s, out = run_dual(sim, A(), B(), bottom=FakeDetector("bottom", drop=[0]))
    st = {c.id: c.status for c in out["side_results"]["bottom"].components}
    assert st["B1"] == "MISSING" and out["verdict"] == "FAIL"


def test_08_incorrect_placement_fail(sim):
    s, out = run_dual(sim, A(), B(), top=FakeDetector("top", shift={1: (0.9, 0.0)}))
    t2 = [c for c in out["side_results"]["top"].components if c.id == "T2"][0]
    assert t2.status == "MISPLACED" and abs(t2.dx_mm - 0.9) < 0.05
    assert out["verdict"] == "FAIL"


def test_08b_per_axis_tolerance(sim):
    g = S.golden_for_layout()
    g["sides"]["top"]["components"][1].update(tol_mm=2.0, tol_y_mm=0.3)
    (sim.profile_dir / "golden_reference.json").write_text(json.dumps(g))
    s, out = run_dual(sim, A(), B(), top=FakeDetector("top", shift={1: (0.0, 0.5)}))
    t2 = [c for c in out["side_results"]["top"].components if c.id == "T2"][0]
    assert t2.status == "MISPLACED" and "|dy|" in t2.message


def test_09_low_confidence_is_review_not_fail(sim):
    s, out = run_dual(sim, A(), B(), bottom=FakeDetector("bottom", conf={3: 0.4}))
    assert out["side_results"]["bottom"].verdict == "REVIEW"
    assert out["verdict"] == "REVIEW"


# 10, 11, 12 ----------------------------------------------------------------
def test_10_invalid_golden_json(sim):
    p = sim.profile_dir / "golden_reference.json"
    p.write_text("{ not json")
    with pytest.raises(GoldenError, match="not valid JSON"):
        load_golden(p)
    g = S.golden_for_layout()
    g["sides"]["top"]["thresholds"] = {"t_low": 0.7, "t_high": 0.5}
    g["sides"]["top"]["components"][0]["tol_mm"] = -1
    g["sides"]["bottom"]["components"][1]["id"] = "B1"
    errors, _ = validate_golden(g)
    assert len(errors) >= 3
    s = sim.system()                                # system refuses to run on it
    assert not s.ready and any("golden" in p_.lower() for p_ in s.problems)


def test_10b_safe_save_keeps_backup_and_rejects_invalid(sim):
    p = sim.profile_dir / "golden_reference.json"
    good = load_golden(p)
    good["sides"]["top"]["default_tolerance"]["tol_mm"] = 0.8
    saved = save_golden_safe(p, good, "test")
    assert saved["revision"] == 2 and list_backups(p)
    bad = json.loads(p.read_text())
    bad["sides"]["top"]["default_tolerance"]["tol_mm"] = 50
    with pytest.raises(GoldenError):
        save_golden_safe(p, bad, "test")
    assert load_golden(p)["sides"]["top"]["default_tolerance"]["tol_mm"] == 0.8


def test_11_missing_model_reported(sim):
    prof = Profile(C.MODELS_DIR, "pcb_x")
    with pytest.raises(ModelError, match="No usable top model"):
        prof.model_info("top")
    from inspection.runner import InspectionSystem
    s = InspectionSystem(simulate=True, load_models=True)
    sim.put_images("upper", A())
    sim.put_images("lower", B())
    s.start()
    assert not s.ready and any("model" in p.lower() for p in s.problems)
    assert s.inspect()["state"] == "NOT_READY"


def test_11b_fake_pt_file_rejected(sim):
    (sim.profile_dir / "top").mkdir()
    (sim.profile_dir / "top" / "best.pt").write_bytes(b"0" * 100)
    with pytest.raises(ModelError, match="too small"):
        Profile(C.MODELS_DIR, "pcb_x").model_info("top")


def test_12_camera_init_failure(sim):
    from inspection.runner import InspectionSystem
    s = InspectionSystem(simulate=True, load_models=False)      # sim folders are empty
    s.start()
    assert not s.ready and any("upper camera" in p for p in s.problems)


def test_12b_capture_failure_during_inspection_is_review(sim):
    s, out = run_dual(sim, A(), None)
    assert out["side_results"]["bottom"].verdict == "REVIEW"
    assert any(de.R_NOT_IDENTIFIED in f or de.R_CAPTURE in f
               for f in out["side_results"]["bottom"].flags)


# 13, 14, 15 ---------------------------------------------------------------
def test_13_front_pass_back_pass(sim):
    s, out = run_dual(sim, A(), B())
    assert [out["side_results"][x].verdict for x in ("top", "bottom")] == ["PASS", "PASS"]
    assert out["verdict"] == "PASS"


def test_14_front_fail_back_pass(sim):
    s, out = run_dual(sim, A(), B(), top=FakeDetector("top", drop=[2]))
    assert out["side_results"]["top"].verdict == "FAIL"
    assert out["side_results"]["bottom"].verdict == "PASS"
    assert out["verdict"] == "FAIL"


def test_15_front_pass_back_review(sim):
    s, out = run_dual(sim, A(), B(), bottom=FakeDetector("bottom", extra=[("diode", 100, 20, 0.9)]))
    assert out["side_results"]["top"].verdict == "PASS"
    assert out["side_results"]["bottom"].verdict == "REVIEW"
    assert out["verdict"] == "REVIEW"


def test_combination_table():
    mk = lambda v: de.SideResult("x", v)  # noqa: E731
    table = [("PASS", "PASS", "PASS"), ("PASS", "FAIL", "FAIL"), ("FAIL", "PASS", "FAIL"),
             ("PASS", "REVIEW", "REVIEW"), ("REVIEW", "FAIL", "FAIL"), ("REVIEW", "REVIEW", "REVIEW")]
    for f, b, overall in table:
        assert de.combine([mk(f), mk(b)]) == overall


# full live path: file cameras + logging ------------------------------------
def test_inspect_logs_record(sim):
    sim.put_images("upper", A())
    sim.put_images("lower", B())
    s = sim.system()
    out = s.inspect()
    s.image_logger.flush()
    assert out["verdict"] == "PASS"
    rec = json.loads((out["folder"] / "result.json").read_text())
    assert rec["golden_revision"] == 1 and rec["golden_hash"] and rec["mode"] == "dual"
    assert (out["folder"] / "overlay_top.jpg").exists()
    from storage import make_html_report
    assert "PCB inspection report" in make_html_report(out["folder"]).read_text()
    rows = s.result_logger.read_rows()
    assert rows and rows[0]["verdict"] == "PASS"


def test_settings_validation(sim):
    with pytest.raises(ValueError):
        C.save_settings_file({"INSPECTION_MODE": "triple"}, sim.root / "config" / "settings.json")
    C.save_settings_file({"LED_SETTLE_S": 0.2}, sim.root / "config" / "settings.json")
    assert C.LED_SETTLE_S == 0.2
