# Package A — Hardware setup and wiring guide (V2: 2 × Camera Module 3)

Labels used in this document:
**[CONFIRMED]** = checked against a manufacturer/official source (listed at the end) ·
**[RECOMMENDATION]** = our engineering choice, with reasons ·
**[ESTIMATE]** / **[MUST TEST]** = a number or behaviour you must measure on your build.

---

## A1. Final recommended hardware configuration

| Block | Recommended | Status vs. your plan |
|---|---|---|
| Computer | **Raspberry Pi 5, 4 GB** + official Active Cooler + official 27 W USB-C PSU | keep 4 GB (8 GB not needed, see A1.1) |
| Lower camera (below the tray, normally sees the BACK/SMD side) | **Raspberry Pi Camera Module 3 Standard** on **CAM0** | V2 final |
| Upper camera (above the tray, normally sees the FRONT/THT side) | **Raspberry Pi Camera Module 3 Standard** on **CAM1** | V2 final (USB webcam code kept as optional fallback) |
| Lighting | **WS2812B, 2 strips on ONE SPI data line** (GPIO10), 74AHCT125 level shifter, separate 5 V 3 A supply, opal diffusers | keep WS2812B, add shifter + diffuser |
| Display | **7″ HDMI touchscreen (1024 × 600)** | HDMI, not DSI (both CAM/DISP ports may be needed for cameras) |
| Storage | **32 GB high-endurance A1/A2 microSD** (OS + app + logs; off-load logs weekly) | 32 GB is sufficient (V2 evaluation); 64 GB only if same price |
| Controls | Power button on Pi 5 **J2** header, 1 illuminated **START** button, 1 **drawer-closed microswitch** | no E-stop, no reset button |
| Mechanics | **Drawer-type tray with removable 3-D-printed nest**, 4 corner support tabs, end-stop + ball-catch detent | see A5 |

### A1.1 Is a Pi 5 with 4 GB enough?

| Item | RAM [ESTIMATE — measure with `tools/benchmark.py` and `free -h`] |
|---|---|
| Raspberry Pi OS desktop, idle | 0.5 – 0.8 GB |
| Python + PyTorch + Ultralytics imported | 0.4 – 0.6 GB |
| Two NCNN models loaded (n-size) + inference buffers | 0.1 – 0.3 GB |
| Camera buffers (binned 2304×1296 CSI + 2560×1440 USB) | 0.05 – 0.15 GB |
| Working images (raw, undistort map, canvases), GUI | 0.15 – 0.3 GB |
| **Total** | **≈ 1.2 – 2.2 GB of 4 GB** |

* The PDF's 1–1.5 GB is plausible but optimistic once PyTorch is imported
  (Ultralytics imports it even when the model is NCNN).
* Capturing the CSI camera in the **2×2-binned mode** (Camera Module 3:
  2304 × 1296) instead of full 12–16 MP cuts per-frame memory ~4× and is
  still ≥ 14 px/mm at 12 cm — more than the 10 px/mm canvas needs.
* **8 GB?** Not justified. [CONFIRMED] Makerlab PH lists the Pi 5 4 GB at
  ₱11,449 and 8 GB at ₱17,999 (Nov 2026) after several memory-driven price
  increases in 2026. The extra ₱6,550 buys headroom you will not use. Buy 8 GB
  only if `benchmark.py` shows > 3.2 GB used.

### A1.2 Inference engine, speed and cooling

* **[CONFIRMED]** Ultralytics states NCNN gives the best inference performance
  of all its export formats on Raspberry Pi, and its NCNN export supports
  YOLOv8, YOLO11 and YOLO26. Their Pi 5 benchmark lists YOLO26n (NCNN, FP32,
  640 px) at **67 ms per image, excluding pre/post-processing**.
