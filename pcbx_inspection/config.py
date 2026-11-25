"""
config.py - ALL tunable settings for the PCB X inspection system live here.

Edit this file, not the modules. Every value marked  # TUNE  must be measured
or tuned on YOUR chamber during the stage tests (docs/C_Pi_Software_Roadmap.md).

Units: millimetres (mm), seconds (s), microseconds (us), pixels (px).
"""
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_DIR / "models"
REFERENCES_DIR = PROJECT_DIR / "references"
CALIBRATION_DIR = PROJECT_DIR / "references" / "calibration"
LOGS_DIR = PROJECT_DIR / "logs"

# --------------------------------------------------------------------------
# Board geometry and the "canvas" (the straightened, cropped board image)
# --------------------------------------------------------------------------
BOARD_NAME = "PCB X"
BOARD_WIDTH_MM = 115.0       # TUNE: measure with calipers (long edge)
BOARD_HEIGHT_MM = 45.0       # TUNE: measure with calipers (short edge)
CANVAS_MARGIN_MM = 2.5       # border kept around the board in the canvas
PX_PER_MM = 10.0             # canvas scale. 10 px/mm -> 1200 x 500 px canvas

# Derived (do not edit)
CANVAS_W = int(round((BOARD_WIDTH_MM + 2 * CANVAS_MARGIN_MM) * PX_PER_MM))
CANVAS_H = int(round((BOARD_HEIGHT_MM + 2 * CANVAS_MARGIN_MM) * PX_PER_MM))

# --------------------------------------------------------------------------
# Cameras.  backend: "picamera2" (CSI camera) | "uvc" (USB webcam) | "file"
# "file" replays images from a folder (simulation / Windows development).
# --------------------------------------------------------------------------
CAMERAS = {
    "top": {                       # sees Side A (through-hole parts)
        # FINAL CHOICE: Raspberry Pi Camera Module 3 (standard) on CAM1.
        # (USB webcam option kept below: set backend "uvc" to use it instead.)
        "backend": "picamera2",
        "camera_num": 1,           # CAM1 port
        "width": 2304,             # CM3 2x2-binned mode  # TUNE in Stage 2
        "height": 1296,
        "flush_frames": 2,         # frames thrown away after LED switch-on
        "picamera2": {
            "ExposureTime": 8000,      # us  # TUNE
            "AnalogueGain": 1.0,
            "AwbEnable": False,
            "ColourGains": (1.8, 1.6), # (red, blue)  # TUNE with a grey card
            "AfMode": 0,               # 0 = manual focus
            "LensPosition": 8.0,       # dioptres = 1 / distance_in_m  # TUNE
        },
        # --- used only if backend == "uvc" (USB webcam alternative) ---
        "device": "auto",          # "auto" = /dev/v4l/by-id/*<match>*, or a path
        "match": "EMEET",
        "fourcc": "MJPG",
        "fps": 30,
        "v4l2_controls": {
            "auto_exposure": 1, "exposure_time_absolute": 150, "gain": 0,
            "white_balance_automatic": 0, "white_balance_temperature": 5000,
            "focus_automatic_continuous": 0, "focus_absolute": 300,
            "power_line_frequency": 2,
        },
        "calibration_file": "top_camera.json",
        "simulate_folder": "sim_images/top",
    },
    "bottom": {                    # sees Side B (SMD parts)
        "backend": "picamera2",
        "camera_num": 0,           # 0 = CAM0 port, 1 = CAM1 port
        # FINAL CHOICE: Raspberry Pi Camera Module 3 (standard) on CAM0.
        # 2x2-binned mode is sharper per pixel, faster and uses less RAM.
        # Use the full mode (4608x2592 / 4656x3496) only if you need >16 px/mm.
        "width": 2304,             # TUNE in Stage 2
        "height": 1296,
        "flush_frames": 2,
        "picamera2": {
            "ExposureTime": 8000,      # us  # TUNE so the board is not clipped
            "AnalogueGain": 1.0,
            "AwbEnable": False,
            "ColourGains": (1.8, 1.6), # (red, blue)  # TUNE with a grey card
            "AfMode": 0,               # 0 = manual focus
            "LensPosition": 8.0,       # dioptres = 1 / distance_in_m  # TUNE
        },
        "calibration_file": "bottom_camera.json",
        "simulate_folder": "sim_images/bottom",
    },
}
CAMERA_RETRIES = 2                 # recapture attempts if quality check fails

