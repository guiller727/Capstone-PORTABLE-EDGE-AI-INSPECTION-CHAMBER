# models/pcb_x/bottom/  (BACK - Side B model)

Put the trained model for this side HERE (nothing is shipped - no fake model):

```
best.pt              trained weights from training (runs/bottom/.../weights/best.pt)
best_ncnn_model/     NCNN export (model.ncnn.param, model.ncnn.bin, metadata.yaml)
```

`training/export.py --side bottom --weights <best.pt> --profile-dir ../pcbx_inspection/models/pcb_x`
copies both here and updates `metadata.json`. The Pi uses `best_ncnn_model/` when it exists
(faster) and falls back to `best.pt`. See docs/MODEL_INTEGRATION.md.