* **[ESTIMATE]** Our top model runs at 288 × 640 (≈ 0.45× the pixels of
  640 × 640) and the bottom model at 512 × 1216 (≈ 1.5×). Scaling the
  published number gives roughly 40–60 ms (top) and 100–150 ms (bottom) for
  the network, plus Python overhead. YOLOv8n is similar in size. **[MUST TEST]**
* **Per-board time [ESTIMATE]:** capture 2 × (0.3 s LED settle + 0.1–0.3 s
  flush/grab) ≈ 0.8–1.2 s; alignment ≈ 0.1–0.2 s; inference ≈ 0.2–0.5 s;
  matching < 10 ms; GUI draw ≈ 50 ms → **≈ 1.3–2.2 s**, inside your 2–4 s
  target. Image saving runs in the background.
* **Active cooling: yes.** Continuous CPU inference heats the SoC; without
  cooling the Pi throttles and timings become inconsistent between boards.
  `benchmark.py` prints `vcgencmd get_throttled` — it must stay `0x0`.

---

## A2. Cameras — 2 × Raspberry Pi Camera Module 3 Standard

### A2.1 Facts [CONFIRMED, see sources]
| Item | Value |
|---|---|
| Sensor | Sony IMX708, 11.9 MP, 4608 × 2592, motorised focus |
| Field of view (standard lens) | 66° horizontal × 41° vertical (75° diagonal) |
| Focus range | 10 cm – infinity |
| Pi 5 connectors | **two** 4-lane MIPI connectors **CAM/DISP 0** and **CAM/DISP 1** (each camera *or* display) |
| Cable | Pi 5 uses the **mini 22-pin** connector → "**Standard–Mini**" camera cable (22-pin on the Pi side, 15-pin on the camera side); 200/300/500 mm lengths exist |
| Drivers | none to install — official modules are auto-detected by Raspberry Pi OS |
| Two cameras at once | supported (rpicam-apps `--camera 0/1`, two `Picamera2(n)` objects) |

### A2.2 Installing the cameras
1. **Power off and unplug the Pi.** Never connect cameras live.
2. On the Pi 5 the two camera connectors sit between the Ethernet and HDMI ports.
   Lift the connector latch gently.
3. Insert the 22-pin end of the cable with its **metal contacts facing the
   Ethernet port** (Arducam/Waveshare Pi 5 guides), fully and straight; press the latch down.
