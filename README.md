# PCB X — Portable Edge-AI Inspection Chamber (capstone implementation package)

Dual-sided PCB component detection with tri-tier **PASS / FAIL / REVIEW**
classification on a Raspberry Pi 5. Built from your *PCB X System Workflow and
Training Guide* (PDF), which remains the reference design; the changes and the
reasons for them are listed in `docs/00_Technical_Review.md`, section 1.

**Final prototype configuration (used in the diagrams below):**
Raspberry Pi 5 (4 GB) · **2 × Raspberry Pi Camera Module 3 (standard)** — bottom on
CAM0, top on CAM1 · 2 × WS2812B strips on one SPI data line through a 74AHCT125
level shifter · 7″ HDMI touchscreen · START button, drawer switch, power button.

---

## 1. Block diagram

```mermaid
flowchart LR
  subgraph PWR["Power"]
    AC["220 V AC outlet"]
    PSU27["Official 27 W USB-C PSU<br/>5.1 V 5 A"]
    PSU5["LED PSU<br/>5 V 3 A"]
    AC --> PSU27
    AC --> PSU5
  end

  subgraph CTRL["Controller"]
    PI["Raspberry Pi 5 · 4 GB<br/>Active Cooler · 64 GB microSD<br/>Raspberry Pi OS 64-bit<br/>Python · OpenCV · YOLO NCNN"]
  end

  subgraph CHAMBER["Inspection chamber"]
    direction TB
    CAMT["Top camera<br/>Camera Module 3<br/>(Side A, THT parts)"]
    LEDT["Top LED strip<br/>WS2812B ×24 + diffuser"]
    TRAY["Drawer + nest<br/>PCB X 115 × 45 mm"]
    LEDB["Bottom LED strip<br/>WS2812B ×24 + diffuser"]
    CAMB["Bottom camera<br/>Camera Module 3<br/>(Side B, SMD parts)"]
    SW["Drawer microswitch"]
    TRAY -.- SW
  end

  subgraph UI["Operator interface"]
    LCD["7-inch HDMI touchscreen<br/>1024 × 600"]
    BTN["START button<br/>with LED"]
    PBTN["Power button"]
  end

  SHIFT["74AHCT125<br/>3.3 V → 5 V level shifter"]

  PSU27 -- "USB-C" --> PI
  PSU5 -- "+5 V / GND" --> LEDT
  PSU5 -- "+5 V / GND" --> LEDB
  PSU5 -- "+5 V / GND" --> SHIFT
  CAMT -- "CSI ribbon · CAM1" --> PI
  CAMB -- "CSI ribbon · CAM0" --> PI
  PI -- "GPIO10 SPI MOSI" --> SHIFT
  SHIFT -- "DIN" --> LEDT
  LEDT -- "DOUT → DIN" --> LEDB
  SW -- "GPIO27" --> PI
  BTN -- "GPIO17 in / GPIO22 LED" --> PI
  PBTN -- "J2 header" --> PI
  PI -- "micro-HDMI" --> LCD
  LCD -- "USB touch" --> PI
```

**Signal summary**

| From | To | Interface |
|---|---|---|
| Bottom camera | Pi 5 CAM0 | MIPI CSI-2, 22-pin → 15-pin ribbon |
| Top camera | Pi 5 CAM1 | MIPI CSI-2, 22-pin → 15-pin ribbon |
| Pi 5 GPIO10 | 74AHCT125 → top strip DIN → bottom strip DIN | SPI MOSI, WS2812 data (800 kHz) |
| START button | Pi 5 GPIO17 | digital in, internal pull-up |
| START button LED | Pi 5 GPIO22 | digital out |
| Drawer microswitch | Pi 5 GPIO27 | digital in, internal pull-up |
| Power button | Pi 5 J2 | power on / safe shutdown |
| Touchscreen | Pi 5 HDMI0 + USB | video + touch |

---

## 2. Detailed schematic

