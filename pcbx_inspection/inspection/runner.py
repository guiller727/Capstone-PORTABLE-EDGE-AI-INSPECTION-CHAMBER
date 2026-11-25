"""
inspection/runner.py - the complete inspection sequence for one board.

    START
      |-- door closed?                         no -> DOOR_OPEN (no verdict)
      |-- capture TOP    (top LED only, settle, flush, grab, quality check, retry)
      |-- capture BOTTOM (bottom LED only, ...)          camera error -> ERROR
      |-- align both sides (undistort, outline, orientation/side, fiducials)
      |        no board      -> NO_BOARD      (no verdict)
      |        flipped board -> WRONG_SIDE    (no verdict, "flip the board")
      |        not PCB X     -> UNKNOWN_BOARD (no verdict)
      |-- CLAHE (same function used for the training images)
      |-- YOLO on both canvases (conf >= T_LOW)
      |-- box centres -> mm -> Hungarian matching with golden reference
      |-- rules -> side verdicts -> board verdict PASS / FAIL / REVIEW
      '-- overlays, logging (images saved in background)

Capture happens for BOTH sides before identification because it only takes
~1-2 s and the side/orientation check needs the aligned images anyway.
Captures are SEQUENTIAL (one light at a time) so light from one side does
not leak through holes and board edges into the other camera.

`process(raw_top, raw_bottom)` contains everything after capture and is used
unchanged by tools/run_offline.py and the tests - so the offline evaluation
of saved images is exactly the same code as the live system.
"""
import logging
import time
from datetime import datetime
from pathlib import Path

import config as C
from camera import CameraError, create_camera
from inspection import decision_engine as de
from inspection.component_matching import hungarian_match
from inspection.golden_reference import load_golden
from lighting import LedController
from storage import ImageLogger, ResultLogger
from vision.board_alignment import (NO_BOARD, UNKNOWN_BOARD, WRONG_SIDE, BoardAligner,
                                    Canvas, load_profile)
from vision.calibration import Undistorter
from vision.coordinate_extraction import detections_to_mm
from vision.preprocessing import preprocess_canvas
from vision.quality import check_quality

log = logging.getLogger(__name__)
SIDES = ("top", "bottom")


def make_canvas():
    return Canvas(C.BOARD_WIDTH_MM, C.BOARD_HEIGHT_MM, C.CANVAS_MARGIN_MM, C.PX_PER_MM)


def make_aligners(canvas, profile=None):
    profile = profile if profile is not None else load_profile(C.REFERENCES_DIR / "board_profile.json")
    out = {}
    for side in SIDES:
        und = Undistorter(C.CALIBRATION_DIR / C.CAMERAS[side]["calibration_file"])
        out[side] = BoardAligner(side, canvas, profile, C.ALIGN, und, C.REFERENCES_DIR)
    return out