4. **CAM0 → lower camera** (looks up at the board), **CAM1 → upper camera** (looks down).
5. Camera end: follow the cable's printed marking / the camera's connector
   (contacts towards the connector's contacts). Do not twist or sharply fold the cable;
   route it away from the drawer.
6. Mount each camera so the board is **110–130 mm** away and centred
   (≥ 10 cm minimum focus). At 120 mm the view is ≈ 156 × 90 mm, the board
   115 × 45 mm fits with margin. [ESTIMATE]

### A2.3 Identifying and testing the cameras
```bash
rpicam-hello --list-cameras                # expect two "imx708" entries (0 and 1)
rpicam-still --camera 0 -o cam0.jpg        # lower camera?  (cover it with a finger to check)
rpicam-still --camera 1 -o cam1.jpg        # upper camera?
cd ~/PCBX_Capstone/pcbx_inspection && source ~/pcbx-venv/bin/activate
python tools/test_cameras.py --list        # what Picamera2 sees + config mapping
python tools/test_cameras.py --both-streaming   # both cameras open at the same time
python tools/test_cameras.py               # 10 LED-synchronised captures per camera (stability)
python tools/test_cameras.py --camera upper --focus-sweep 4 14 0.5   # best LensPosition
```
If upper/lower are swapped, exchange `camera_num` in `config.py` →
`CAMERAS["upper"]` / `["lower"]` (or swap the cables).

### A2.4 Software configuration (`config.py` → `CAMERAS`)
| Key | Value | Why |
|---|---|---|
| `backend` | `picamera2` | official CSI stack |
| `camera_num` | upper 1, lower 0 | connector |
| `width × height` | 2304 × 1296 | 2×2-binned mode: sharper per pixel, faster, ~4× less RAM than 12 MP; ≈ 14.8 px/mm at 120 mm, above the 10 px/mm canvas |
| `ExposureTime`, `AnalogueGain` | fixed (start 8000 µs, 1.0) | no auto-exposure drift |
| `AwbEnable` / `ColourGains` | False / fixed | colours stay constant (part colours carry information) |
| `AfMode` / `LensPosition` | 0 (manual) / ≈ 1 / distance [m] (e.g. 8.0 at 125 mm) | fixed focus at a fixed distance; tune with `--focus-sweep` |
| `flush_frames` | 2 | discard frames exposed before the LED switched on |
| `led` | upper → `top` strip, lower → `bottom` strip | only the light of the camera taking the photo is on |
| `calibration_file` | `upper_camera.json` / `lower_camera.json` | independent lens calibration per camera |

### A2.5 Simultaneous or sequential?
Both cameras are **opened and streaming for the whole session** (no 1–2 s
start-up per board). Photos are taken **sequentially** — upper with the top
LEDs only, then lower with the bottom LEDs only — so the light of one side
does not leak through holes and board edges into the other camera. The extra
time is < 1 s. In **flip mode** only `FLIP_CAMERA` is used and the operator
flips the board between the two photos (Settings > Inspection).

### A2.6 Same camera model, both sides
Each side is warped to the same 10 px/mm canvas and compared with **that
side's** golden reference. Coordinates are never compared between cameras,
so identical cameras simply mean one calibration procedure and one set of
settings to learn. Each camera still has its own calibration file.

## A3. Lighting (WS2812B)

### A3.1 Facts and why the circuit looks like this

* **[CONFIRMED]** The classic `rpi_ws281x` library needs a kernel module on the
  Pi 5 (because of the new RP1 I/O chip) and its Pi 5 support is labelled
  experimental; SPI on MOSI = **GPIO10 (pin 19)** is the method used by
  Pi 5-specific libraries. Our `lighting/led_controller.py` drives the strip
  through `/dev/spidev0.0` itself (no extra library).
* **[CONFIRMED]** WS281x LEDs are driven at 5 V and the rpi_ws281x project
  states a level shifter is required for the 3.3 V GPIO signal. (The WS2812B
  datasheet input-high threshold is 0.7 × VDD ≈ 3.5 V at 5 V — 3.3 V is below
  it, so without a shifter it may work on the bench and fail in the chamber.)
* **[RECOMMENDATION]** Chain both strips on **one data line**: the first
  `top_count` LEDs = top strip, the next `bottom_count` = bottom strip. Software
  still switches them independently, and only one GPIO is used.

### A3.2 Wiring diagram

```
 5 V 3 A LED SUPPLY  (+5V) ──┬──────────────┬────────────────┬───────────────────┐
                             │              │                │                   │
                       [1000 µF 10 V]   74AHCT125 pin 14   TOP strip +5V      BOTTOM strip +5V
                             │           (VCC)
 5 V 3 A LED SUPPLY  (GND) ──┴──────────────┬────────────────┬───────────────────┐
                                            │                │                   │
                                  74AHCT125 pin 7 (GND)   TOP strip GND      BOTTOM strip GND
                                  74AHCT125 pin 1 (1OE)  ← tie to GND (output enabled)
                                  pins 5, 9, 12 (2A,3A,4A) ← tie to GND (unused inputs)
                                  pins 4, 10, 13 (2OE,3OE,4OE) ← tie to VCC (unused outputs off)
                                            │
            Raspberry Pi 5 pin 6 (GND) ─────┘   ← COMMON GROUND (mandatory)

 Raspberry Pi 5 pin 19 (GPIO10 / SPI0 MOSI) ──► 74AHCT125 pin 2 (1A)
 74AHCT125 pin 3 (1Y) ──[330 Ω]──► TOP strip DIN
 TOP strip DOUT ─────────────────► BOTTOM strip DIN      (one data line, 48 LEDs total)

 Raspberry Pi 5 pin 11 (GPIO17) ──[ START button, NO ]──── pin 9 (GND)
 Raspberry Pi 5 pin 13 (GPIO27) ──[ drawer microswitch, NO ]── pin 14 (GND)
 Raspberry Pi 5 pin 15 (GPIO22) ──[ 330 Ω ]──►|── GND        (START button LED)
 Raspberry Pi 5 J2 pads ──────────[ POWER button, momentary NO ]
 Raspberry Pi 5 USB-C  ◄── official 27 W PSU
 CAM0 ◄── lower Camera Module 3   CAM1 ◄── upper Camera Module 3
 HDMI0 ──► 7" display     USB ◄── touch panel
```

Rules:
1. **Common ground**: LED supply (−) to a Pi GND pin. Without it the data
   signal has no reference → random colours.
2. **Do not power the LEDs from the Pi's 5 V pins.** The Pi 5 shares that rail
   with its USB ports; 24 LEDs at full white draw up to ~1.4 A.
3. 330 Ω in series with DIN, close to the first LED; 1000 µF across the strip
   supply at the input.
4. Feed +5 V/GND to *both* ends of each strip if the strips are long (> 30 LEDs).
5. Enable SPI: `sudo raspi-config nonint do_spi 0` (done by `install_pi.sh`).
6. Budget: 60 mA per LED at full white [datasheet typical]. Only one strip is on
   at a time; at `brightness: 0.6` → 24 × 60 mA × 0.6 ≈ 0.9 A. A 5 V 3 A supply
   gives a safe margin.

**Alternative (simpler, more robust):** two plain **white 5 V or 12 V LED
strips** switched by logic-level MOSFET modules on GPIO12/GPIO13
(`LIGHTING["backend"] = "gpio_mosfet"`). No timing, no shifter, better white
(high-CRI strips exist). Choose this if the WS2812B gives trouble in Stage 3.

### A3.3 Getting even, glare-free light

| Problem | Fix |
|---|---|
| Hot-spot reflections on solder, IC tops, electrolytic caps | No LEDs on the camera axis. Mount **two LED bars along the long sides of the board at ~30–45°**, so mirror reflections go away from the lens |
| Visible LED dots | **Opal/frosted diffuser** (2–3 mm opal acrylic or translucent PP sheet) 10–20 mm in front of the LEDs |
| Uneven brightness | Matte **white** inner walls around the light (acts like a dome); check with a grey card: corners within ±10 % of centre |
| Remaining glare on shiny parts | **Optional** cross-polarisation: linear polariser film on the diffuser + polariser on the lens rotated 90°. Removes most specular glare; costs ~1–2 stops of light (raise exposure) |
| Light from the other side leaking through holes | Sequential capture (only one strip on) — already the design |
| Ambient light | Closed drawer = closed chamber; matte black tray nest |

---

## A4. Storage

| Option | Verdict |
|---|---|
| **32 GB high-endurance (A1/A2) microSD** | **Sufficient** [ESTIMATE]: OS + desktop 5–7 GB, venv with CPU PyTorch 2–3 GB, models < 30 MB → ~20 GB free ≈ 5,000 inspections with raw images (≈ 2–4 MB each) or ~20,000 without raw images. Copy `logs/` to a laptop weekly and delete old dates. |
| 64 GB high-endurance | only if about the same price, or if you keep every raw image of a long trial |
| SATA SSD via USB / NVMe HAT | not needed for this workload |

Check free space with `df -h /`. Use a **high-endurance** card (made for
continuous writing, e.g. dash-cam cards); ordinary cards wear out faster.
Back up `models/`, `references/` and `config/` — they are your calibrated system.

## A5. Chamber and tray mechanism

### A5.1 Recommended design: drawer with removable nest

```
   SIDE SECTION (not to scale)                        TOP VIEW OF THE NEST (3-D printed, matte black)
 ┌──────────────────────────────┐                     ┌──────────────────────────────────────────┐
 │   top camera (↓)             │  ← 110–130 mm        │ ┌──┐                                ┌──┐ │
 │ ╲ LED bar     LED bar ╱      │    diffusers         │ │▓▓│  pocket 115.6 × 45.6 mm        │▓▓│ │
 │  ╲ (diffuser) (diffuser)     │                     │ └──┘  (0.3 mm clearance per side)   └──┘ │
 │══════[ PCB in nest ]═════════│ ← drawer slides in   │        open window: board visible        │
 │  ╱                     ╲     │   on rails, end-stop │        from top AND bottom               │
 │ ╱ LED bar     LED bar  ╲     │   + ball-catch       │ ┌──┐                                ┌──┐ │
 │   bottom camera (↑)          │  ← 110–130 mm        │ │▓▓│  ▓▓ = 3 × 3 mm corner support  │▓▓│ │
 ├──────────────────────────────┤                     │ └──┘       tabs (only contact)      └──┘ │
 │ electronics bay: Pi 5, PSUs, │                     │   finger notches on both long sides      │
 │ level shifter, fan vent      │                     │   "▲ INSERT THIS WAY" arrow engraved     │
 └──────────────────────────────┘                     └──────────────────────────────────────────┘
```

* **Drawer** (front-loading) on two guide rails, with a hard **end-stop** and a
  **ball-catch/magnet detent** → the nest returns to the same place every time
  (repeatability matters more than tight tolerances; the software corrects
  ±2 mm and small rotation using the fiducials).
* **Removable nest**: a 3-D-printed plate with a pocket 0.3 mm larger than the
  board on each side and **four small corner tabs** the board rests on. The
  window is otherwise open so both cameras see the whole board, including its
  edges (needed by the outline detection). Print in **matte black** PLA/PETG
  (contrast with the solder mask, no reflections). Measure the real board
  first and print a test nest.
* **Component clearance**: the top side has tall THT parts (transformer!) —
  make the nest thin and the upper compartment tall enough; the bottom side
  has only SMD parts and solder joints, so the board can rest on its edges.
* **Orientation key**: a rectangular board fits a rectangular pocket in four
  ways (normal, rotated 180°, flipped, flipped + rotated). Instead of a
  mechanical key, the software handles all four: rotated → corrected
  automatically, flipped → "FLIP THE BOARD". An engraved arrow on the nest
  reduces operator errors. *(If PCB X has an asymmetric feature — a notch,
  connector overhang or mounting hole — a pin in the nest can make
  flipped insertion physically impossible. Check the board.)*
* **ESD**: handle boards with an ESD wrist strap; PLA is an insulator — avoid
  rubbing the board in the nest.

### A5.2 Sensors and safety items

| Item | Decision | Reason |
|---|---|---|
| Door / drawer-closed sensor | **Yes** — one microswitch hit by the drawer at its end-stop (₱30–80) | Captures with the drawer open let ambient light in → wrong images. One switch = "drawer closed **and** tray in position" |
| PCB presence sensor | **No** | The software already reports "no board" / "not PCB X" from the image |
| Mechanical lock | **No** | Nothing moves during inspection; adds failure points |
| Removable tray (nest) | **Yes** | Quick swap if worn; lets you print a nest for another board |
| Emergency stop | **No** | E-stops are for hazardous motion/energy. The chamber has no motors, no actuators and only 5 V inside. Explain this in the safety section; the power button and unplugging the adapters suffice |

---

## A6. Buttons and controls

| Control | Physical? | GUI? | Notes |
|---|---|---|---|
| Power | **Yes** — momentary NO button wired to the Pi 5 **J2** pads [CONFIRMED: J2 is a breakout for an external power button] | Exit/Shutdown button | Press = power on from shutdown / start safe shutdown |
| START inspection | **Yes** — one large illuminated button (GPIO17, LED on GPIO22) | **Yes** (big START, touch) | Operators can work without touching the screen; GUI is the backup |
| Next board | No | No | START again = next board |
| Reset | No | No | The program auto-restarts on crash (`run_pcbx.sh`); power button for hard cases |
| Manual capture | No | Tools only (`capture_dataset.py`) | Maintenance function, not operator function |
| Emergency stop | No | — | See A5.2 |
| Operator decision on REVIEW | No | **Yes** (Operator PASS / FAIL) | Logged; gives you data on how often REVIEW was needed |

Total physical controls: **2 buttons + 1 switch**.

### A6.1 GPIO assignment table

| Function | BCM GPIO | Physical pin | Direction | Notes |
|---|---|---|---|---|
| WS2812B data (via 74AHCT125) | GPIO10 (SPI0 MOSI) | 19 | out | SPI0 also reserves GPIO 7, 8, 9, 11 (pins 26, 24, 21, 23) — leave them free |
| START button | GPIO17 | 11 | in, pull-up | button to GND |
| Drawer-closed switch | GPIO27 | 13 | in, pull-up | NO switch to GND (closed = drawer in) |
| START button LED | GPIO22 | 15 | out | 330 Ω series (or the button's built-in resistor) |
| (alt.) top white strip MOSFET | GPIO12 | 32 | out | only with `gpio_mosfet` backend |
| (alt.) bottom white strip MOSFET | GPIO13 | 33 | out | only with `gpio_mosfet` backend |
| Ground | — | 6, 9, 14, 20, 25, 30, 34, 39 | — | common ground with LED supply |
| Power button | J2 header (not GPIO) | — | — | momentary NO |
| Fan | fan connector | — | — | official Active Cooler |

---

## A7. Hardware block diagram

```mermaid
flowchart LR
  subgraph Power
    PSU27[27 W USB-C PSU] --> PI
    PSU5[5 V 3 A LED supply] --> LEDT & LEDB
  end
  subgraph Chamber
    CAMT[Upper camera<br/>Camera Module 3] -->|CAM1| PI
    CAMB[Lower camera<br/>Camera Module 3] -->|CAM0| PI
    LEDT[Top WS2812B strip<br/>+ diffuser] -->|DOUT→DIN| LEDB[Bottom WS2812B strip<br/>+ diffuser]
    TRAY[Drawer + nest<br/>with PCB X] -.- SW[Drawer microswitch]
  end
  PI[Raspberry Pi 5 4 GB<br/>Active Cooler, 32 GB microSD]
  PI -->|GPIO10 SPI MOSI| SHIFT[74AHCT125<br/>3.3→5 V] --> LEDT
  SW -->|GPIO27| PI
  BTN[START button + LED] -->|GPIO17 / GPIO22| PI
  PWR[Power button] -->|J2| PI
  PI -->|HDMI + USB touch| LCD[7" touchscreen]
```

---

## A8. Bill of materials and budget (PHP)

Prices marked **[CONFIRMED]** were listed by the named PH store in Nov 2026
(stock and prices change — Raspberry Pi raised prices several times in 2026).
Everything else is an **[ESTIMATE]** of typical Shopee/Lazada/e-Gizmo prices; get
real quotes for your paper.

| # | Item | Qty | Unit ₱ | Total ₱ | Note |
|---|---|---|---|---|---|
| 1 | Raspberry Pi 5 **4 GB** | 1 | 11,449 | 11,449 | [CONFIRMED] Makerlab |
| 2 | Official 27 W USB-C power supply | 1 | 800–1,200 | ~1,000 | needed for full USB current |
| 3 | Official Active Cooler | 1 | 350–600 | ~450 | |
| 4 | 32 GB high-endurance microSD (A1/A2) | 1 | 350–700 | ~500 | e.g. Samsung PRO Endurance / SanDisk High Endurance |
| 5 | Camera Module 3 **Standard** (not Wide) | **2** | 1,530–2,490 | ~4,000 | [CONFIRMED Nov 2026] element14 PH ₱1,529.60; Makerlab ₱2,490 |
| 6 | Pi 5 "Standard–Mini" camera cable (22→15-pin), 300–500 mm | 2 | 70–250 | ~300 | the short cable in the camera box does **not** fit the Pi 5 |
| 7 | 7″ HDMI touchscreen 1024×600 | 1 | 2,845–3,290 | ~3,000 | [CONFIRMED] Makerlab range |
| 8 | Micro-HDMI → HDMI cable (short) | 1 | 150–300 | ~200 | |
| 9 | WS2812B 5 V 60 LED/m strip, 1 m | 1 | 250–450 | ~350 | cut 2 × 24 LEDs |
| 10 | 74AHCT125 (DIP-14) + socket | 1 | 40–100 | ~80 | |
| 11 | 5 V 3 A adapter + DC jack | 1 | 250–450 | ~350 | LEDs only |
| 12 | 1000 µF 10 V cap, 330 Ω resistors, perfboard, terminal blocks, wire | 1 set | 150–300 | ~250 | |
| 13 | START button (16–22 mm, illuminated, momentary) | 1 | 80–250 | ~150 | |
| 14 | Power button (momentary NO) + 2-pin header | 1 | 50–150 | ~100 | to J2 |
| 15 | Microswitch with lever (drawer) | 1 | 30–80 | ~50 | |
| 16 | Opal acrylic / translucent PP sheet (diffusers) | 1 | 150–400 | ~300 | |
| 17 | Enclosure: laser-cut 3 mm acrylic or MDF + matte paint | 1 | 1,500–3,500 | ~2,500 | inside: white near LEDs, black elsewhere |
| 18 | 3-D-printed nest + drawer (PLA/PETG, matte black) | 1 | 300–800 | ~600 | print 2–3 test nests |
| 19 | Drawer rails, ball-catch, hinges, standoffs, screws | 1 set | 200–500 | ~350 | |
| 20 | Printed checkerboard on stiff card | 1 | 50–100 | ~80 | calibration |
| | **Subtotal (V2: 2 × Camera Module 3)** | | | **≈ ₱26,000** | estimate, get quotes |
| 22 | Optional: polariser film (sheet + lens piece) | 1 | 200–500 | ~350 | |
| 23 | Optional: 8 GB Pi 5 instead of 4 GB | — | +6,550 | — | not recommended |

V2: EMEET C60E and Arducam 16 MP are no longer needed (the USB-webcam code path is kept only as a fallback).

**Purchase order** (to unblock software early): items 1–4, 5–6, 9–12 first
(Stages 1–4 need them), then 7–8, 13–15, then mechanics (16–19) once camera
distance and lighting are fixed in the pilot.

---

### Sources (checked Nov 2026)
- Raspberry Pi camera documentation (Pi 5 mini 22-pin connector, Standard–Mini cable); Camera Module 3 product brief/page (4608 × 2592, 66° × 41°, 10 cm–∞)
- Arducam / Waveshare Pi 5 connection guides (metal contacts face the Ethernet port); Tom's Hardware / The Pi Hut dual-camera guides
- Ultralytics Raspberry Pi guide & NCNN integration docs (NCNN fastest on Pi; YOLO26n NCNN 67.03 ms at 640 px on Pi 5; SSD vs SD advice)
- Arducam 16MP IMX519 documentation (FOV 66°×49.5°; AF models need Arducam libcamera; Pi 5 `dtoverlay=imx519`)
- Adorama / EMEET product pages (C60E: 4K30/1080p60, 73° FOV, PDAF, listed 4 MP sensor, USB 2.0)
- rpi_ws281x wiki "Raspberry Pi 5 Support"; rpi5-ws2812 on PyPI (SPI on GPIO10); rpi_ws281x README (5 V, level shifter)
- Raspberry Pi 5 J2 power-button header (Raspberry Pi documentation / element14 community)
- Makerlab PH and element14 PH product listings; Raspberry Pi price-increase announcements (2026)