```
                        ┌─────────────────────────── 220 V AC ───────────────────────────┐
                        │                                                                │
              ┌─────────┴─────────┐                                         ┌────────────┴───────────┐
              │ Official 27 W PSU │                                         │  5 V 3 A LED adapter   │
              │ USB-C 5.1 V / 5 A │                                         │  (+) 5V      (−) GND   │
              └─────────┬─────────┘                                         └─────┬──────────┬───────┘
                        │ USB-C                                                   │          │
                        ▼                                                  +5V_LED│          │GND
 ┌──────────────────────────────────────────────────────┐                        │   C1     │
 │                  RASPBERRY PI 5 (4 GB)               │                        ├──┤├──────┤  C1 = 1000 µF / 10 V
 │                                                      │                        │  (+)  (−)│      (at strip input)
 │  CAM0 [22-pin] ◄═══ ribbon ═══ BOTTOM Camera Module 3│                        │          │
 │  CAM1 [22-pin] ◄═══ ribbon ═══ TOP    Camera Module 3│                        │          │
 │  HDMI0 ═══ micro-HDMI ═══► 7" touchscreen (HDMI in)  │                        │          │
 │  USB 2.0 ◄═══ USB ═══ touchscreen (touch / power*)   │                        │          │
 │  FAN ◄═══ Active Cooler                              │                        │          │
 │  J2 (PWR BUT) ●──[ S3 POWER, momentary NO ]──●       │                        │          │
 │                                                      │                        │          │
 │  J8 40-pin header (only used pins shown)             │     U1 74AHCT125 (DIP-14, powered from 5 V)
 │                                                      │     ┌──────────────────────┐   │          │
 │  pin 19  GPIO10 / SPI0 MOSI ─────────────────────────┼────►│2  1A          VCC 14│◄──┘          │
 │                                                      │  ┌─►│1  1OE         4OE 13│◄── +5V_LED    │
 │  pin 6   GND ────────────────────────────────────────┼──┼─►│7  GND          4A 12│──► GND        │
 │                         (COMMON GROUND) ─────────────┼──┴──┼──────────────────────┼───────────────┤
 │                                                      │     │4  2OE ◄─ +5V   4Y 11│ n.c.          │
 │                                                      │     │5  2A  ◄─ GND  3OE 10│◄── +5V_LED    │
 │                                                      │     │6  2Y  n.c.     3A  9│──► GND        │
 │                                                      │     │3  1Y ──┐       3Y  8│ n.c.          │
 │                                                      │     └────────┼─────────────┘               │
 │                                                      │              │  R1 330 Ω                   │
 │                                                      │              └──/\/\/──┐                    │
 │                                                      │                        ▼                    │
 │                                                      │   ┌────────────────────────────────────┐   │
 │                                                      │   │ TOP STRIP  WS2812B × 24            │   │
 │                                                      │   │ +5V ◄── +5V_LED   GND ──► GND ─────┼───┤
 │                                                      │   │ DIN (input end)  …  DOUT (out end) │   │
 │                                                      │   └──────────────────────────┬─────────┘   │
 │                                                      │                   data wire  │             │
 │                                                      │   ┌──────────────────────────▼─────────┐   │
 │                                                      │   │ BOTTOM STRIP  WS2812B × 24         │   │
 │                                                      │   │ +5V ◄── +5V_LED   GND ──► GND ─────┼───┘
 │                                                      │   │ DIN                    DOUT  n.c.  │
 │                                                      │   └────────────────────────────────────┘
 │                                                      │
 │  pin 11  GPIO17 ────────[ S1 START, momentary NO ]───┼── pin 9  GND     (internal pull-up, pressed = LOW)
 │  pin 13  GPIO27 ────────[ S2 drawer microswitch  ]───┼── pin 14 GND     (NO contact: drawer closed = LOW)
 │  pin 15  GPIO22 ──/\/\/──►|────────────────────────── ┼── pin 20 GND     (START button LED)
 │                  R2 330 Ω  D1                        │
 └──────────────────────────────────────────────────────┘
   * Power the touchscreen from its own USB/5 V input if it flickers; do not use J8 5 V pins for LEDs.
```

**Component list for the schematic**

| Ref | Part | Value / type | Notes |
|---|---|---|---|
| — | Raspberry Pi 5 | 4 GB | official Active Cooler on FAN header |
| CAM0 | Camera Module 3 (standard) | 12 MP, autofocus | bottom side, SMD parts |
| CAM1 | Camera Module 3 (standard) | 12 MP, autofocus | top side, THT parts |
| U1 | 74AHCT125 | quad buffer, DIP-14 | 3.3 V → 5 V level shifter, VCC = 5 V |
| R1 | Resistor | 330 Ω ¼ W | in series with DIN, close to the first LED |
| R2 | Resistor | 330 Ω ¼ W | START LED current limit (skip if the button LED has a built-in resistor) |
| C1 | Electrolytic capacitor | 1000 µF 10 V | across +5V_LED/GND at the strip input; mind polarity |
| D1 | LED | built into S1 | START "ready" indicator |
| S1 | Push button | momentary NO, 16–22 mm | START |
| S2 | Microswitch with lever | NO contact | closed when the drawer is fully in |
| S3 | Push button | momentary NO | to J2 (PWR BUT) |
| LED1 | WS2812B strip | 24 LEDs, 5 V, 60/m | top strip, first in the chain |
| LED2 | WS2812B strip | 24 LEDs, 5 V, 60/m | bottom strip, fed from LED1 DOUT |
| PSU1 | Official Raspberry Pi 27 W USB-C | 5.1 V 5 A | Pi only |
| PSU2 | DC adapter | 5 V 3 A | LEDs + U1 only |