# --------------------------------------------------------------------------
# Lighting.  backend: "ws2812_spi" | "gpio_mosfet" | "dummy"
# --------------------------------------------------------------------------
LIGHTING = {
    "backend": "ws2812_spi",
    "spi_bus": 0,                  # SPI0 -> GPIO10 (physical pin 19)
    "spi_device": 0,
    "spi_hz": 6_400_000,
    # One data line, two strips chained: first TOP_COUNT LEDs = top strip,
    # next BOTTOM_COUNT LEDs = bottom strip.
    "top_count": 24,               # TUNE to your strip
    "bottom_count": 24,            # TUNE to your strip
    "color_order": "GRB",          # WS2812B is GRB
    "top_rgb": (255, 255, 255),
    "bottom_rgb": (255, 255, 255),
    "brightness": 0.6,             # 0..1, keep < 0.8 to limit current/heat
    # gpio_mosfet backend (plain white LED strips switched by MOSFETs):
    "top_gpio": 12,
    "bottom_gpio": 13,
}
LED_SETTLE_S = 0.30                # wait after LED on before capturing # TUNE

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
PREPROCESS = {
    "clahe": True,
    "clahe_clip": 2.0,
    "clahe_tiles": (8, 8),
    "gamma": 1.0,                  # 1.0 = off. Use >1 to brighten only if needed
}

# Image quality gate (on the raw image centre). # TUNE from golden captures
QUALITY = {
    "min_sharpness": 60.0,         # variance of Laplacian
    "min_mean": 40,                # 0..255
    "max_mean": 215,
    "max_saturated_frac": 0.02,    # fraction of pixels >= 250
}

# --------------------------------------------------------------------------
# Board alignment
# --------------------------------------------------------------------------
ALIGN = {
    # "outline": find the board edge in every image (default).
    # "fixed":   use a homography saved by tools/build_board_profile.py
    #            (works when the board edge is hard to see).
    "coarse_method": "outline",
    "outline_min_area_frac": 0.08,  # board must cover >= 8% of the image
    "outline_max_area_frac": 0.90,
    "aspect_tolerance": 0.15,        # allowed deviation of long/short ratio
    "template_size": (360, 150),     # downscaled size for side/orientation check
    "min_template_score": 0.45,      # below this -> "not PCB X"   # TUNE
    "min_score_margin": 0.05,        # best must beat 2nd best by this
    "fiducial_search_mm": 3.0,       # search radius around expected fiducial
    "min_fiducials": 2,              # need >= 2 for fine alignment
    "max_fiducial_rms_mm": 0.35,     # larger residual -> alignment "coarse"
    "review_if_coarse": True,        # coarse-only alignment can't give PASS
}

# --------------------------------------------------------------------------
# YOLO models and inspection thresholds
# --------------------------------------------------------------------------
MODELS = {
    "top": {
        "path": "top_best_ncnn_model",       # folder inside models/
        "imgsz": (288, 640),                 # (h, w) = export size
        "classes": ["electrolytic_cap", "inductor", "transformer", "varistor",
                    "fuse", "terminal_block", "connector"],
    },
    "bottom": {
        "path": "bottom_best_ncnn_model",
        "imgsz": (512, 1216),
        "classes": ["resistor", "smd_capacitor", "diode", "ic8"],
    },
}
YOLO_IOU = 0.50
YOLO_MAX_DET = 300

T_LOW = 0.25     # detections below this are ignored completely   # TUNE on val
T_HIGH = 0.60    # detections below this are "uncertain" (REVIEW)  # TUNE on val

# Matching (golden reference vs detections)
MATCH = {
    "gate_factor": 3.0,          # search radius = max(gate_factor*tol, gate_min)
    "gate_min_mm": 1.5,
    "class_penalty": 2.0,        # extra cost (in tolerance units) for wrong class
    "duplicate_iou": 0.45,       # unmatched box overlapping a matched one = duplicate
}
EXTRA_IS_FAIL = False            # PDF rule: extra component -> REVIEW

# Default position tolerance per class (mm) when building golden references.
# Final values must be agreed with the partner company (IPC-A-610 criteria).
DEFAULT_TOL_MM = {
    "resistor": 0.5, "smd_capacitor": 0.5, "diode": 0.5, "ic8": 0.6,
    "electrolytic_cap": 1.0, "inductor": 1.0, "transformer": 1.5,
    "varistor": 1.0, "fuse": 1.0, "terminal_block": 1.5, "connector": 1.5,
}

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
SAVE_RAW_IMAGES = True           # raw camera frames (large). Needed for retraining.
SAVE_CANVAS_IMAGES = True        # aligned canvases (small) - always recommended
JPEG_QUALITY = 95

# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
FULLSCREEN = True
WINDOW_SIZE = (1024, 600)        # used when FULLSCREEN is False
SIMULATE = False                 # True = no cameras/LEDs/GPIO (or use --simulate)
