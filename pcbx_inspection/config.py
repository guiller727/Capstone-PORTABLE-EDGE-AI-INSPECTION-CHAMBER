"""
config.py - SYSTEM settings for the PCB X inspection system (V2).

What lives where (V2):
  config.py                         hardware + pipeline defaults (this file)
  config/settings.json              values changed from the GUI Settings window
                                    (overrides a whitelist of keys below; optional)
  models/<profile>/metadata.json    the PCB profile: board size, sides, model files
  models/<profile>/golden_reference.json   expected components, tolerances, thresholds
  models/<profile>/board_profile.json      identification markers + fiducials (mounting holes)
  references/calibration/<camera>_camera.json   lens calibration per camera

Naming (kept from V1, see docs/PCB_IDENTIFICATION_AND_ORIENTATION.md):
  PCB SIDES   "top"    = Side A = FRONT (through-hole parts, "SHARP" silkscreen)
              "bottom" = Side B = BACK  (SMD parts, "T1" white block)
  CAMERAS     "upper"  = Camera Module 3 on CAM1, above the tray, looks down
              "lower"  = Camera Module 3 on CAM0, below the tray, looks up
A camera does NOT decide the side: every image is identified from the PCB's
own markings, so a board inserted flipped is still inspected correctly.

Units: millimetres (mm), seconds (s), microseconds (us), pixels (px).
Lines marked  # TUNE  must be measured on your chamber (see docs).
"""
import json
import logging
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_DIR / "models"            # one sub-folder per PCB profile
REFERENCES_DIR = PROJECT_DIR / "references"    # camera calibration (per camera)
CALIBRATION_DIR = REFERENCES_DIR / "calibration"
LOGS_DIR = PROJECT_DIR / "logs"
SETTINGS_FILE = PROJECT_DIR / "config" / "settings.json"

ACTIVE_PROFILE = "pcb_x"                       # folder name inside models/

SIDES = ("top", "bottom")
SIDE_LABELS = {"top": "FRONT - Side A", "bottom": "BACK - Side B"}
SIDE_SEARCH_ORDER = ("top", "bottom")          # front identifiers are tried first

# --------------------------------------------------------------------------
# Fallback board geometry - the active profile's metadata.json overrides these
# --------------------------------------------------------------------------
BOARD_NAME = "PCB X"
BOARD_WIDTH_MM = 115.0       # TUNE: measure with calipers (long edge)
BOARD_HEIGHT_MM = 45.0       # TUNE: measure with calipers (short edge)
CANVAS_MARGIN_MM = 2.5
PX_PER_MM = 10.0             # canvas scale -> 1200 x 500 px canvas

# --------------------------------------------------------------------------
# Inspection mode
#   "dual" : both cameras, ONE insertion. Upper and lower images are captured
#            one after the other (one light at a time). Recommended.
#   "flip" : ONE camera (FLIP_CAMERA). Capture, operator flips the board,
#            capture again. Use if only one camera is installed/working.
# --------------------------------------------------------------------------
INSPECTION_MODE = "dual"
FLIP_CAMERA = "upper"
ALLOW_FLIPPED_INSERTION = True   # dual mode: board upside-down in the tray is
                                 # inspected anyway (sides are identified per image)

