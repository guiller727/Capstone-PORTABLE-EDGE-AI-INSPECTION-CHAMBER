# models/

Put the exported NCNN model FOLDERS here (from the Colab notebook or
`training/export.py`). Expected names (see `config.py` → `MODELS`):

```
models/
├── top_best_ncnn_model/        (model.ncnn.param, model.ncnn.bin, metadata.yaml)
└── bottom_best_ncnn_model/
```

* Copy the whole folder, not only the `.bin` file — `metadata.yaml` holds the
  class names and image size, and `Detector` checks that the class list matches
  `config.py` (so a swapped top/bottom model is caught at start-up).
* The `imgsz` in `config.py` must equal the size used at export
  (default top `(288, 640)`, bottom `(512, 1216)`).
* For testing on a laptop you may point `MODELS[...]["path"]` to a `best.pt`
  file instead; Ultralytics loads both.
