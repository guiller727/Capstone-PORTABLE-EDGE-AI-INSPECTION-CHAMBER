"""
gui/history_window.py - NEW in V2: inspection history (from logs/results.csv).

Shows the latest 500 boards (newest first) with verdict, operator decision,
front/back verdicts and flagged parts. Buttons: open the board's folder,
export an HTML report for the selected board, export the CSV.
"""
import os
import platform
import shutil
import subprocess
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import config as C
from storage import make_html_report


def _open(path: Path):
    try:
        if platform.system() == "Windows":
            os.startfile(str(path))                       # noqa: S606
        elif path.suffix == ".html":
            webbrowser.open(path.resolve().as_uri())
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        messagebox.showerror("Open", f"Cannot open {path}: {exc}")


class HistoryWindow:
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("Inspection history")
        self.win.geometry("980x500")
        self.win.transient(app.root)
        top = ttk.Frame(self.win, padding=4)
        top.pack(fill="x")
        self.filter = tk.StringVar(value="ALL")
        ttk.Label(top, text="Show").pack(side="left")
        cb = ttk.Combobox(top, textvariable=self.filter, values=["ALL", "PASS", "FAIL", "REVIEW"],
                          state="readonly", width=8)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.summary = ttk.Label(top, text="")
        self.summary.pack(side="left", padx=10)
        cols = ("timestamp", "board_id", "verdict", "operator", "front", "back", "rev", "flagged")
        self.tree = ttk.Treeview(self.win, columns=cols, show="headings")
        for c, w in zip(cols, (140, 170, 70, 70, 60, 60, 40, 360)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w)
        for v, col in (("PASS", "#1f9d3a"), ("FAIL", "#c62828"), ("REVIEW", "#e65100")):
            self.tree.tag_configure(v, foreground=col)
        self.tree.pack(fill="both", expand=True)
        bar = ttk.Frame(self.win, padding=4)
        bar.pack(fill="x")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(bar, text="Open folder", command=self.open_folder).pack(side="left", padx=4)
        ttk.Button(bar, text="Export HTML report", command=self.export_report).pack(side="left")
        ttk.Button(bar, text="Export CSV", command=self.export_csv).pack(side="left", padx=4)
        self.rows = {}
        self.refresh()

    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        rows = self.app.system.result_logger.read_rows()
        counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0}
        self.rows = {}
        for r in rows:
            counts[r.get("verdict")] = counts.get(r.get("verdict"), 0) + 1
            if self.filter.get() != "ALL" and r.get("verdict") != self.filter.get():
                continue
            iid = r["board_id"]
            self.rows[iid] = r
            self.tree.insert("", "end", iid=iid, tags=(r.get("verdict"),), values=(
                r.get("timestamp"), r["board_id"], r.get("verdict"), r.get("operator_decision"),
                r.get("top_verdict"), r.get("bottom_verdict"), r.get("golden_revision"),
                r.get("flagged", "")[:120]))
        self.summary.configure(text=f"{len(rows)} boards: PASS {counts['PASS']}  "
                                    f"FAIL {counts['FAIL']}  REVIEW {counts['REVIEW']}")

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("History", "Select a board first.", parent=self.win)
            return None
        return Path(self.rows[sel[0]]["folder"])

    def open_folder(self):
        folder = self._selected()
        if folder is not None:
            _open(folder)

    def export_report(self):
        folder = self._selected()
        if folder is None:
            return
        try:
            out = make_html_report(folder)
        except Exception as exc:
            messagebox.showerror("Report", f"Could not create report: {exc}", parent=self.win)
            return
        messagebox.showinfo("Report", f"Saved {out}", parent=self.win)
        _open(out)

    def export_csv(self):
        src = self.app.system.result_logger.csv_path
        dst_dir = C.LOGS_DIR / "exports"
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"results_{datetime.now():%Y%m%d_%H%M%S}.csv"
        shutil.copy2(src, dst)
        messagebox.showinfo("Export", f"Saved {dst}\n(copy it to a USB stick or laptop)",
                            parent=self.win)
