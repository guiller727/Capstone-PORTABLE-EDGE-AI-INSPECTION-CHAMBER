"""
storage/result_logger.py - one CSV row per board + one JSON file per board.

logs/results.csv  : easy to open in Excel for Chapter 4 statistics
logs/<date>/<board_id>/result.json : every component, every rule, timings
logs/app.log      : program messages (rotating, max 5 x 2 MB)
"""
import csv
import json
import logging
import logging.handlers
from pathlib import Path

# top = FRONT (Side A), bottom = BACK (Side B)
CSV_FIELDS = ["board_id", "timestamp", "verdict", "operator_decision", "top_verdict",
              "bottom_verdict", "n_fail", "n_review", "flagged", "total_s",
              "capture_s", "inference_ms_top", "inference_ms_bottom",
              "top_alignment", "bottom_alignment", "top_camera", "bottom_camera",
              "mode", "profile", "golden_revision", "golden_hash", "notes", "folder"]


def setup_app_logging(logs_dir: Path, level=logging.INFO):
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        fh = logging.handlers.RotatingFileHandler(logs_dir / "app.log", maxBytes=2_000_000,
                                                  backupCount=5)
        fh.setFormatter(fmt)
        root.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


class ResultLogger:
    def __init__(self, logs_dir: Path):
        self.logs_dir = Path(logs_dir)
        self.csv_path = self.logs_dir / "results.csv"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if self.csv_path.exists():
            with open(self.csv_path, newline="") as f:
                header = next(csv.reader(f), [])
            if header != CSV_FIELDS:            # V1 file: keep it, start a new one
                self.csv_path.rename(self.logs_dir / "results_v1.csv")
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="") as f:
                csv.DictWriter(f, CSV_FIELDS).writeheader()

    def write(self, folder: Path, record: dict):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "result.json").write_text(json.dumps(record, indent=2, default=str))
        row = {k: record.get(k, "") for k in CSV_FIELDS}
        row["folder"] = str(folder)
        with open(self.csv_path, "a", newline="") as f:
            csv.DictWriter(f, CSV_FIELDS).writerow(row)

    def read_rows(self, limit=500):
        """Most recent rows first (for the History window). Later rows for the
        same board (operator decision) replace earlier ones."""
        if not self.csv_path.exists():
            return []
        with open(self.csv_path, newline="") as f:
            rows = list(csv.DictReader(f))
        latest = {}
        for r in rows:
            latest[r["board_id"]] = r
        return list(reversed(list(latest.values())))[:limit]

    def set_operator_decision(self, folder: Path, decision: str):
        """Store the operator's final call for a REVIEW board (keeps CSV append-only:
        writes a second row marked with the decision)."""
        p = folder / "result.json"
        if not p.exists():
            return
        rec = json.loads(p.read_text())
        rec["operator_decision"] = decision
        p.write_text(json.dumps(rec, indent=2, default=str))
        row = {k: rec.get(k, "") for k in CSV_FIELDS}
        row["folder"] = str(folder)
        with open(self.csv_path, "a", newline="") as f:
            csv.DictWriter(f, CSV_FIELDS).writerow(row)
