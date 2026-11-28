"""
GUI smoke test (SIMULATED): opens the real Tkinter interface with simulated
cameras and fake detectors, runs an inspection, edits a tolerance through the
Settings window, opens History and exports a report. Skipped automatically
when tkinter or a display is not available (e.g. headless CI).
Run on the Pi desktop or a PC:  python -m pytest -q tests/test_gui_smoke.py
"""
import os
import time

import pytest

tk = pytest.importorskip("tkinter")
if os.name != "nt" and not os.environ.get("DISPLAY"):
    pytest.skip("no display", allow_module_level=True)

import config as C  # noqa: E402
from tests import synthetic as S  # noqa: E402
from tests.conftest import FakeDetector  # noqa: E402


def pump(app, until, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.root.update()
        if until():
            return True
        time.sleep(0.02)
    return False


def test_gui_end_to_end(sim, monkeypatch):
    from tkinter import messagebox
    for name in ("showinfo", "showerror"):
        monkeypatch.setattr(messagebox, name, lambda *a, **k: None)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(C, "FULLSCREEN", False)
    sim.put_images("upper", S.camera_image(S.board_texture("top")))
    sim.put_images("lower", S.camera_image(S.board_texture("bottom")))
    system = sim.system(start=False)
    system.detectors = {"top": FakeDetector("top"), "bottom": FakeDetector("bottom", drop=[0])}
    from gui import history_window
    monkeypatch.setattr(history_window, "_open", lambda p: None)
    from gui.interface import App
    app = App(system, None)
    assert pump(app, lambda: str(app.start_btn["state"]) == "normal"), app.status["text"]
    app.request_start()
    assert pump(app, lambda: app.banner["text"] in ("PASS", "FAIL", "REVIEW"))
    assert app.banner["text"] == "FAIL"                    # bottom B1 missing
    assert any("MISSING" in str(app.flags.item(i)["values"]) for i in app.flags.get_children())

    app.open_settings()
    sw = app.settings_win
    sw.side.set("bottom")
    sw._load_side()
    sw.vars["tol_mm"].set("0.8")
    sw._save_tolerances()
    assert system.golden["revision"] == 2
    assert system.golden["sides"]["bottom"]["default_tolerance"]["tol_mm"] == 0.8
    sw.vars["t_low"].set("0.9")                            # invalid: t_low > t_high
    sw._save_tolerances()
    assert system.golden["revision"] == 2                  # not saved

    app.open_history()
    hw = app.history_win
    pump(app, lambda: False, timeout=1.0)
    hw.refresh()
    assert hw.tree.get_children()
    hw.tree.selection_set(hw.tree.get_children()[0])
    system.image_logger.flush()
    hw.export_report()
    folder = next(iter(hw.rows.values()))["folder"]
    assert (__import__("pathlib").Path(folder) / "report.html").exists()

    app.toggle_preview()
    assert pump(app, lambda: "LIVE PREVIEW" in app.side_info["top"]["text"], timeout=10)
    app.toggle_preview(); app.toggle_preview()               # lower, then off
    app.cmd_q.put("quit")
    pump(app, lambda: False, timeout=0.5)
    app.root.destroy()