# --------------------------------------------------------------------------
# Cameras.  backend: "picamera2" (CSI, Camera Module 3) | "uvc" (optional USB
# webcam fallback) | "file" (replays images - simulation / Windows development)
# --------------------------------------------------------------------------
_CM3_CONTROLS = {
    "ExposureTime": 8000,        # us  # TUNE so the board is bright but not clipped
    "AnalogueGain": 1.0,
    "AwbEnable": False,
    "ColourGains": (1.8, 1.6),   # (red, blue)  # TUNE with a grey card
    "AfMode": 0,                 # 0 = manual focus (fixed working distance)
    "LensPosition": 8.0,         # dioptres = 1 / distance_m (0.125 m -> 8.0)  # TUNE
}
CAMERAS = {
    "upper": {                   # above the tray, looks DOWN
        "backend": "picamera2",
        "camera_num": 1,         # CAM1 connector. Check with: rpicam-hello --list-cameras
        "width": 2304,           # Camera Module 3 2x2-binned mode (sharp, fast, low RAM)
        "height": 1296,
        "flush_frames": 2,       # frames thrown away after the LED switches on
        "led": "top",            # which LED strip lights this camera's view
        "picamera2": dict(_CM3_CONTROLS),
        "calibration_file": "upper_camera.json",
        "simulate_folder": "sim_images/upper",
        # --- only used if backend == "uvc" (optional USB webcam fallback) ---
        "device": "auto", "match": "EMEET", "fourcc": "MJPG", "fps": 30,
        "v4l2_controls": {"auto_exposure": 1, "exposure_time_absolute": 150, "gain": 0,
                          "white_balance_automatic": 0, "white_balance_temperature": 5000,
                          "focus_automatic_continuous": 0, "focus_absolute": 300,
                          "power_line_frequency": 2},
    },
    "lower": {                   # below the tray, looks UP
        "backend": "picamera2",
        "camera_num": 0,         # CAM0 connector
        "width": 2304,
        "height": 1296,
        "flush_frames": 2,
        "led": "bottom",
        "picamera2": dict(_CM3_CONTROLS),
        "calibration_file": "lower_camera.json",
        "simulate_folder": "sim_images/lower",
    },
}
CAMERA_ORDER = ("upper", "lower")   # sequential capture order in dual mode
CAMERA_RETRIES = 2                  # recapture attempts if the quality check fails

# --------------------------------------------------------------------------
# Lighting.  backend: "ws2812_spi" | "gpio_mosfet" | "dummy"
# --------------------------------------------------------------------------
LIGHTING = {
    "backend": "ws2812_spi",
    "spi_bus": 0,                  # SPI0 -> GPIO10 (physical pin 19)
    "spi_device": 0,
    "spi_hz": 6_400_000,
    # One data line, two strips chained: first top_count LEDs = top strip
    # (lights the UPPER camera's view), next bottom_count = bottom strip.
    "top_count": 24,               # TUNE to your strip
    "bottom_count": 24,
    "color_order": "GRB",          # WS2812B is GRB
    "top_rgb": (255, 255, 255),
    "bottom_rgb": (255, 255, 255),
    "brightness": 0.6,             # 0..1, keep < 0.8 to limit current/heat
    "top_gpio": 12,                # gpio_mosfet backend only
    "bottom_gpio": 13,
}
LED_SETTLE_S = 0.30                # wait after LED on before capturing  # TUNE
PREVIEW_FPS = 4                    # live preview rate in the GUI (keep low on a Pi)

# --------------------------------------------------------------------------
# Physical inputs (gpiozero, BCM numbering). Set a pin to None to disable.
# --------------------------------------------------------------------------
START_BUTTON_GPIO = 17             # physical pin 11, button to GND
DOOR_SWITCH_GPIO = 27              # physical pin 13, switch to GND when closed
STATUS_LED_GPIO = 22               # physical pin 15, optional indicator
REQUIRE_DOOR_CLOSED = True

# --------------------------------------------------------------------------
# Preprocessing (MUST be identical for dataset images and inspection)
# --------------------------------------------------------------------------
PREPROCESS = {"clahe": True, "clahe_clip": 2.0, "clahe_tiles": (8, 8), "gamma": 1.0}

QUALITY = {                        # TUNE from good captures
    "min_sharpness": 60.0,         # variance of Laplacian
    "min_mean": 40,
    "max_mean": 215,
    "max_saturated_frac": 0.02,
}

# --------------------------------------------------------------------------
# Board alignment + identification
# --------------------------------------------------------------------------
ALIGN = {
    "coarse_method": "outline",      # "outline" or "fixed" (homography stored in the
                                     # camera calibration file, see tools/build_board_profile.py)
    "outline_min_area_frac": 0.08,
    "outline_max_area_frac": 0.90,
    "aspect_tolerance": 0.15,
    "template_size": (360, 150),     # whole-board template (fallback identification)
    "min_template_score": 0.45,
    "min_score_margin": 0.05,
    "marker_min_score": 0.60,        # default for identification markers  # TUNE
    "marker_search_mm": 4.0,         # default search radius around a marker
    "orientation_margin": 0.08,      # 0 vs 180 deg scores closer than this -> ambiguous
    "fiducial_search_mm": 3.0,
    "fiducial_d_range_mm": (0.6, 5.0),  # mounting holes on PCB X are ~3-4 mm
    "min_fiducials": 2,
    "max_fiducial_rms_mm": 0.35,
    "review_if_coarse": True,
}

