"""
Shared fixtures: a complete SIMULATED system (profile, golden reference,
board profile, file cameras, fake detectors) in a temporary folder.
Nothing here touches real hardware; tests marked as hardware tests in
docs/D_Testing_and_Validation.md must still be run on the Pi.
"""
import copy
import json
import sys
from pathlib import Path

import cv2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C  # noqa: E402
from tests import synthetic as S  # noqa: E402
from vision.component_detection import Detection  # noqa: E402

CLASSES = {"top": ["electrolytic_cap", "film_capacitor", "ceramic_capacitor", "varistor", "fuse",
                   "inductor", "transformer", "connector"],
           "bottom": ["resistor", "smd_capacitor", "diode", "ic8"]}


class FakeDetector:
    """Returns the true LAYOUT boxes (canvas px) with optional defects.
    drop: indices removed; shift: {i: (dx_mm, dy_mm)}; conf: {i: value}; cls: {i: name}."""

    def __init__(self, side, drop=(), shift=None, conf=None, cls=None, extra=()):
        self.side, self.drop = side, set(drop)
        self.shift, self.conf, self.cls, self.extra = shift or {}, conf or {}, cls or {}, extra
        self.format, self.last_ms = "fake", 1.0

    def detect(self, img, conf):
        out = []
        for i, (c, x, y, w, h, _) in enumerate(S.LAYOUT[self.side]):
            if i in self.drop:
                continue
            dx, dy = self.shift.get(i, (0, 0))
            cx, cy = (x + dx + 2.5) * 10, (y + dy + 2.5) * 10
            p = self.conf.get(i, 0.9)
            if p >= conf:
                out.append(Detection(self.cls.get(i, c), p, cx - w * 5, cy - h * 5,
                                     cx + w * 5, cy + h * 5))
        for c, x, y, p in self.extra:
            cx, cy = (x + 2.5) * 10, (y + 2.5) * 10
            out.append(Detection(c, p, cx - 10, cy - 10, cx + 10, cy + 10))
        return out


@pytest.fixture
def sim(tmp_path, monkeypatch):
    """Patch config to a temporary, fully simulated installation."""
    models = tmp_path / "models"
    pdir = models / "pcb_x"
    pdir.mkdir(parents=True)
    meta = {"schema_version": 2, "profile": "pcb_x", "board_name": "PCB X",
            "board_size_mm": [S.BOARD_W, S.BOARD_H], "canvas": {"px_per_mm": 10.0, "margin_mm": 2.5},
            "sides": {s: {"label": C.SIDE_LABELS[s], "classes": CLASSES[s],
                          "model": {"ncnn": f"{s}/best_ncnn_model", "pt": f"{s}/best.pt",
                                    "imgsz": 640}} for s in ("top", "bottom")}}
    (pdir / "metadata.json").write_text(json.dumps(meta))
    (pdir / "golden_reference.json").write_text(json.dumps(S.golden_for_layout()))
    from vision.board_alignment import Canvas
    S.build_test_profile(pdir, Canvas(115, 45, 2.5, 10), C.ALIGN, with_barcode=True)
    cams = copy.deepcopy(C.CAMERAS)
    for cam in cams:
        cams[cam]["simulate_folder"] = str(tmp_path / "sim" / cam)
        (tmp_path / "sim" / cam).mkdir(parents=True)
    for k, v in {"MODELS_DIR": models, "LOGS_DIR": tmp_path / "logs",
                 "CALIBRATION_DIR": tmp_path / "cal", "CAMERAS": cams,
                 "ACTIVE_PROFILE": "pcb_x", "INSPECTION_MODE": "dual", "FLIP_CAMERA": "upper",
                 "ALLOW_FLIPPED_INSERTION": True, "LED_SETTLE_S": 0.0,
                 "SETTINGS_FILE": tmp_path / "config" / "settings.json"}.items():
        monkeypatch.setattr(C, k, v)

    class Env:
        root = tmp_path
        profile_dir = pdir

        @staticmethod
        def put_images(cam, *imgs):
            folder = tmp_path / "sim" / cam
            for f in folder.glob("*.png"):
                f.unlink()
            for i, img in enumerate(imgs):
                cv2.imwrite(str(folder / f"{i:03d}.png"), img)

        @staticmethod
        def system(top=None, bottom=None, start=True):
            from inspection.runner import InspectionSystem
            s = InspectionSystem(simulate=True, load_models=False)
            if start:
                s.start()
                s.detectors = {"top": top or FakeDetector("top"),
                               "bottom": bottom or FakeDetector("bottom")}
                s.problems = [p for p in s.problems if "model" not in p.lower()]
                s.ready = not s.problems
            return s

    return Env
