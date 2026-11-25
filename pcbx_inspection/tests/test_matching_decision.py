"""Unit tests for component matching and the PASS/FAIL/REVIEW rules."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inspection import decision_engine as de  # noqa: E402
from inspection.component_matching import hungarian_match, nearest_neighbour_match  # noqa: E402
from lighting.led_controller import BIT0, BIT1, encode_ws2812  # noqa: E402
from vision.coordinate_extraction import Observed  # noqa: E402

GOLD = [
    {"id": "R1", "class": "resistor", "x_mm": 10.0, "y_mm": 10.0, "w_mm": 2, "h_mm": 1.2, "tol_mm": 0.5},
    {"id": "R2", "class": "resistor", "x_mm": 12.0, "y_mm": 10.0, "w_mm": 2, "h_mm": 1.2, "tol_mm": 0.5},
    {"id": "C1", "class": "smd_capacitor", "x_mm": 30.0, "y_mm": 20.0, "w_mm": 2, "h_mm": 1.2, "tol_mm": 0.5},
    {"id": "U1", "class": "ic8", "x_mm": 60.0, "y_mm": 25.0, "w_mm": 5, "h_mm": 4, "tol_mm": 0.6},
]


def obs(cls, x, y, conf=0.9, w=2.0, h=1.2):
    px = (x + 2.5) * 10, (y + 2.5) * 10
    return Observed(cls, conf, x, y, w, h,
                    (px[0] - w * 5, px[1] - h * 5, px[0] + w * 5, px[1] + h * 5))


def run(observed):
    m = hungarian_match(GOLD, observed)
    return de.evaluate_side("bottom", GOLD, observed, m, t_high=0.6)


def test_all_ok_pass():
    r = run([obs("resistor", 10.1, 10), obs("resistor", 12, 10.1),
             obs("smd_capacitor", 30, 20), obs("ic8", 60.2, 25, w=5, h=4)])
    assert r.verdict == "PASS"
    assert all(c.status == "OK" for c in r.components)


def test_missing_fail():
    r = run([obs("resistor", 10, 10), obs("smd_capacitor", 30, 20), obs("ic8", 60, 25)])
    st = {c.id: c.status for c in r.components}
    assert r.verdict == "FAIL" and st["R2"] == "MISSING"


def test_wrong_type_fail():
    r = run([obs("resistor", 10, 10), obs("resistor", 12, 10),
             obs("diode", 30, 20), obs("ic8", 60, 25)])
    assert {c.id: c.status for c in r.components}["C1"] == "WRONG_TYPE"
    assert r.verdict == "FAIL"


def test_misplaced_fail():
    r = run([obs("resistor", 10, 10), obs("resistor", 12, 10),
             obs("smd_capacitor", 30.9, 20), obs("ic8", 60, 25)])
    c1 = [c for c in r.components if c.id == "C1"][0]
    assert c1.status == "MISPLACED" and abs(c1.offset_mm - 0.9) < 1e-6


def test_uncertain_review():
    r = run([obs("resistor", 10, 10), obs("resistor", 12, 10, conf=0.4),
             obs("smd_capacitor", 30, 20), obs("ic8", 60, 25)])
    assert r.verdict == "REVIEW"


def test_extra_review_and_noise_ignored():
    base = [obs("resistor", 10, 10), obs("resistor", 12, 10),
            obs("smd_capacitor", 30, 20), obs("ic8", 60, 25)]
    assert run(base + [obs("diode", 90, 30, conf=0.3)]).verdict == "PASS"      # noise
    assert run(base + [obs("diode", 90, 30, conf=0.9)]).verdict == "REVIEW"    # extra


def test_duplicate_box_ignored():
    base = [obs("resistor", 10, 10), obs("resistor", 12, 10),
            obs("smd_capacitor", 30, 20), obs("ic8", 60, 25, w=5, h=4)]
    r = run(base + [obs("ic8", 60.1, 25.1, conf=0.8, w=5, h=4)])
    assert r.verdict == "PASS"
    assert any(e.status == "DUPLICATE" for e in r.extras)


def test_fail_beats_review():
    r = run([obs("resistor", 10, 10, conf=0.4), obs("smd_capacitor", 30, 20), obs("ic8", 60, 25)])
    assert r.verdict == "FAIL"      # R2 missing + R1 uncertain -> FAIL


def test_hungarian_one_to_one_vs_nearest_neighbour():
    # One resistor detected between R1 and R2: NN gives it to both, Hungarian to one.
    single = [obs("resistor", 11.0, 10.0)]
    nn = nearest_neighbour_match(GOLD, single)
    hu = hungarian_match(GOLD, single)
    assert len([p for p in nn if p[1] == 0]) == 2
    assert len([p for p in hu if p[1] == 0]) == 1


def test_coarse_alignment_downgrades_pass():
    o = [obs("resistor", 10, 10), obs("resistor", 12, 10),
         obs("smd_capacitor", 30, 20), obs("ic8", 60, 25)]
    r = de.evaluate_side("bottom", GOLD, o, hungarian_match(GOLD, o), 0.6,
                         alignment_status="coarse")
    assert r.verdict == "REVIEW"


def test_combine():
    mk = lambda v: de.SideResult("x", v)  # noqa: E731
    assert de.combine([mk("PASS"), mk("PASS")]) == "PASS"
    assert de.combine([mk("PASS"), mk("REVIEW")]) == "REVIEW"
    assert de.combine([mk("REVIEW"), mk("FAIL")]) == "FAIL"


def test_ws2812_encoding():
    data = encode_ws2812([(255, 0, 0)], "GRB")
    body = data[1:25]
    assert list(body[:8]) == [BIT0] * 8        # G = 0
    assert list(body[8:16]) == [BIT1] * 8      # R = 255
    assert list(body[16:24]) == [BIT0] * 8     # B = 0
    assert data[25:] == b"\x00" * (len(data) - 25)