---

## 3. Pinouts

### 3.1 Raspberry Pi 5 J8 40-pin header

`◄` = used in this prototype. Pins marked *SPI0 reserved* are claimed when SPI is enabled; don't use them for anything else.

| Function | GPIO | Pin | Pin | GPIO | Function |
|---|---|---|---|---|---|
| 3V3 | — | 1 | 2 | — | 5V |
| SDA1 | GPIO2 | 3 | 4 | — | 5V |
| SCL1 | GPIO3 | 5 | 6 | — | **GND ◄ common ground to U1 / LED PSU** |
| — | GPIO4 | 7 | 8 | GPIO14 | TXD |
| GND | — | 9 | 10 | GPIO15 | RXD |
| **START button S1 ◄** | **GPIO17** | **11** | 12 | GPIO18 | — |
| **Drawer switch S2 ◄** | **GPIO27** | **13** | **14** | — | **GND ◄ S2** |
| **START LED D1 ◄** | **GPIO22** | **15** | 16 | GPIO23 | — |
| 3V3 | — | 17 | 18 | GPIO24 | — |
| **SPI0 MOSI → U1 1A ◄** | **GPIO10** | **19** | **20** | — | **GND ◄ D1** |
| SPI0 MISO *(SPI0 reserved)* | GPIO9 | 21 | 22 | GPIO25 | — |
| SPI0 SCLK *(SPI0 reserved)* | GPIO11 | 23 | 24 | GPIO8 | SPI0 CE0 *(SPI0 reserved)* |
| GND | — | 25 | 26 | GPIO7 | SPI0 CE1 *(SPI0 reserved)* |
| ID_SD (do not use) | GPIO0 | 27 | 28 | GPIO1 | ID_SC (do not use) |
| — | GPIO5 | 29 | 30 | — | GND |
| — | GPIO6 | 31 | 32 | GPIO12 | spare (MOSFET option, top) |
| spare (MOSFET option, bottom) | GPIO13 | 33 | 34 | — | GND |
| — | GPIO19 | 35 | 36 | GPIO16 | — |
| — | GPIO26 | 37 | 38 | GPIO20 | — |
| GND | — | 39 | 40 | GPIO21 | — |

S1 uses pin 9 (GND) as its return. All GND pins are connected together on the board.

### 3.2 Other Raspberry Pi 5 connectors

| Connector | Connected to | Notes |
|---|---|---|
| USB-C power | Official 27 W PSU | needed for full USB current; avoid phone chargers |
| CAM0 (22-pin mini FPC) | Bottom Camera Module 3 | Pi 5 cable **22-pin → 15-pin**; follow Raspberry Pi docs for contact orientation |
| CAM1 (22-pin mini FPC) | Top Camera Module 3 | same cable type, 300–500 mm |
| HDMI0 (micro-HDMI) | 7″ touchscreen | the port next to USB-C |
| USB 2.0 | Touchscreen touch (and power if the screen needs it) | |
| FAN (4-pin) | Official Active Cooler | |
| J2 (PWR BUT, 2 pads) | S3 power button | momentary NO; no resistor needed |
| microSD | 64 GB A2 high-endurance | OS + software + logs |

### 3.3 74AHCT125 (U1) pinout (DIP-14, top view)

```
            ┌───────U───────┐
  1OE  1 ───┤●              ├─── 14  VCC  → +5V_LED
   1A  2 ───┤               ├─── 13  4OE  → +5V (unused, disabled)
   1Y  3 ───┤               ├─── 12  4A   → GND (unused input)
  2OE  4 ───┤   74AHCT125   ├─── 11  4Y     n.c.
   2A  5 ───┤               ├─── 10  3OE  → +5V (unused, disabled)
   2Y  6 ───┤               ├───  9  3A   → GND (unused input)
  GND  7 ───┤               ├───  8  3Y     n.c.
            └───────────────┘
  pin 1 1OE → GND (enabled: OE is active LOW)
  pin 2 1A  ← Pi pin 19 (GPIO10)
  pin 3 1Y  → R1 330 Ω → top strip DIN
  pin 4 2OE → +5V (disabled)   pin 5 2A → GND   pin 6 2Y n.c.
  pin 7 GND → common ground
```

### 3.4 WS2812B strip pads

| Pad | Top strip (LED1) | Bottom strip (LED2) |
|---|---|---|
| +5V | +5V_LED (thick wire, ≥ 22 AWG) | +5V_LED (own wire from the supply) |
| GND | GND (thick wire) | GND (own wire) |
| DIN | from U1 pin 3 via R1 330 Ω | from LED1 DOUT |
| DOUT | to LED2 DIN | not connected |

