# Golden reference and tolerances (V2)

File: `pcbx_inspection/models/<profile>/golden_reference.json` — one file, both
sides. Format example with the real PCB X layout (rough positions!):
`models/pcb_x/golden_reference.example.json`. The schema is documented at the
top of `inspection/golden_reference.py`.

## 1. Structure

```json
{
  "schema_version": 2, "profile": "pcb_x", "board": "PCB X",
  "board_size_mm": [115.0, 45.0],
  "canvas": {"px_per_mm": 10.0, "margin_mm": 2.5},
  "revision": 4, "modified": "2026-12-10T14:02:11", "modified_by": "gui",
  "sides": {
    "top": {
      "label": "FRONT - Side A",
      "thresholds": {"t_low": 0.25, "t_high": 0.60},
      "default_tolerance": {"tol_mm": 1.0, "tol_x_mm": null, "tol_y_mm": null},
      "class_tolerance": {"transformer": {"tol_mm": 1.5}},
      "built_from": {"images": 30, "boards": 10, "date": "2026-12-10"},
      "components": [
        {"id": "T1", "class": "transformer", "x_mm": 66.2, "y_mm": 19.8,
         "w_mm": 24.0, "h_mm": 22.0, "x_norm": 0.5757, "y_norm": 0.44,
         "tol_mm": null, "tol_x_mm": null, "tol_y_mm": null, "required": true,
         "std_x_mm": 0.05, "std_y_mm": 0.04, "seen": 30}
      ]
    },
    "bottom": { "...": "same structure" }
  }
}
```

| Field | Meaning |
|---|---|
| `x_mm, y_mm` | expected centre, mm from the top-left corner of that side (after identification/orientation) |
| `w_mm, h_mm` | expected size (used for drawing a MISSING box) |
| `x_norm, y_norm` | same position as a fraction of board width/height — written automatically, informational |
| `tol_mm` | max **radial** offset √(dx²+dy²) |
| `tol_x_mm`, `tol_y_mm` | max offset along X / Y (null = not checked) |
| `required` | true: missing → FAIL · false: missing → REVIEW |
| `std_*`, `seen` | repeatability measured while building (evidence for your tolerance choice) |
| `thresholds.t_low` | detections below this are ignored |
| `thresholds.t_high` | detections below this are "uncertain" → REVIEW (never FAIL) |

**Why millimetres?** Positions in mm on the normalised board are already
independent of camera resolution, zoom and px/mm, and tolerances from the
partner company / IPC-A-610 are given in mm. Normalised values (0–1) are
stored too for readability, but x and y have different scales in them, so
they are not used for tolerance checks.

**Tolerance resolution** (first non-null wins): component → `class_tolerance[class]` → `default_tolerance` → 1.0 mm.

## 2. Creating it

1. Known-good boards (not test boards), 10+ boards × 3 insertions, captured with
   `tools/capture_dataset.py --board Bxx --note good` (images land in
   `dataset_capture/canvas/top` and `.../bottom` automatically).
2. `python tools/build_golden_reference.py --side top --images dataset_capture/canvas/top --seed-label <one hand-checked label .txt>`
3. Same for `--side bottom`.
4. Rename the IDs to the silkscreen designators (Settings > Golden JSON, or a text editor).
5. Set tolerances with the partner company (Settings > Tolerances).

Tolerance built automatically = max(class default from `config.DEFAULT_TOL_MM`,
4 × measured radial standard deviation), so a tolerance is never tighter than
the system's own repeatability.

## 3. Editing in the GUI (Settings window)

* **Tolerances tab:** choose side → edit `T_low`, `T_high`, default radial/X/Y
  tolerance → double-click a component to override its tolerances or untick
  "required" → **Save (validate + backup)**.
* **Golden JSON tab:** full text editor with **Validate** and **Save**.
* **Restore backup…:** pick any earlier revision.

What protects the file:

| Protection | How |
|---|---|
| Invalid input cannot be saved | `validate_golden()`: numbers, ranges (0.05–10 mm), 0 < t_low < t_high < 1, unique IDs, class names of that side's model, positions on the board, no empty side |
| Original preserved | old file copied to `models/<profile>/backups/golden_reference.rev<N>.<time>.json` (last 30 kept) |
| No half-written file | written to a temp file, then renamed (atomic) |
| Effect is visible | `revision` +1; main screen header shows `golden rev N`; every result (CSV + JSON + HTML report) records `golden_revision` and a `golden_hash` |
| Confirmation | "Saving changes the PASS/FAIL/REVIEW limits…" dialog |
| Ambiguity warning | if two same-class parts' tolerance circles overlap, a warning is shown (matches there become AMBIGUOUS → REVIEW) |

Manual editing with a text editor is allowed; the program validates the file
when it starts and refuses to inspect with an invalid one ("NOT READY" + the
exact error). Run `python tools/check_profile.py` after manual edits.

## 4. Decision rules (summary — full table in `inspection/decision_engine.py`)

| Situation | Status | Board |
|---|---|---|
| required part not detected | MISSING | FAIL |
| optional part not detected | MISSING_OPTIONAL | REVIEW |
| detected, confidence < t_high | UNCERTAIN | REVIEW |
| confident, wrong class | WRONG_TYPE | FAIL |
| confident, outside tol_mm / tol_x / tol_y | MISPLACED | FAIL |
| confident, inside tolerance of two same-class parts | AMBIGUOUS | REVIEW |
| confident unexpected part | EXTRA | REVIEW |
| side not identified / orientation ambiguous / capture unusable / no model | side REVIEW | REVIEW |
| holes not found (coarse alignment) | PASS → REVIEW | REVIEW |

Front + back: **FAIL > REVIEW > PASS** (a confirmed defect is never hidden by an uncertainty).
