"""
lighting/led_controller.py - switch the top / bottom lights.

Backends
--------
ws2812_spi  : WS2812B strips driven from SPI0 MOSI (GPIO10, pin 19).
              rpi_ws281x's PWM/DMA method does not work the same way on the
              Pi 5 (RP1 chip), so we generate the WS2812 waveform with SPI.
gpio_mosfet : two plain white LED strips, each switched by a logic-level
              MOSFET from a GPIO pin (simplest, most robust alternative).
dummy       : prints only. Used in --simulate mode and on Windows.

How the SPI trick works
-----------------------
At 6.4 MHz one SPI byte lasts 1.25 us - exactly one WS2812 bit.
  WS2812 '0'  -> SPI byte 0b11000000 (high ~0.31 us, low ~0.94 us)
  WS2812 '1'  -> SPI byte 0b11111000 (high ~0.78 us, low ~0.47 us)
Each LED needs 24 bits (G,R,B order) = 24 SPI bytes. A run of zero bytes
(>= 300 us low) latches the colours.
"""
import logging
import time

log = logging.getLogger(__name__)

BIT0 = 0b11000000
BIT1 = 0b11111000
RESET_BYTES = 320          # 320 x 1.25 us = 400 us low (> 280 us latch)


def encode_ws2812(pixels, color_order: str = "GRB") -> bytes:
    """Convert a list of (r, g, b) tuples into SPI bytes. Pure function."""
    idx = {"R": 0, "G": 1, "B": 2}
    out = bytearray([0])           # leading 0 byte avoids a first-bit glitch
    for px in pixels:
        for ch in color_order:
            value = int(px[idx[ch]]) & 0xFF
            for bit in range(7, -1, -1):
                out.append(BIT1 if (value >> bit) & 1 else BIT0)
    out.extend(b"\x00" * RESET_BYTES)
    return bytes(out)


class _Ws2812Spi:
    def __init__(self, cfg):
        import spidev  # pip install spidev  (needs SPI enabled)
        self.cfg = cfg
        self.n_top = int(cfg["top_count"])
        self.n_bottom = int(cfg["bottom_count"])
        self.spi = spidev.SpiDev()
        self.spi.open(int(cfg["spi_bus"]), int(cfg["spi_device"]))
        self.spi.max_speed_hz = int(cfg["spi_hz"])
        self.spi.mode = 0
        n_bytes = 1 + 24 * (self.n_top + self.n_bottom) + RESET_BYTES
        if n_bytes > 4096:
            log.warning("LED frame is %d bytes (> 4096 spidev default). Add "
                        "spidev.bufsiz=65536 to /boot/firmware/cmdline.txt", n_bytes)

    def _scaled(self, rgb):
        b = max(0.0, min(1.0, float(self.cfg.get("brightness", 1.0))))
        return tuple(int(c * b) for c in rgb)

    def show(self, top_on: bool, bottom_on: bool):
        off = (0, 0, 0)
        top = self._scaled(self.cfg["top_rgb"]) if top_on else off
        bot = self._scaled(self.cfg["bottom_rgb"]) if bottom_on else off
        pixels = [top] * self.n_top + [bot] * self.n_bottom
        data = encode_ws2812(pixels, self.cfg.get("color_order", "GRB"))
        self.spi.writebytes2(data)

    def close(self):
        try:
            self.show(False, False)
        finally:
            self.spi.close()


class _GpioMosfet:
    def __init__(self, cfg):
        from gpiozero import DigitalOutputDevice
        self.top = DigitalOutputDevice(int(cfg["top_gpio"]))
        self.bottom = DigitalOutputDevice(int(cfg["bottom_gpio"]))

    def show(self, top_on: bool, bottom_on: bool):
        self.top.value = 1 if top_on else 0
        self.bottom.value = 1 if bottom_on else 0

    def close(self):
        self.show(False, False)
        self.top.close()
        self.bottom.close()


class _Dummy:
    def __init__(self, cfg):
        self.state = (False, False)

    def show(self, top_on: bool, bottom_on: bool):
        self.state = (top_on, bottom_on)
        log.debug("LEDs (dummy): top=%s bottom=%s", top_on, bottom_on)

    def close(self):
        pass


class LedController:
    """High-level API used by the inspection sequence."""

    def __init__(self, cfg: dict, simulate: bool = False):
        backend = "dummy" if simulate else cfg.get("backend", "ws2812_spi")
        cls = {"ws2812_spi": _Ws2812Spi, "gpio_mosfet": _GpioMosfet,
               "dummy": _Dummy}[backend]
        self.driver = cls(cfg)
        self.backend = backend
        self.all_off()

    def top_on(self):
        self.driver.show(True, False)

    def bottom_on(self):
        self.driver.show(False, True)

    def all_off(self):
        self.driver.show(False, False)

    def both_on(self):
        self.driver.show(True, True)

    def light(self, side: str):
        """Turn on ONLY the light for `side` ('top' or 'bottom')."""
        {"top": self.top_on, "bottom": self.bottom_on}[side]()

    def close(self):
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def blink_test(ctrl: LedController, cycles: int = 3, period: float = 0.5):
    for _ in range(cycles):
        ctrl.top_on(); time.sleep(period)
        ctrl.bottom_on(); time.sleep(period)
        ctrl.all_off(); time.sleep(period)
