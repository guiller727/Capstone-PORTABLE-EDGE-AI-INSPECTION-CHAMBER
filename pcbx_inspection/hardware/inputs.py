"""
hardware/inputs.py - physical START button, door switch and status LED.

Uses gpiozero (pre-installed on Raspberry Pi OS; works on the Pi 5 through
the lgpio backend). RPi.GPIO does NOT work on the Pi 5.

Wiring (internal pull-ups are used, so no resistors are needed):
  START button : GPIO17 (pin 11) ---[button]--- GND
  Door switch  : GPIO27 (pin 13) ---[switch closed when door shut]--- GND
  Status LED   : GPIO22 (pin 15) ---[330 ohm]---|>|--- GND
"""
import logging

log = logging.getLogger(__name__)


class Inputs:
    def __init__(self, start_gpio=None, door_gpio=None, led_gpio=None,
                 simulate: bool = False):
        self.simulate = simulate
        self.button = self.door = self.led = None
        if simulate:
            return
        try:
            from gpiozero import Button, LED
        except ImportError:
            log.warning("gpiozero not available - physical inputs disabled")
            self.simulate = True
            return
        if start_gpio is not None:
            self.button = Button(start_gpio, pull_up=True, bounce_time=0.05)
        if door_gpio is not None:
            self.door = Button(door_gpio, pull_up=True, bounce_time=0.05)
        if led_gpio is not None:
            self.led = LED(led_gpio)

    def on_start(self, callback):
        """Call `callback()` when the physical START button is pressed."""
        if self.button is not None:
            self.button.when_pressed = lambda: callback()

    def door_closed(self) -> bool:
        if self.door is None:
            return True          # no switch fitted -> assume closed
        return bool(self.door.is_pressed)

    def set_status_led(self, state: str):
        """state: 'ready' (on), 'busy' (blink), 'off'."""
        if self.led is None:
            return
        if state == "ready":
            self.led.on()
        elif state == "busy":
            self.led.blink(on_time=0.15, off_time=0.15)
        else:
            self.led.off()

    def close(self):
        for dev in (self.button, self.door, self.led):
            if dev is not None:
                dev.close()