class InspectionSystem:
    def __init__(self, simulate: bool = False, load_models: bool = True):
        self.simulate = simulate or C.SIMULATE
        self.canvas = make_canvas()
        self.aligners = make_aligners(self.canvas)
        self.cameras, self.detectors, self.golden = {}, {}, {}
        self.leds = None
        self.load_models = load_models
        self.image_logger = ImageLogger(C.JPEG_QUALITY)
        self.result_logger = ResultLogger(C.LOGS_DIR)
        self.counter = 0

    # ------------------------------------------------------------------ start-up
    def start(self, progress=lambda msg: None):
        """Open devices ONCE per session (opening a camera takes 1-2 s)."""
        progress("Starting LEDs...")
        self.leds = LedController(C.LIGHTING, simulate=self.simulate)
        for side in SIDES:
            progress(f"Opening {side} camera...")
            cam = create_camera(side, C.CAMERAS[side], simulate=self.simulate)
            cam.open()
            self.cameras[side] = cam
        for side in SIDES:
            gpath = C.REFERENCES_DIR / f"golden_{side}.json"
            if not gpath.exists():
                raise FileNotFoundError(f"{gpath} missing. Build it with "
                                        "tools/build_golden_reference.py")
            self.golden[side] = load_golden(gpath)
        if self.load_models:
            from vision.component_detection import Detector
            for side in SIDES:
                progress(f"Loading {side} model...")
                m = C.MODELS[side]
                det = Detector(C.MODELS_DIR / m["path"], m["imgsz"], m["classes"],
                               C.YOLO_IOU, C.YOLO_MAX_DET)
                det.warmup((self.canvas.h, self.canvas.w, 3))
                self.detectors[side] = det
        progress("Ready")

    def close(self):
        for cam in self.cameras.values():
            try:
                cam.close()
            except Exception:
                log.exception("camera close")
        if self.leds is not None:
            self.leds.all_off()
            self.leds.close()
        self.image_logger.flush()

    # ------------------------------------------------------------------ capture
    def capture_side(self, side):
        """LED on -> settle -> flush stale frames -> grab -> LED off -> quality."""
        last_reasons = []
        for attempt in range(C.CAMERA_RETRIES + 1):
            try:
                self.leds.light(side)
                time.sleep(C.LED_SETTLE_S)
                img = self.cameras[side].capture()
            finally:
                self.leds.all_off()
            ok, metrics, reasons = check_quality(img, C.QUALITY)
            if ok or self.simulate:
                return img, metrics
            last_reasons = reasons
            log.warning("%s capture attempt %d rejected: %s", side, attempt + 1, reasons)
        raise CameraError(f"{side} image rejected after {C.CAMERA_RETRIES + 1} attempts: "
                          + "; ".join(last_reasons))

    # ------------------------------------------------------------------ processing
    def process(self, raw: dict, detectors=None):
        """Everything after capture. raw = {"top": img, "bottom": img}."""
        detectors = detectors or self.detectors
        out = {"sides": {}, "timing": {}}
        t0 = time.perf_counter()
        aligned = {side: self.aligners[side].align(raw[side]) for side in SIDES}
        out["timing"]["align_s"] = round(time.perf_counter() - t0, 3)
        out["alignment"] = {s: {"status": a.status, "message": a.message,
                                "rotated_180": a.rotated_180,
                                "fiducials": f"{a.fiducials_found}/{a.fiducials_expected}",
                                "fiducial_rms_mm": a.fiducial_rms_mm,
                                "template_scores": a.template_scores}
                            for s, a in aligned.items()}
        out["aligned"] = aligned
        for side in SIDES:
            a = aligned[side]
            if a.status in (NO_BOARD, WRONG_SIDE, UNKNOWN_BOARD):
                out["state"] = a.status.upper()
                out["message"] = f"{side.upper()} camera: {a.message}"
                return out

        side_results, canvases = [], {}
        for side in SIDES:
            canvas = preprocess_canvas(aligned[side].canvas, C.PREPROCESS)
            canvases[side] = canvas
            t1 = time.perf_counter()
            dets = detectors[side].detect(canvas, conf=C.T_LOW)
            out["timing"][f"inference_ms_{side}"] = round((time.perf_counter() - t1) * 1000, 1)
            observed = detections_to_mm(dets, self.canvas.ppm, self.canvas.m)
            comps = self.golden[side]["components"]
            matches = hungarian_match(comps, observed, gate_factor=C.MATCH["gate_factor"],
                                      gate_min_mm=C.MATCH["gate_min_mm"],
                                      class_penalty=C.MATCH["class_penalty"])
            sr = de.evaluate_side(side, comps, observed, matches, C.T_HIGH,
                                  C.MATCH["duplicate_iou"], C.EXTRA_IS_FAIL,
                                  aligned[side].status if C.ALIGN["review_if_coarse"] else "ok")
            side_results.append(sr)
        out["state"] = "RESULT"
        out["verdict"] = de.combine(side_results)
        out["side_results"] = side_results
        out["canvases"] = canvases
        out["flagged"] = de.summary_lines(side_results)
        return out

    # ------------------------------------------------------------------ one board
    def inspect(self, door_closed: bool = True):
        t_start = time.perf_counter()
        self.counter += 1
        board_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{self.counter:04d}"
        folder = C.LOGS_DIR / datetime.now().strftime("%Y-%m-%d") / board_id
        if C.REQUIRE_DOOR_CLOSED and not door_closed:
            return {"state": "DOOR_OPEN", "message": "Close the chamber door, then press START.",
                    "board_id": board_id}
        raw, quality = {}, {}
        t_cap = time.perf_counter()
        try:
            for side in SIDES:
                raw[side], quality[side] = self.capture_side(side)
        except Exception as exc:          # camera failure must never crash the GUI
            log.exception("capture failed")
            return {"state": "ERROR", "message": f"Capture failed: {exc}", "board_id": board_id}
        capture_s = time.perf_counter() - t_cap

        out = self.process(raw)
        out.update(board_id=board_id, folder=folder, raw=raw, quality=quality)
        out["timing"]["capture_s"] = round(capture_s, 3)
        out["timing"]["total_s"] = round(time.perf_counter() - t_start, 3)
        self._log(out)
        return out

    def _log(self, out):
        folder = out["folder"]
        if C.SAVE_RAW_IMAGES:
            for side, img in out["raw"].items():
                self.image_logger.save(folder / f"raw_{side}.jpg", img)
        if out.get("state") != "RESULT":
            log.info("%s: %s", out["board_id"], out.get("message"))
            return
        from gui.overlay import draw_side
        out["overlays"] = {}
        for sr in out["side_results"]:
            ov = draw_side(out["canvases"][sr.side], sr, self.canvas.ppm, self.canvas.m)
            out["overlays"][sr.side] = ov
            self.image_logger.save(folder / f"overlay_{sr.side}.jpg", ov)
            if C.SAVE_CANVAS_IMAGES:
                self.image_logger.save(folder / f"canvas_{sr.side}.jpg", out["canvases"][sr.side])
        by_side = {sr.side: sr for sr in out["side_results"]}
        n_fail = sum(1 for sr in out["side_results"] for c in sr.components + sr.extras
                     if c.status in de.FAIL_STATUSES)
        n_rev = sum(1 for sr in out["side_results"] for c in sr.components + sr.extras
                    if c.status in de.REVIEW_STATUSES)
        record = {
            "board_id": out["board_id"], "timestamp": datetime.now().isoformat(timespec="seconds"),
            "verdict": out["verdict"], "operator_decision": "",
            "top_verdict": by_side["top"].verdict, "bottom_verdict": by_side["bottom"].verdict,
            "n_fail": n_fail, "n_review": n_rev, "flagged": " | ".join(out["flagged"]),
            "total_s": out["timing"]["total_s"], "capture_s": out["timing"]["capture_s"],
            "inference_ms_top": out["timing"].get("inference_ms_top"),
            "inference_ms_bottom": out["timing"].get("inference_ms_bottom"),
            "top_alignment": out["alignment"]["top"]["status"],
            "bottom_alignment": out["alignment"]["bottom"]["status"],
            "alignment": out["alignment"], "quality": out["quality"],
            "timing": out["timing"],
            "thresholds": {"T_LOW": C.T_LOW, "T_HIGH": C.T_HIGH},
            "sides": {sr.side: sr.to_dict() for sr in out["side_results"]},
        }
        self.result_logger.write(folder, record)
