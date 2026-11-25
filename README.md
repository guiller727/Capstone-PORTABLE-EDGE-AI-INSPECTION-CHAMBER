# PCB X — Portable Edge-AI Inspection Chamber (capstone implementation package)

Dual-sided PCB component detection with tri-tier **PASS / FAIL / REVIEW**
classification on a Raspberry Pi 5. Built from your *PCB X System Workflow and
Training Guide* (PDF), which remains the reference design; the changes and the
reasons for them are listed in `docs/00_Technical_Review.md`, section 1.

## Start here

1. **Read** `docs/00_Technical_Review.md` — answers to Parts 1–8, corrections to
   the PDF, decision table, roadmap and the recommended final configuration.
2. **Buy and wire** with `docs/A_Hardware.md` (BOM in PHP, wiring, GPIO table).
3. **Bring up the Pi** stage by stage with `docs/C_Pi_Software_Roadmap.md`.
4. **Collect, label and train** with `training/README.md` and the Colab notebook.
5. **Test and report** with `docs/D_Testing_and_Validation.md`.

## Package map

| Package | Content | Location |
|---|---|---|
| A Hardware | block diagram, wiring diagram, GPIO table, BOM, chamber/tray, controls | `docs/A_Hardware.md` |
| B AI training | Colab notebook, data YAMLs, hyper-parameter YAMLs, Label Studio configs, prepare/check/zip tools, train/validate/export/learning-curve scripts, requirements, README | `training/` |
| C Pi software | complete Python project, installer, autostart files, unit tests | `pcbx_inspection/`, `docs/C_Pi_Software_Roadmap.md` |
| D Testing | procedures D1–D9 with pass criteria and record templates | `docs/D_Testing_and_Validation.md` |

## What has been verified, and what has not

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
or **[MUST TEST]**.

## Folder overview

```
PCBX_Capstone/
├── README.md
├── docs/
│   ├── 00_Technical_Review.md
│   ├── A_Hardware.md
│   ├── C_Pi_Software_Roadmap.md
│   └── D_Testing_and_Validation.md
├── training/                       (Package B)
└── pcbx_inspection/                (Package C)
```