Follow the arrows printed on the strip: data flows DIN → DOUT. In software,
LEDs 0–23 are the top strip and 24–47 the bottom strip
(`config.py` → `LIGHTING`).

### 3.5 Camera Module 3 (each)

| Item | Value |
|---|---|
| Sensor / resolution | 12 MP; capture mode used: 2304 × 1296 (2×2 binned) |
| Field of view (standard lens) | ≈ 66° horizontal × 41° vertical |
| Mounting distance | 110–130 mm from the board (≥ 10 cm minimum focus) |
| Focus | locked in software (`LensPosition` in `config.py`, set with `tools/test_cameras.py --focus-sweep`) |
| Connector | 15-pin on camera → 22-pin on Pi 5 |

---

## 4. Electrical rules

1. **Common ground:** LED PSU (−), U1 GND and a Pi GND pin must be connected, or
   the LED data signal has no reference and the colours go random.
2. **Never power the LEDs from the Pi's 5 V pins** (pins 2/4). They share the
   Pi's USB power budget; 24 white LEDs can draw up to ~1.4 A.
3. **Level shifter required:** the Pi outputs 3.3 V; WS2812B at 5 V expects
   about 0.7 × 5 V = 3.5 V for a reliable HIGH.
4. **R1 and C1** go at the strip end of the wiring (R1 near DIN, C1 across +5 V/GND).
5. **Current budget:** 60 mA per LED at full white (typical). Only one strip is on
   at a time; at `brightness: 0.6` that is ≈ 24 × 60 mA × 0.6 ≈ 0.9 A → the 5 V 3 A
   supply has a safe margin.
6. **Enable SPI** (`install_pi.sh` does it) — the data line is `/dev/spidev0.0`.
7. **Ribbon cables:** insert with the power off; don't fold them sharply or let them
   rub on the drawer.
8. **ESD:** handle PCBs and camera boards with a grounded wrist strap.

---

## 5. Start here

1. **Read** `docs/00_Technical_Review.md` — answers to Parts 1–8, corrections to
   the PDF, decision table, roadmap and the recommended final configuration.
2. **Buy and wire** with `docs/A_Hardware.md` and sections 1–4 above.
3. **Bring up the Pi** stage by stage with `docs/C_Pi_Software_Roadmap.md`.
4. **Collect, label and train** with `training/README.md` and the Colab notebook.
5. **Test and report** with `docs/D_Testing_and_Validation.md`.

## 6. Package map

| Package | Content | Location |
|---|---|---|
| A Hardware | block diagram, wiring diagram, GPIO table, BOM, chamber/tray, controls | `docs/A_Hardware.md`, this README |
| B AI training | Colab notebook, data YAMLs, hyper-parameter YAMLs, Label Studio configs, prepare/check/zip tools, train/validate/export/learning-curve scripts, requirements, README | `training/` |
| C Pi software | complete Python project, installer, autostart files, unit tests | `pcbx_inspection/`, `docs/C_Pi_Software_Roadmap.md` |
| D Testing | procedures D1–D9 with pass criteria and record templates | `docs/D_Testing_and_Validation.md` |

## 7. What has been verified, and what has not

**Verified in our build environment (Linux x86, Python 3.13, ultralytics 8.4.218):**
18 unit tests pass (matching, all decision rules, Hungarian vs nearest-neighbour,
WS2812 bit encoding, alignment Scenarios A/B/C, empty tray, hidden fiducial);
the full inspection pipeline (`process()` and `inspect()` with simulated cameras)
produces PASS/FAIL, overlays, CSV/JSON logs; the training chain demo dataset →
prepare → check → train (YOLOv8n and YOLO26n) → validate → rectangular NCNN
export → NCNN prediction; and the Colab notebook executed end-to-end locally.

**Not verified:** the Tkinter GUI was checked statically but not opened (no
display toolkit in our build environment) — run `python main.py --simulate
--windowed` early. **Needs your hardware:** anything involving the real cameras,
LEDs, GPIO, the Raspberry Pi 5 itself, NCNN speed on the Pi, RAM use, and every
accuracy figure. All such numbers in the documents are labelled **[ESTIMATE]**
or **[MUST TEST]**. The schematic has not been built and tested — check every
connection against the part datasheets before powering up.

## 8. Folder overview

```
PCBX_Capstone/
├── README.md                     ← this file (block diagram, schematic, pinouts)
├── docs/
│   ├── 00_Technical_Review.md
│   ├── A_Hardware.md
│   ├── C_Pi_Software_Roadmap.md
│   └── D_Testing_and_Validation.md
├── training/                     (Package B)
└── pcbx_inspection/              (Package C)
```
