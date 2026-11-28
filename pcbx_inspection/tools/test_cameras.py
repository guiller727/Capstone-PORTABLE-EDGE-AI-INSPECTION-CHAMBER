#!/usr/bin/env python3
"""
tools/test_cameras.py - Stage 2/4 test: open cameras, check locked settings,
measure stability, find the best focus.

Examples
  python tools/test_cameras.py --list                    # which CSI cameras libcamera sees
  python tools/test_cameras.py                           # both cameras, 10 captures each
  python tools/test_cameras.py --camera lower --focus-sweep 4 14 0.5
  python tools/test_cameras.py --both-streaming          # open BOTH cameras at once (Pi 5 check)

PASS criteria (Stage 2):
  * both cameras open and deliver the configured resolution
  * over 10 captures: brightness std < 2.0 and sharpness CV < 5 %
    (if it drifts, auto-exposure / auto-focus is still active)
  * capture time per side < 1.0 s
"""
import argparse
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

import config as C  # noqa: E402
from camera import create_camera  # noqa: E402
from lighting import LedController  # noqa: E402
from vision.quality import image_metrics  # noqa: E402

OUT = C.PROJECT_DIR / "test_output" / "cameras"


def stability(cam, leds, side, n):
    led = C.CAMERAS[side].get("led", "top")
    means, sharp, times = [], [], []
    for i in range(n):
        t0 = time.perf_counter()
        leds.light(led)
        time.sleep(C.LED_SETTLE_S)
        img = cam.capture()
        leds.all_off()
        times.append(time.perf_counter() - t0)
        m = image_metrics(img)
        means.append(m["mean"])
        sharp.append(m["sharpness"])
        if i == 0:
            OUT.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(OUT / f"{side}_sample.jpg"), img)
            print(f"  resolution {img.shape[1]}x{img.shape[0]}  saved {OUT / f'{side}_sample.jpg'}")
    cv_sharp = st.pstdev(sharp) / st.mean(sharp) * 100 if st.mean(sharp) else 0
    print(f"  brightness mean {st.mean(means):.1f}  std {st.pstdev(means):.2f}   "
          f"(target std < 2.0)")
    print(f"  sharpness  mean {st.mean(sharp):.1f}  CV {cv_sharp:.1f} %   (target CV < 5 %)")
    print(f"  capture time mean {st.mean(times):.2f} s  max {max(times):.2f} s (target < 1.0 s)")
    ok = st.pstdev(means) < 2.0 and cv_sharp < 5 and max(times) < 1.0
    print("  RESULT:", "PASS" if ok else "CHECK SETTINGS")


def focus_sweep(cam, leds, side, start, stop, step):
    """Capture at several focus settings and report the sharpest."""
    cfg = C.CAMERAS[side]
    results = []
    v = start
    while v <= stop + 1e-9:
        if cfg["backend"] == "picamera2":
            cam.cam.set_controls({"AfMode": 0, "LensPosition": float(v)})
            time.sleep(0.5)
        else:
            from camera.uvc_camera import apply_v4l2_controls
            apply_v4l2_controls(cam.device, {"focus_automatic_continuous": 0,
                                             "focus_absolute": int(v)})
            time.sleep(0.7)
        leds.light(cfg.get("led", "top"))
        time.sleep(C.LED_SETTLE_S)
        img = cam.capture()
        leds.all_off()
        s = image_metrics(img, centre_frac=0.4)["sharpness"]
        results.append((v, s))
        print(f"  focus {v:8.2f}  sharpness {s:10.1f}")
        v += step
    best = max(results, key=lambda r: r[1])
    key = "LensPosition" if cfg["backend"] == "picamera2" else "focus_absolute"
    print(f"\n  BEST {key} = {best[0]}  -> put this value in config.py CAMERAS['{side}']")


def list_cameras():
    from camera.picam_camera import list_csi_cameras
    info = list_csi_cameras()
    if not info:
        print("No CSI cameras found (or picamera2 not installed). Check cables, then run:\n"
              "  rpicam-hello --list-cameras")
    for i, c in enumerate(info):
        print(f"  camera_num {i}: model={c.get('Model')}  location={c.get('Location')}  "
              f"id={c.get('Id')}")
    for name, cfg in C.CAMERAS.items():
        print(f"  config: {name:5} -> backend={cfg['backend']} camera_num={cfg.get('camera_num')}")


def both_streaming(n=5):
    """Open and start BOTH cameras simultaneously, grab alternately (Pi 5 dual-CSI check)."""
    cams = {}
    try:
        for name in C.CAMERA_ORDER:
            cams[name] = create_camera(name, C.CAMERAS[name])
            cams[name].open()
        print("Both cameras opened and streaming at the same time.")
        for i in range(n):
            for name, cam in cams.items():
                t0 = time.perf_counter()
                img = cam.capture()
                print(f"  {name}: {img.shape[1]}x{img.shape[0]} in {time.perf_counter() - t0:.2f} s")
        print("RESULT: PASS (both cameras usable in one session)")
    finally:
        for cam in cams.values():
            cam.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", choices=list(C.CAMERAS) + ["both"], default="both")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--list", action="store_true", help="list detected cameras")
    ap.add_argument("--both-streaming", action="store_true")
    ap.add_argument("--focus-sweep", nargs=3, type=float, metavar=("START", "STOP", "STEP"))
    args = ap.parse_args()
    if args.list:
        list_cameras()
        return
    if args.both_streaming:
        both_streaming()
        return
    sides = list(C.CAMERA_ORDER) if args.camera == "both" else [args.camera]
    with LedController(C.LIGHTING) as leds:
        for side in sides:
            print(f"\n=== {side.upper()} camera: {C.CAMERAS[side]['backend']} ===")
            cam = create_camera(side, C.CAMERAS[side])
            t0 = time.perf_counter()
            cam.open()
            print(f"  opened in {time.perf_counter() - t0:.1f} s")
            try:
                if args.focus_sweep:
                    focus_sweep(cam, leds, side, *args.focus_sweep)
                else:
                    stability(cam, leds, side, args.n)
            finally:
                cam.close()


if __name__ == "__main__":
    main()
