# models/  - one folder per PCB profile (V2)

```
models/pcb_x/
├── metadata.json                 board size, sides, classes, model paths + image size   (shipped)
├── golden_reference.example.json format example (rough positions!)                      (shipped)
├── board_profile.example.json    format example for identification markers + holes       (shipped)
├── golden_reference.json         YOUR expected components   <- tools/build_golden_reference.py
├── board_profile.json            YOUR markers + mounting holes <- tools/build_board_profile.py
├── templates/                    marker / whole-board template images (created by the tool)
├── backups/                      automatic backups of golden_reference.json (GUI/tool saves)
├── top/                          FRONT (Side A) model: best.pt and/or best_ncnn_model/
└── bottom/                       BACK  (Side B) model: best.pt and/or best_ncnn_model/
```

No trained model is shipped - it must be trained on your own PCB X images.
`training/export.py --profile-dir pcbx_inspection/models/pcb_x` installs a
trained model here; `python tools/check_profile.py` confirms it loads.
The Pi uses `best_ncnn_model/` when present (fastest on the Pi 5 CPU) and
falls back to `best.pt`. A second PCB type = a second folder; choose it in
Settings > Profile & model.
