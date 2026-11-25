#!/usr/bin/env python3
"""
tools/test_leds.py - Stage 3 test for the lights.

  python tools/test_leds.py            # top 2 s, bottom 2 s, off, 3x blink
  python tools/test_leds.py --interactive

PASS criteria:
  * only the TOP strip lights when "top" is selected, only BOTTOM for "bottom"
  * every LED is white (no green/red tint -> wrong color_order or bad data level)
  * no flicker, no random colours on the last LEDs (-> level shifter / ground)
  * LEDs are OFF after the program exits
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C  # noqa: E402
from lighting import LedController  # noqa: E402
from lighting.led_controller import blink_test  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interactive", action="store_true")
    args = ap.parse_args()
    print(f"Backend: {C.LIGHTING['backend']}  top={C.LIGHTING['top_count']} "
          f"bottom={C.LIGHTING['bottom_count']} LEDs")
    with LedController(C.LIGHTING) as leds:
        if args.interactive:
            print("Commands: t = top, b = bottom, a = both, o = off, q = quit")
            while True:
                c = input("> ").strip().lower()
                if c == "q":
                    break
                {"t": leds.top_on, "b": leds.bottom_on, "a": leds.both_on,
                 "o": leds.all_off}.get(c, lambda: print("?"))()
        else:
            print("TOP on"); leds.top_on(); time.sleep(2)
            print("BOTTOM on"); leds.bottom_on(); time.sleep(2)
            print("OFF"); leds.all_off(); time.sleep(1)
            print("Blink x3"); blink_test(leds)
            # timing of one update (should be a few ms)
            t0 = time.perf_counter()
            for _ in range(20):
                leds.top_on(); leds.all_off()
            print(f"Average switch time: {(time.perf_counter() - t0) / 40 * 1000:.1f} ms")
    print("Done - LEDs should now be OFF")


if __name__ == "__main__":
    main()
