"""
inspection/runner.py - the complete inspection sequence (V2).

DUAL mode (default; two Camera Module 3, one insertion):
    START
      |-- drawer closed?                               no -> DOOR_OPEN (no verdict)
      |-- capture UPPER camera (top LED only, settle, flush, grab, quality, retry)
      |-- capture LOWER camera (bottom LED only, ...)
      |-- for each image: undistort -> outline -> IDENTIFY side (front markers
      |   first, then back) -> orientation 0/90/180/270 corrected -> fine
      |   alignment on the mounting holes
      |-- assign images to sides (upper=front/lower=back normally; a board
      |   inserted upside-down is recognised and handled automatically)
      |-- per side: CLAHE -> YOLO (that side's model) -> mm -> Hungarian match
      |   with that side's golden reference -> rules -> side verdict
      |   (a side that cannot be inspected -> REVIEW with the reason)
      |-- board verdict = combine(front, back)  FAIL > REVIEW > PASS
      '-- overlays, CSV/JSON/JPEG logging in the background

FLIP mode (one camera): START -> capture + identify + inspect the side that
is up -> "Flip the board, press START" -> capture + inspect the other side ->
combine. Same rules, same records.

Captures are SEQUENTIAL even though the Pi 5 can stream both cameras at once:
only one light may be on per photo (light through holes and board edges
would otherwise reach the other camera), and sequential capture costs < 1 s.
Both cameras stay opened and started for the whole session.

`process(raw)` holds everything after capture and is used unchanged by
tools/run_offline.py and the tests (offline evaluation = live code).
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime

import config as C
from camera import CameraError, create_camera
from inspection import decision_engine as de
from inspection.component_matching import hungarian_match
from inspection.golden_reference import golden_hash, resolved_components, thresholds
from inspection.profile import ModelError, Profile, ProfileError
from inspection.golden_reference import GoldenError
from lighting import LedController
from storage import ImageLogger, ResultLogger
from vision.board_alignment import (AMBIGUOUS, NO_BOARD, UNCONFIGURED, UNKNOWN_BOARD,
                                    BoardAligner, Canvas)
from vision.calibration import Undistorter
from vision.coordinate_extraction import detections_to_mm
from vision.preprocessing import preprocess_canvas
from vision.quality import check_quality

log = logging.getLogger(__name__)
SIDES = C.SIDES


@dataclass
class Analysis:
    """One captured image after alignment/identification."""
    camera: str
    raw: object = None
    quality: dict = None
    align: object = None          # AlignResult
    error: str = None             # capture error text

    @property
    def side(self):
        return self.align.side if (self.align is not None and self.align.usable) else None


def make_canvas(profile: Profile = None):
    if profile is not None:
        w, h = profile.board_size
        ppm, m = profile.canvas_params(C.PX_PER_MM, C.CANVAS_MARGIN_MM)
        return Canvas(w, h, m, ppm)
    return Canvas(C.BOARD_WIDTH_MM, C.BOARD_HEIGHT_MM, C.CANVAS_MARGIN_MM, C.PX_PER_MM)


def make_aligners(canvas, board_profile, profile_dir, cameras=None):
    out = {}
    for cam in cameras or C.CAMERAS:
        und = Undistorter(C.CALIBRATION_DIR / C.CAMERAS[cam]["calibration_file"])
        fixed = und.extra.get("fixed_homography")
        out[cam] = BoardAligner(cam, canvas, board_profile, C.ALIGN, und, profile_dir,
                                fixed_H=fixed, order=C.SIDE_SEARCH_ORDER)
    return out


class InspectionSystem:
    def __init__(self, simulate: bool = False, load_models: bool = True, profile_name=None):
        self.simulate = simulate or C.SIMULATE
        self.load_models = load_models
        self.profile_name = profile_name or C.ACTIVE_PROFILE
        self.cameras, self.detectors = {}, {}
        self.leds = None
        self.image_logger = ImageLogger(C.JPEG_QUALITY)
        self.result_logger = ResultLogger(C.LOGS_DIR)
        self.counter = 0
        self.problems, self.ready = [], False
        self.flip_pending = None
        self.profile = self.golden = None
        self.board_profile = {}
        self.canvas = make_canvas()
        self.aligners = {}

    # ------------------------------------------------------------------ profile
    def load_profile(self, name=None):
        """(Re)load metadata, golden reference, board profile. Collects problems."""
        self.profile_name = name or self.profile_name
        problems = []
        try:
            self.profile = Profile(C.MODELS_DIR, self.profile_name)
        except ProfileError as exc:
            self.profile, self.golden = None, None
            return [str(exc)]
        self.canvas = make_canvas(self.profile)
        try:
            self.board_profile = self.profile.load_board_profile()
            if not self.board_profile:
                problems.append("board_profile.json missing - PCB side identification is "
                                "not configured (tools/build_board_profile.py)")
        except ProfileError as exc:
            self.board_profile = {}
            problems.append(str(exc))
        try:
            self.golden = self.profile.load_golden()
            for side in self.profile.sides():
                if side not in self.golden.get("sides", {}):
                    problems.append(f"golden reference has no {C.SIDE_LABELS[side]} section - "
                                    f"run tools/build_golden_reference.py --side {side}")
        except GoldenError as exc:
            self.golden = None
            problems.append(str(exc))
        self.aligners = make_aligners(self.canvas, self.board_profile, self.profile.dir)
        return problems

    def load_detectors(self, progress=lambda m: None):
        from vision.component_detection import Detector
        problems = []
        self.detectors = {}
        for side in self.profile.sides() if self.profile else []:
            try:
                path, fmt, imgsz = self.profile.model_info(side, C.PREFER_NCNN)
                progress(f"Loading {C.SIDE_LABELS[side]} model ({fmt})...")
                det = Detector(path, imgsz, self.profile.classes(side), C.YOLO_IOU, C.YOLO_MAX_DET)
                det.format = fmt
                det.warmup((self.canvas.h, self.canvas.w, 3))
                self.detectors[side] = det
            except Exception as exc:       # ModelError / ModelLoadError / anything
                problems.append(str(exc))
        return problems

    def needed_cameras(self):
        return [C.FLIP_CAMERA] if C.INSPECTION_MODE == "flip" else list(C.CAMERA_ORDER)

    # ------------------------------------------------------------------ start-up
    def start(self, progress=lambda msg: None):
        """Open devices ONCE per session. Never raises: problems are collected
        and shown in the GUI (system 'not ready')."""
        self.problems = []
        progress("Starting LEDs...")
        try:
            self.leds = LedController(C.LIGHTING, simulate=self.simulate)
        except Exception as exc:
            log.exception("LED init")
            self.problems.append(f"LEDs: {exc}")
            self.leds = LedController(C.LIGHTING, simulate=True)
        for cam in self.needed_cameras():
            if cam in self.cameras:
                continue
            progress(f"Opening {cam} camera...")
            try:
                c = create_camera(cam, C.CAMERAS[cam], simulate=self.simulate)
                c.open()
                self.cameras[cam] = c
            except Exception as exc:
                log.exception("camera %s", cam)
                self.problems.append(f"{cam} camera: {exc}")
        progress(f"Loading profile {self.profile_name}...")
        self.problems += self.load_profile()
        if self.load_models and self.profile is not None:
            self.problems += self.load_detectors(progress)
        self.ready = not self.problems
        progress("Ready" if self.ready else f"NOT READY: {len(self.problems)} problem(s)")
        return self.problems

    def reload(self, progress=lambda msg: None):
        """Apply changed settings/profile/golden without restarting the program."""
        for cam in [c for c in self.cameras if c not in self.needed_cameras()]:
            self.cameras.pop(cam).close()
        self.flip_pending = None
        return self.start(progress)

    def reload_golden(self):
        """Golden reference edited (GUI): reload only that file."""
        try:
            self.golden = self.profile.load_golden()
            return []
        except GoldenError as exc:
            return [str(exc)]

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
    def capture(self, cam):
        """LED on -> settle -> flush stale frames -> grab -> LED off -> quality."""
        if cam not in self.cameras:
            raise CameraError(f"{cam} camera is not available")
        last_reasons = []
        for attempt in range(C.CAMERA_RETRIES + 1):
            try:
                self.leds.light(C.CAMERAS[cam].get("led", "top"))
                time.sleep(C.LED_SETTLE_S)
                img = self.cameras[cam].capture()
            finally:
                self.leds.all_off()
            ok, metrics, reasons = check_quality(img, C.QUALITY)
            if ok or self.simulate:
                return img, metrics
            last_reasons = reasons
            log.warning("%s capture attempt %d rejected: %s", cam, attempt + 1, reasons)
        raise CameraError(f"{cam} image unusable after {C.CAMERA_RETRIES + 1} attempts: "
                          + "; ".join(last_reasons))

    def preview(self, cam):
        """Low-rate live preview frame (LED of that camera on while previewing)."""
        self.leds.light(C.CAMERAS[cam].get("led", "top"))
        return self.cameras[cam].capture(fresh=False)

    def analyze(self, cam, raw, expected_side=None):
        if raw is None:
            return Analysis(cam, error="no image")
        return Analysis(cam, raw=raw, align=self.aligners[cam].align(raw, expected_side))

    # ------------------------------------------------------------------ one side
    def inspect_side(self, side, a: Analysis):
        """Detection + matching + rules for one identified side."""
        if self.golden is None:
            return de.review_side(side, "golden reference not loaded", camera=a.camera), None, 0
        if not self.golden["sides"].get(side, {}).get("components"):
            return de.review_side(side, "no golden reference for this side",
                                  "run tools/build_golden_reference.py", camera=a.camera), None, 0
        det = self.detectors.get(side)
        if det is None:
            return de.review_side(side, de.R_MODEL, camera=a.camera), None, 0
        canvas = preprocess_canvas(a.align.canvas, C.PREPROCESS)
        t_low, t_high = thresholds(self.golden, side, (C.T_LOW, C.T_HIGH))
        t0 = time.perf_counter()
        dets = det.detect(canvas, conf=t_low)
        ms = (time.perf_counter() - t0) * 1000
        observed = detections_to_mm(dets, self.canvas.ppm, self.canvas.m)
        comps = resolved_components(self.golden["sides"].get(side, {}))
        matches = hungarian_match(comps, observed, gate_factor=C.MATCH["gate_factor"],
                                  gate_min_mm=C.MATCH["gate_min_mm"],
                                  class_penalty=C.MATCH["class_penalty"])
        sr = de.evaluate_side(side, comps, observed, matches, t_high, C.MATCH["duplicate_iou"],
                              C.EXTRA_IS_FAIL,
                              a.align.status if C.ALIGN["review_if_coarse"] else "ok",
                              camera=a.camera)
        return sr, canvas, round(ms, 1)

    @staticmethod
    def _reason(a: Analysis):
        """Why an image could not be used for a side (S2 reason + detail)."""
        if a is None:
            return de.R_NOT_CAPTURED, ""
        if a.error:
            return de.R_CAPTURE, a.error
        st = a.align.status
        if st == AMBIGUOUS:
            return de.R_AMBIGUOUS_ORIENT, a.align.message
        if st in (UNKNOWN_BOARD, UNCONFIGURED):
            return de.R_NOT_IDENTIFIED, a.align.message
        if st == NO_BOARD:
            return de.R_NOT_IDENTIFIED, f"{a.camera} camera: {a.align.message}"
        return de.R_NOT_IDENTIFIED, a.align.message

    def finalize(self, analyses, notes=None):
        """analyses: list of Analysis. Assigns them to sides and builds the result."""
        out = {"state": "RESULT", "timing": {}, "notes": list(notes or []),
               "side_results": {}, "canvases": {}, "side_info": {}}
        claims = {}
        for a in analyses:
            if a.side:
                claims.setdefault(a.side, []).append(a)
        conflict = {s for s, lst in claims.items() if len(lst) > 1}
        used = set()
        sides = self.profile.sides() if self.profile else list(SIDES)
        for side in sides:
            lst = claims.get(side, [])
            if side in conflict:
                cams = " and ".join(x.camera for x in lst)
                sr = de.review_side(side, de.R_CONFLICT, f"{cams} cameras both see the {side} side")
                used.update(id(x) for x in lst)
                a = lst[0]
            elif lst:
                a = lst[0]
                used.add(id(a))
                sr, canvas, ms = self.inspect_side(side, a)
                if canvas is not None:
                    out["canvases"][side] = canvas
                out["timing"][f"inference_ms_{side}"] = ms
            else:
                leftovers = [x for x in analyses if id(x) not in used and not x.side]
                a = leftovers[0] if leftovers else None
                if a is not None:
                    used.add(id(a))
                reason, detail = self._reason(a)
                sr = de.review_side(side, reason, detail, camera=a.camera if a else None)
            out["side_results"][side] = sr
            if a is not None and a.align is not None:
                al = a.align
                out["side_info"][side] = {
                    "camera": a.camera, "status": al.status, "message": al.message,
                    "identification": (al.identification or {}).get("message", ""),
                    "id_method": (al.identification or {}).get("method"),
                    "rotation_deg": al.rotation_deg, "rotated_180": al.rotated_180,
                    "fiducials": f"{al.fiducials_found}/{al.fiducials_expected}",
                    "fiducial_rms_mm": al.fiducial_rms_mm}
            elif a is not None:
                out["side_info"][side] = {"camera": a.camera, "status": "capture_error",
                                          "message": a.error}
        results = [out["side_results"][s] for s in sides]
        out["verdict"] = de.combine(results)
        out["flagged"] = de.summary_lines(results, labels=C.SIDE_LABELS)
        return out

    def process(self, raw: dict, errors: dict = None):
        """DUAL mode: raw = {"upper": img or None, "lower": img or None};
        errors = {camera: capture error text} for failed captures."""
        t0 = time.perf_counter()
        analyses = [self.analyze(cam, raw.get(cam)) for cam in C.CAMERA_ORDER if cam in raw]
        for a in analyses:
            if (errors or {}).get(a.camera):
                a.error = errors[a.camera]
        align_s = time.perf_counter() - t0
        if analyses and all(a.align is not None and a.align.status == NO_BOARD for a in analyses):
            return {"state": "NO_BOARD", "timing": {"align_s": round(align_s, 3)},
                    "message": "No board detected by any camera - insert PCB X and close the "
                               "drawer.", "analyses": analyses}
        notes = []
        sides = {a.camera: a.side for a in analyses}
        if sides.get("upper") == "bottom" or sides.get("lower") == "top":
            if not C.ALLOW_FLIPPED_INSERTION:
                return {"state": "WRONG_SIDE", "timing": {"align_s": round(align_s, 3)},
                        "message": "Board is upside-down in the tray - flip it over.",
                        "analyses": analyses}
            notes.append("Board inserted flipped (back side up) - sides identified from the "
                         "markings and inspected normally.")
        out = self.finalize(analyses, notes)
        out["timing"]["align_s"] = round(align_s, 3)
        out["analyses"] = analyses
        return out

    # ------------------------------------------------------------------ one board
    def _new_ids(self):
        self.counter += 1
        now = datetime.now()
        board_id = now.strftime("%Y%m%d_%H%M%S") + f"_{self.counter:04d}"
        return board_id, C.LOGS_DIR / now.strftime("%Y-%m-%d") / board_id

    def inspect(self, door_closed: bool = True, progress=lambda m: None):
        if not self.ready:
            return {"state": "NOT_READY", "message": "; ".join(self.problems)[:400]}
        if C.REQUIRE_DOOR_CLOSED and not door_closed:
            return {"state": "DOOR_OPEN", "message": "Close the chamber door, then press START."}
        if C.INSPECTION_MODE == "flip":
            return self._inspect_flip_step(progress)
        t_start = time.perf_counter()
        board_id, folder = self._new_ids()
        raw, quality, errors = {}, {}, {}
        for cam in C.CAMERA_ORDER:
            progress(f"Capturing {cam} camera...")
            try:
                raw[cam], quality[cam] = self.capture(cam)
            except Exception as exc:         # capture failure -> that side REVIEW
                log.exception("capture %s", cam)
                raw[cam], errors[cam] = None, str(exc)
        capture_s = time.perf_counter() - t_start
        progress("Identifying sides and aligning...")
        out = self.process(raw, errors)
        out.update(board_id=board_id, folder=folder, raw=raw, quality=quality, mode="dual")
        out.setdefault("timing", {})
        out["timing"]["capture_s"] = round(capture_s, 3)
        out["timing"]["total_s"] = round(time.perf_counter() - t_start, 3)
        self._log(out)
        return out

    # ------------------------------------------------------------------ flip mode
    def _inspect_flip_step(self, progress):
        cam = C.FLIP_CAMERA
        progress(f"Capturing ({cam} camera)...")
        try:
            img, q = self.capture(cam)
        except Exception as exc:
            return {"state": "ERROR", "message": f"Capture failed: {exc}. Press START to retry "
                                                 "or FINISH to record this board as REVIEW."}
        progress("Identifying side and aligning...")
        a = self.analyze(cam, img)
        a.quality = q
        if a.align.status == NO_BOARD:
            return {"state": "NO_BOARD", "message": a.align.message}
        first = self.flip_pending
        if first is None:
            board_id, folder = self._new_ids()
            self.flip_pending = {"analyses": [a], "board_id": board_id, "folder": folder,
                                 "t0": time.perf_counter()}
            part = self.finalize([a])
            done = [s for s in part["side_results"] if part["side_results"][s].inspected]
            label = C.SIDE_LABELS[done[0]] if done else "Side not identified"
            part.update(state="FLIP_PROMPT", board_id=board_id,
                        message=f"{label}: {part['side_results'][done[0]].verdict if done else 'REVIEW'}."
                                " Flip the board over and press START.")
            return part
        prev = first["analyses"][0]
        if a.side and prev.side and a.side == prev.side:
            return {"state": "SAME_SIDE", "message": f"The {C.SIDE_LABELS[a.side]} is facing the "
                    "camera again - flip the board over and press START."}
        first["analyses"].append(a)
        return self.finish_flip()

    def finish_flip(self):
        """Complete a flip-mode board (also used by the GUI's FINISH button:
        any side not captured is recorded as REVIEW)."""
        pend, self.flip_pending = self.flip_pending, None
        if pend is None:
            return {"state": "IDLE", "message": "Nothing to finish."}
        out = self.finalize(pend["analyses"])
        out.update(board_id=pend["board_id"], folder=pend["folder"], mode="flip",
                   raw={f"{a.camera}_{i + 1}": a.raw for i, a in enumerate(pend["analyses"])},
                   quality={f"{a.camera}_{i + 1}": a.quality for i, a in enumerate(pend["analyses"])})
        out["timing"]["total_s"] = round(time.perf_counter() - pend["t0"], 3)
        self._log(out)
        return out

    def cancel_flip(self):
        self.flip_pending = None

    # ------------------------------------------------------------------ logging
    def _log(self, out):
        folder = out["folder"]
        if C.SAVE_RAW_IMAGES:
            for name, img in (out.get("raw") or {}).items():
                if img is not None:
                    self.image_logger.save(folder / f"raw_{name}.jpg", img)
        if out.get("state") != "RESULT":
            log.info("%s: %s", out.get("board_id"), out.get("message"))
            return
        from gui.overlay import draw_side
        out["overlays"] = {}
        for side, sr in out["side_results"].items():
            if side in out["canvases"]:
                ov = draw_side(out["canvases"][side], sr, self.canvas.ppm, self.canvas.m)
                out["overlays"][side] = ov
                self.image_logger.save(folder / f"overlay_{side}.jpg", ov)
                if C.SAVE_CANVAS_IMAGES:
                    self.image_logger.save(folder / f"canvas_{side}.jpg", out["canvases"][side])
        srs = out["side_results"]
        n_fail = sum(1 for sr in srs.values() for c in sr.components + sr.extras
                     if c.status in de.FAIL_STATUSES)
        n_rev = sum(1 for sr in srs.values() for c in sr.components + sr.extras
                    if c.status in de.REVIEW_STATUSES) + sum(len(sr.flags) for sr in srs.values())
        info = out.get("side_info", {})
        record = {
            "board_id": out["board_id"], "timestamp": datetime.now().isoformat(timespec="seconds"),
            "verdict": out["verdict"], "operator_decision": "",
            "top_verdict": srs.get("top").verdict if "top" in srs else "",
            "bottom_verdict": srs.get("bottom").verdict if "bottom" in srs else "",
            "n_fail": n_fail, "n_review": n_rev, "flagged": " | ".join(out["flagged"]),
            "total_s": out["timing"].get("total_s"), "capture_s": out["timing"].get("capture_s"),
            "inference_ms_top": out["timing"].get("inference_ms_top"),
            "inference_ms_bottom": out["timing"].get("inference_ms_bottom"),
            "top_alignment": info.get("top", {}).get("status", ""),
            "bottom_alignment": info.get("bottom", {}).get("status", ""),
            "top_camera": info.get("top", {}).get("camera", ""),
            "bottom_camera": info.get("bottom", {}).get("camera", ""),
            "mode": out.get("mode", C.INSPECTION_MODE), "profile": self.profile_name,
            "golden_revision": (self.golden or {}).get("revision", ""),
            "golden_hash": golden_hash(self.golden) if self.golden else "",
            "notes": " | ".join(out.get("notes", [])),
            "side_info": info, "quality": out.get("quality"), "timing": out["timing"],
            "sides": {s: sr.to_dict() for s, sr in srs.items()},
        }
        self.result_logger.write(folder, record)