# --------------------------------------------------------------------------
# YOLO / matching. Thresholds per side live in golden_reference.json;
# these are only fallbacks.
# --------------------------------------------------------------------------
YOLO_IOU = 0.50
YOLO_MAX_DET = 300
PREFER_NCNN = True               # use <side>/best_ncnn_model if present, else best.pt
T_LOW = 0.25
T_HIGH = 0.60
MATCH = {"gate_factor": 3.0, "gate_min_mm": 1.5, "class_penalty": 2.0, "duplicate_iou": 0.45}
EXTRA_IS_FAIL = False            # PDF rule: extra component -> REVIEW

# Default tolerance per class (mm) used when BUILDING golden references.
# Final values must be agreed with the partner company (IPC-A-610 criteria).
DEFAULT_TOL_MM = {
    "resistor": 0.5, "smd_capacitor": 0.5, "diode": 0.5, "ic8": 0.6,
    "electrolytic_cap": 1.0, "film_capacitor": 1.0, "ceramic_capacitor": 1.0,
    "inductor": 1.0, "transformer": 1.5, "varistor": 1.0, "fuse": 1.0,
    "connector": 1.5,
}

# --------------------------------------------------------------------------
# Logging / GUI
# --------------------------------------------------------------------------
SAVE_RAW_IMAGES = True
SAVE_CANVAS_IMAGES = True
JPEG_QUALITY = 95
FULLSCREEN = True
WINDOW_SIZE = (1024, 600)
SIMULATE = False

# --------------------------------------------------------------------------
# GUI-editable overrides (config/settings.json). Only these keys may be
# overridden; values are type-checked so a bad file cannot break the program.
# --------------------------------------------------------------------------
OVERRIDABLE = {
    "ACTIVE_PROFILE": str, "INSPECTION_MODE": str, "FLIP_CAMERA": str,
    "ALLOW_FLIPPED_INSERTION": bool, "LED_SETTLE_S": float, "LED_BRIGHTNESS": float,
    "SAVE_RAW_IMAGES": bool, "REQUIRE_DOOR_CLOSED": bool,
}
_log = logging.getLogger(__name__)


def validate_override(key, value):
    """Return (ok, message). Used by the GUI before saving settings.json."""
    if key not in OVERRIDABLE:
        return False, f"{key} cannot be changed from settings.json"
    typ = OVERRIDABLE[key]
    if typ is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, typ):
        return False, f"{key} must be {typ.__name__}"
    if key == "INSPECTION_MODE" and value not in ("dual", "flip"):
        return False, "INSPECTION_MODE must be 'dual' or 'flip'"
    if key == "FLIP_CAMERA" and value not in CAMERAS:
        return False, f"FLIP_CAMERA must be one of {list(CAMERAS)}"
    if key == "LED_SETTLE_S" and not 0.0 <= value <= 3.0:
        return False, "LED_SETTLE_S must be 0..3 s"
    if key == "LED_BRIGHTNESS" and not 0.05 <= value <= 1.0:
        return False, "LED_BRIGHTNESS must be 0.05..1.0"
    if key == "ACTIVE_PROFILE" and not (MODELS_DIR / value / "metadata.json").exists():
        return False, f"profile '{value}' not found in models/"
    return True, "ok"


def apply_settings_file(path: Path = None):
    """Apply config/settings.json if it exists. Invalid entries are skipped."""
    path = Path(path or SETTINGS_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception as exc:          # broken file must not stop the appliance
        _log.error("Ignoring %s: %s", path, exc)
        return {}
    applied = {}
    for key, value in data.items():
        ok, msg = validate_override(key, value)
        if not ok:
            _log.warning("settings.json: %s", msg)
            continue
        if key == "LED_BRIGHTNESS":
            LIGHTING["brightness"] = float(value)
        else:
            globals()[key] = float(value) if OVERRIDABLE[key] is float else value
        applied[key] = value
    return applied


def save_settings_file(values: dict, path: Path = None):
    """Validate and write GUI settings atomically. Raises ValueError if invalid."""
    path = Path(path or SETTINGS_FILE)
    current = json.loads(path.read_text()) if path.exists() else {}
    for key, value in values.items():
        ok, msg = validate_override(key, value)
        if not ok:
            raise ValueError(msg)
        current[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2))
    tmp.replace(path)
    apply_settings_file(path)
    return current


apply_settings_file()
