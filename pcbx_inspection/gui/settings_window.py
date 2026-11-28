"""
gui/settings_window.py - NEW in V2: Settings (one window, four tabs).

  Profile & model   choose the PCB profile, see model/golden/board-profile status
  Inspection        mode (dual / flip), flip camera, flipped insertion, LEDs, logging
  Tolerances        per-side thresholds + default tolerances + per-component
                    tolerances (table, double-click a row to edit)
  Golden JSON       the raw golden_reference.json in a text editor

Safety rules for edits:
  * every value is checked before saving (inspection/golden_reference.validate_golden,
    config.validate_override); an invalid configuration cannot be saved
  * the previous golden_reference.json is copied to models/<profile>/backups/
    and the file is replaced atomically; "Restore backup" brings any version back
  * the revision number increases with every save and is written into every
    inspection record, so results before and after a tolerance change can be told apart
  * the running system reloads the saved file immediately; the main screen shows
    the new revision
"""
import copy
import json
import tkinter as tk
from tkinter import messagebox, ttk

import config as C
from inspection import golden_reference as gr
from inspection.profile import ModelError, Profile, ProfileError, list_profiles


def _f(text, allow_blank=False):
    text = str(text).strip()
    if text == "" and allow_blank:
        return None
    return float(text)


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        self.sys = app.system
        self.win = tk.Toplevel(app.root)
        self.win.title("Settings")
        self.win.geometry("900x540")
        self.win.transient(app.root)
        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True)
        self.tabs = {}
        for name in ("Profile & model", "Inspection", "Tolerances", "Golden JSON"):
            f = ttk.Frame(nb, padding=8)
            nb.add(f, text=name)
            self.tabs[name] = f
        self.work = copy.deepcopy(self.sys.golden) if self.sys.golden else None
        self.dirty = False
        self._profile_tab()
        self._inspection_tab()
        self._tolerance_tab()
        self._json_tab()

    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    # ================================================================== profile
    def _profile_tab(self):
        f = self.tabs["Profile & model"]
        names = [p["name"] for p in list_profiles(C.MODELS_DIR)]
        ttk.Label(f, text="PCB profile (folder in models/):").grid(row=0, column=0, sticky="w")
        self.profile_var = tk.StringVar(value=self.sys.profile_name)
        cb = ttk.Combobox(f, textvariable=self.profile_var, values=names, state="readonly", width=24)
        cb.grid(row=0, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._show_profile_status())
        ttk.Button(f, text="Check", command=self._show_profile_status).grid(row=0, column=2, padx=4)
        ttk.Button(f, text="Use this profile", command=self._apply_profile).grid(row=0, column=3)
        self.prof_text = tk.Text(f, height=24, width=110, font=("DejaVu Sans Mono", 9))
        self.prof_text.grid(row=1, column=0, columnspan=4, sticky="nsew", pady=6)
        f.rowconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)
        self._show_profile_status()

    def _show_profile_status(self):
        t = self.prof_text
        t.delete("1.0", "end")
        name = self.profile_var.get()
        try:
            p = Profile(C.MODELS_DIR, name)
        except ProfileError as exc:
            t.insert("end", f"PROFILE ERROR: {exc}\n")
            return
        t.insert("end", f"Board: {p.board_name}   size {p.board_size} mm   folder {p.dir}\n\n")
        for side in p.sides():
            t.insert("end", f"{C.SIDE_LABELS[side]}  classes: {', '.join(p.classes(side))}\n")
            try:
                info = p.check_model_files(side, C.PREFER_NCNN)
                t.insert("end", f"   model OK: {info['format']}  {info['path']}  imgsz {info['imgsz']}\n")
            except ModelError as exc:
                t.insert("end", f"   MODEL PROBLEM: {exc}\n")
        t.insert("end", "\nReadiness check (files only, models are loaded when applied):\n")
        probs = p.problems(C.PREFER_NCNN)
        t.insert("end", "   READY\n" if not probs else "".join(f"   - {x}\n" for x in probs))
        loaded = self.sys.detectors
        t.insert("end", f"\nCurrently loaded models: "
                        f"{ {s: getattr(d, 'format', '?') for s, d in loaded.items()} or 'none'}\n")

    def _apply_profile(self):
        try:
            C.save_settings_file({"ACTIVE_PROFILE": self.profile_var.get()})
        except ValueError as exc:
            messagebox.showerror("Profile", str(exc), parent=self.win)
            return
        self.sys.profile_name = self.profile_var.get()
        self.app.request_reload()
        messagebox.showinfo("Profile", "Profile saved. Models are being (re)loaded - watch the "
                                       "status line.", parent=self.win)

    # ================================================================== inspection
    def _inspection_tab(self):
        f = self.tabs["Inspection"]
        self.mode = tk.StringVar(value=C.INSPECTION_MODE)
        self.flipcam = tk.StringVar(value=C.FLIP_CAMERA)
        self.allowflip = tk.BooleanVar(value=C.ALLOW_FLIPPED_INSERTION)
        self.saveraw = tk.BooleanVar(value=C.SAVE_RAW_IMAGES)
        self.door = tk.BooleanVar(value=C.REQUIRE_DOOR_CLOSED)
        self.bright = tk.DoubleVar(value=C.LIGHTING["brightness"])
        self.settle = tk.StringVar(value=str(C.LED_SETTLE_S))
        row = 0
        ttk.Label(f, text="Inspection mode").grid(row=row, column=0, sticky="w")
        ttk.Radiobutton(f, text="dual - two cameras, one insertion (recommended)",
                        variable=self.mode, value="dual").grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Radiobutton(f, text="flip - one camera, operator flips the board",
                        variable=self.mode, value="flip").grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Label(f, text="Camera used in flip mode").grid(row=row, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.flipcam, values=list(C.CAMERAS), state="readonly",
                     width=10).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Checkbutton(f, text="dual mode: accept a board inserted upside-down (sides are "
                                "identified from the markings)", variable=self.allowflip
                        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        row += 1
        ttk.Label(f, text="LED brightness (0.05-1.0)").grid(row=row, column=0, sticky="w")
        ttk.Scale(f, from_=0.05, to=1.0, variable=self.bright, length=250).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Label(f, text="LED settle time before capture (s, 0-3)").grid(row=row, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.settle, width=8).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Checkbutton(f, text="save raw camera images (needed for retraining)",
                        variable=self.saveraw).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(f, text="require drawer/door switch closed", variable=self.door
                        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        cams = "\n".join(f"  {n}: {c['backend']} camera_num={c.get('camera_num')} "
                         f"{c['width']}x{c['height']}  calibration={c['calibration_file']}"
                         for n, c in C.CAMERAS.items())
        ttk.Label(f, text="Cameras (edit config.py for camera numbers, exposure, focus):\n" + cams,
                  foreground="#555").grid(row=row, column=0, columnspan=2, sticky="w", pady=8)
        row += 1
        ttk.Button(f, text="Save and apply", command=self._save_inspection).grid(row=row, column=1,
                                                                                sticky="e")

    def _save_inspection(self):
        try:
            vals = {"INSPECTION_MODE": self.mode.get(), "FLIP_CAMERA": self.flipcam.get(),
                    "ALLOW_FLIPPED_INSERTION": bool(self.allowflip.get()),
                    "LED_BRIGHTNESS": round(float(self.bright.get()), 2),
                    "LED_SETTLE_S": float(self.settle.get()),
                    "SAVE_RAW_IMAGES": bool(self.saveraw.get()),
                    "REQUIRE_DOOR_CLOSED": bool(self.door.get())}
            C.save_settings_file(vals)
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Settings", f"Not saved: {exc}", parent=self.win)
            return
        self.app.request_reload()
        messagebox.showinfo("Settings", "Saved to config/settings.json and applied.",
                            parent=self.win)

    # ================================================================== tolerances
    def _tolerance_tab(self):
        f = self.tabs["Tolerances"]
        if self.work is None:
            ttk.Label(f, text="No valid golden reference loaded - build it first "
                              "(tools/build_golden_reference.py) or fix it in the Golden JSON tab."
                      ).pack(anchor="w")
            return
        top = ttk.Frame(f)
        top.pack(fill="x")
        self.side = tk.StringVar(value=next(iter(self.work["sides"])))
        ttk.Label(top, text="Side").pack(side="left")
        cb = ttk.Combobox(top, textvariable=self.side, values=list(self.work["sides"]),
                          state="readonly", width=8)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._load_side())
        self.vars = {k: tk.StringVar() for k in ("t_low", "t_high", "tol_mm", "tol_x_mm", "tol_y_mm")}
        for k, lab in (("t_low", "T_low"), ("t_high", "T_high"), ("tol_mm", "default tol (mm)"),
                       ("tol_x_mm", "tol X"), ("tol_y_mm", "tol Y")):
            ttk.Label(top, text=lab).pack(side="left", padx=(8, 2))
            ttk.Entry(top, textvariable=self.vars[k], width=6).pack(side="left")
        ttk.Label(f, text="Blank tol X / tol Y = not checked. Component values override the "
                          "default; blank = use default. Double-click a row to edit.",
                  foreground="#555").pack(anchor="w", pady=2)
        cols = ("id", "class", "x_mm", "y_mm", "tol_mm", "tol_x_mm", "tol_y_mm", "required", "eff")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=13)
        for c, w in zip(cols, (70, 130, 70, 70, 70, 70, 70, 70, 170)):
            self.tree.heading(c, text="effective tol" if c == "eff" else c)
            self.tree.column(c, width=w)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._edit_component)
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=4)
        self.tol_status = ttk.Label(bar, text="")
        self.tol_status.pack(side="left")
        ttk.Button(bar, text="Save (validate + backup)", command=self._save_tolerances).pack(side="right")
        ttk.Button(bar, text="Restore backup...", command=self._restore).pack(side="right", padx=4)
        ttk.Button(bar, text="Discard changes", command=self._revert).pack(side="right")
        self._load_side()

    def _load_side(self):
        sd = self.work["sides"][self.side.get()]
        th = sd.get("thresholds", {})
        dt = sd.get("default_tolerance", {})
        for k, v in (("t_low", th.get("t_low", 0.25)), ("t_high", th.get("t_high", 0.6)),
                     ("tol_mm", dt.get("tol_mm", 1.0)), ("tol_x_mm", dt.get("tol_x_mm")),
                     ("tol_y_mm", dt.get("tol_y_mm"))):
            self.vars[k].set("" if v is None else str(v))
        self._refresh_tree()

    def _refresh_tree(self):
        sd = self.work["sides"][self.side.get()]
        self.tree.delete(*self.tree.get_children())
        for c in sd.get("components", []):
            e = gr.effective_tolerance(sd, c)
            eff = f"r {e['tol_mm']}" + (f" x {e['tol_x_mm']}" if e["tol_x_mm"] else "") + \
                  (f" y {e['tol_y_mm']}" if e["tol_y_mm"] else "")
            self.tree.insert("", "end", iid=c["id"], values=(
                c["id"], c["class"], c["x_mm"], c["y_mm"],
                *("" if c.get(k) is None else c.get(k) for k in ("tol_mm", "tol_x_mm", "tol_y_mm")),
                c.get("required", True), eff))
        rev = self.sys.golden.get("revision", "?") if self.sys.golden else "?"
        self.tol_status.configure(text=f"file revision {rev}" + ("   * unsaved changes" if self.dirty else ""))

    def _read_side_fields(self):
        """Copy the entry fields into the working copy. Raises ValueError."""
        sd = self.work["sides"][self.side.get()]
        sd["thresholds"] = {"t_low": _f(self.vars["t_low"].get()),
                            "t_high": _f(self.vars["t_high"].get())}
        sd["default_tolerance"] = {"tol_mm": _f(self.vars["tol_mm"].get()),
                                   "tol_x_mm": _f(self.vars["tol_x_mm"].get(), True),
                                   "tol_y_mm": _f(self.vars["tol_y_mm"].get(), True)}

    def _edit_component(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        sd = self.work["sides"][self.side.get()]
        comp = next(c for c in sd["components"] if c["id"] == sel[0])
        dlg = tk.Toplevel(self.win)
        dlg.title(f"Edit {comp['id']} ({comp['class']})")
        dlg.transient(self.win)
        vals = {k: tk.StringVar(value="" if comp.get(k) is None else str(comp.get(k)))
                for k in ("tol_mm", "tol_x_mm", "tol_y_mm")}
        req = tk.BooleanVar(value=comp.get("required", True))
        for i, (k, lab) in enumerate((("tol_mm", "radial tolerance (mm, blank = default)"),
                                      ("tol_x_mm", "X tolerance (mm, blank = default/none)"),
                                      ("tol_y_mm", "Y tolerance (mm, blank = default/none)"))):
            ttk.Label(dlg, text=lab).grid(row=i, column=0, sticky="w", padx=6, pady=2)
            ttk.Entry(dlg, textvariable=vals[k], width=8).grid(row=i, column=1, padx=6)
        ttk.Checkbutton(dlg, text="required (missing = FAIL; unticked: missing = REVIEW)",
                        variable=req).grid(row=3, column=0, columnspan=2, sticky="w", padx=6)

        def ok():
            try:
                new = {k: _f(v.get(), True) for k, v in vals.items()}
                for k, v in new.items():
                    if v is not None and not gr.TOL_RANGE[0] <= v <= gr.TOL_RANGE[1]:
                        raise ValueError(f"{k} must be {gr.TOL_RANGE[0]}..{gr.TOL_RANGE[1]} mm")
            except ValueError as exc:
                messagebox.showerror("Invalid value", str(exc), parent=dlg)
                return
            comp.update(new)
            comp["required"] = bool(req.get())
            self.dirty = True
            self._refresh_tree()
            dlg.destroy()
        ttk.Button(dlg, text="OK", command=ok).grid(row=4, column=1, pady=6)

    def _save_tolerances(self):
        try:
            self._read_side_fields()
        except ValueError:
            messagebox.showerror("Tolerances", "Thresholds and tolerances must be numbers "
                                               "(tol X / tol Y may be blank).", parent=self.win)
            return
        ok = messagebox.askyesno(
            "Save golden reference",
            "Saving changes the PASS/FAIL/REVIEW limits for every inspection from now on.\n"
            "The current file is backed up and the revision number increases.\n\nSave?",
            parent=self.win)
        if not ok:
            return
        try:
            saved = gr.save_golden_safe(self.sys.profile.golden_path, self.work, "gui",
                                        self.sys.profile.classes_by_side())
        except gr.GoldenError as exc:
            messagebox.showerror("Not saved", str(exc), parent=self.win)
            return
        _, warns = gr.validate_golden(saved, self.sys.profile.classes_by_side())
        self.sys.golden = saved
        self.work = copy.deepcopy(saved)
        self.dirty = False
        self.app.request_reload(golden_only=True)
        self._refresh_tree()
        self._load_json()
        messagebox.showinfo("Saved", f"Saved revision {saved['revision']}. Inspections from now "
                                     "on use this revision (it is written into every record)."
                            + ("\n\nWarnings:\n" + "\n".join(warns[:5]) if warns else ""),
                            parent=self.win)

    def _revert(self):
        self.work = copy.deepcopy(self.sys.golden)
        self.dirty = False
        self._load_side()

    def _restore(self):
        backs = gr.list_backups(self.sys.profile.golden_path)
        if not backs:
            messagebox.showinfo("Backups", "No backups yet.", parent=self.win)
            return
        dlg = tk.Toplevel(self.win)
        dlg.title("Restore a backup")
        lb = tk.Listbox(dlg, width=70, height=12)
        for b in backs:
            lb.insert("end", b.name)
        lb.pack(padx=6, pady=6)

        def go():
            if not lb.curselection():
                return
            b = backs[lb.curselection()[0]]
            try:
                saved = gr.restore_backup(self.sys.profile.golden_path, b,
                                          self.sys.profile.classes_by_side())
            except gr.GoldenError as exc:
                messagebox.showerror("Not restored", str(exc), parent=dlg)
                return
            self.sys.golden = saved
            self._revert()
            self._load_json()
            self.app.request_reload(golden_only=True)
            dlg.destroy()
            messagebox.showinfo("Restored", f"{b.name} restored as revision {saved['revision']}.",
                                parent=self.win)
        ttk.Button(dlg, text="Restore selected", command=go).pack(pady=4)

    # ================================================================== raw JSON
    def _json_tab(self):
        f = self.tabs["Golden JSON"]
        ttk.Label(f, text="Advanced: edit golden_reference.json directly. Save validates the "
                          "whole file first and keeps a backup.", foreground="#555").pack(anchor="w")
        self.json_text = tk.Text(f, font=("DejaVu Sans Mono", 9), undo=True)
        self.json_text.pack(fill="both", expand=True)
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Validate", command=self._validate_json).pack(side="left")
        ttk.Button(bar, text="Reload from file", command=self._load_json).pack(side="left", padx=4)
        ttk.Button(bar, text="Save", command=self._save_json).pack(side="right")
        self._load_json()

    def _load_json(self):
        self.json_text.delete("1.0", "end")
        p = self.sys.profile.golden_path if self.sys.profile else None
        if p is not None and p.exists():
            self.json_text.insert("1.0", p.read_text())

    def _parse_json(self):
        try:
            return json.loads(self.json_text.get("1.0", "end"))
        except json.JSONDecodeError as exc:
            messagebox.showerror("JSON syntax error", f"Line {exc.lineno}, column {exc.colno}: "
                                                      f"{exc.msg}", parent=self.win)
            return None

    def _validate_json(self):
        data = self._parse_json()
        if data is None:
            return None
        errs, warns = gr.validate_golden(data, self.sys.profile.classes_by_side())
        if errs:
            messagebox.showerror("Invalid", "\n".join(errs[:15]), parent=self.win)
            return None
        messagebox.showinfo("Valid", "The golden reference is valid."
                            + ("\n\nWarnings:\n" + "\n".join(warns[:6]) if warns else ""),
                            parent=self.win)
        return data

    def _save_json(self):
        data = self._parse_json()
        if data is None:
            return
        try:
            saved = gr.save_golden_safe(self.sys.profile.golden_path, data, "gui-json",
                                        self.sys.profile.classes_by_side())
        except gr.GoldenError as exc:
            messagebox.showerror("Not saved", str(exc), parent=self.win)
            return
        self.sys.golden = saved
        self._revert() if self.work is not None else None
        self._load_json()
        self.app.request_reload(golden_only=True)
        messagebox.showinfo("Saved", f"Saved revision {saved['revision']}.", parent=self.win)
