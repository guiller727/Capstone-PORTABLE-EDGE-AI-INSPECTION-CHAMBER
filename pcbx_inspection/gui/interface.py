"""
gui/interface.py - Tkinter operator screen (V2; V1 layout and threading kept).

 +----------------------------------------------------------------------------+
 | PCB X Inspection   profile pcb_x | mode dual        status / progress       |
 |                  [  PASS / FAIL / REVIEW / FLIP THE BOARD  ]                |
 | FRONT - Side A  (camera, identified by, orientation, alignment)  +---------+ |
 | +-----------------------------------------------------------+  | flagged | |
 | |  overlay / live preview                                   |  | parts   | |
 | +-----------------------------------------------------------+  | table   | |
 | BACK - Side B   (...)                                          | [START] | |
 | +-----------------------------------------------------------+  | [FINISH]| |
 | |  overlay                                                  |  | Op PASS | |
 | +-----------------------------------------------------------+  | Op FAIL | |
 | last result 2026-11-27 21:48:03 | rev 4                         | Preview | |
 |                                                                 | Settings| |
 |                                                                 | History | |
 +----------------------------------------------------------------------------+

Threading rule (unchanged): Tkinter only in the main thread. Camera, YOLO,
logging and preview run in ONE worker thread; commands go in via cmd_q,
results come back via ui_q (polled every 50 ms). The physical START button
only puts a command into the queue.
"""
import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageTk

import config as C
from gui.overlay import message_image

log = logging.getLogger(__name__)

COLORS = {"PASS": "#1f9d3a", "FAIL": "#c62828", "REVIEW": "#ef8c00", "READY": "#455a64",
          "BUSY": "#1565c0", "WARN": "#6a1b9a", "ERROR": "#000000", "FLIP": "#00838f"}
PROMPTS = {"WRONG_SIDE": "FLIP THE BOARD", "NO_BOARD": "NO BOARD", "DOOR_OPEN": "CLOSE THE DOOR",
           "ERROR": "CAPTURE ERROR - TRY AGAIN", "NOT_READY": "NOT READY",
           "FLIP_PROMPT": "FLIP THE BOARD, PRESS START", "SAME_SIDE": "SAME SIDE AGAIN - FLIP",
           "IDLE": "READY"}
STATUS_ORDER = {"MISSING": 0, "WRONG_TYPE": 0, "MISPLACED": 0, "UNCERTAIN": 1, "AMBIGUOUS": 1,
                "EXTRA": 1, "MISSING_OPTIONAL": 1, "OK": 3}


class App:
    def __init__(self, system, inputs=None, start_worker=True):
        self.system = system
        self.inputs = inputs
        self.cmd_q, self.ui_q = queue.Queue(), queue.Queue()
        self.busy = True
        self.preview_cam = None
        self.last_folder = None
        self.counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0}
        self.settings_win = self.history_win = None

        self.root = tk.Tk()
        self.root.title("PCB X Inspection")
        if C.FULLSCREEN:
            self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry(f"{C.WINDOW_SIZE[0]}x{C.WINDOW_SIZE[1]}")
        self.root.configure(bg="#263238")
        self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))
        self.root.bind("<space>", lambda e: self.request_start())
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)
        self._build()
        if inputs is not None:
            inputs.on_start(self.request_start)          # called from GPIO thread
        if start_worker:
            threading.Thread(target=self._worker, daemon=True).start()
        self.root.after(50, self._poll)

    # ------------------------------------------------------------------ layout
    def _build(self):
        r = self.root
        st = ttk.Style(r)
        st.configure("Flag.Treeview", font=("DejaVu Sans", 9), rowheight=18)
        top = tk.Frame(r, bg="#263238")
        top.pack(fill="x")
        tk.Label(top, text=f"{C.BOARD_NAME} Inspection", fg="white", bg="#263238",
                 font=("DejaVu Sans", 14, "bold")).pack(side="left", padx=8, pady=4)
        self.profile_lbl = tk.Label(top, text="", fg="#90caf9", bg="#263238", font=("DejaVu Sans", 10))
        self.profile_lbl.pack(side="left", padx=8)
        self.status = tk.Label(top, text="Starting...", fg="#cfd8dc", bg="#263238",
                               font=("DejaVu Sans", 10))
        self.status.pack(side="right", padx=8)

        self.banner = tk.Label(r, text="STARTING", fg="white", bg=COLORS["BUSY"],
                               font=("DejaVu Sans", 26, "bold"), height=1)
        self.banner.pack(fill="x", padx=6, pady=(0, 3))

        body = tk.Frame(r, bg="#263238")
        body.pack(fill="both", expand=True, padx=6, pady=2)
        left = tk.Frame(body, bg="#263238")
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg="#263238", width=330)
        right.pack(side="right", fill="y", padx=(6, 0))
        right.pack_propagate(False)

        self.img_labels, self.side_info = {}, {}
        for side in ("top", "bottom"):
            hdr = tk.Frame(left, bg="#263238")
            hdr.pack(fill="x")
            tk.Label(hdr, text=C.SIDE_LABELS[side], fg="white", bg="#263238",
                     font=("DejaVu Sans", 10, "bold")).pack(side="left")
            info = tk.Label(hdr, text="", fg="#b0bec5", bg="#263238", font=("DejaVu Sans", 8),
                            anchor="w")
            info.pack(side="left", padx=6, fill="x", expand=True)
            self.side_info[side] = info
            lab = tk.Label(left, bg="#37474f")
            lab.pack(fill="both", expand=True, pady=(0, 3))
            self.img_labels[side] = lab
        self.footer = tk.Label(left, text="", fg="#90a4ae", bg="#263238", anchor="w",
                               font=("DejaVu Sans", 8))
        self.footer.pack(fill="x")

        cols = ("side", "id", "status", "dx", "dy")
        self.flags = ttk.Treeview(right, columns=cols, show="headings", height=7, style="Flag.Treeview")
        for c, w in zip(cols, (50, 52, 130, 46, 46)):
            self.flags.heading(c, text=c.upper())
            self.flags.column(c, width=w, anchor="w" if c in ("side", "id", "status") else "e")
        self.flags.tag_configure("FAIL", foreground="#c62828")
        self.flags.tag_configure("REVIEW", foreground="#e65100")
        self.flags.tag_configure("INFO", foreground="#455a64")
        self.flags.pack(fill="both", expand=True)
        self.full_text = {}
        self.flags.bind("<<TreeviewSelect>>", self._on_select_flag)
        self.details = tk.Label(right, text="", fg="#eceff1", bg="#37474f", anchor="nw",
                                justify="left", wraplength=315, font=("DejaVu Sans", 9), height=5)
        self.details.pack(fill="x", pady=(2, 0))

        self.start_btn = tk.Button(right, text="START", font=("DejaVu Sans", 20, "bold"),
                                   bg="#1565c0", fg="white", activebackground="#0d47a1",
                                   command=self.request_start, state="disabled", height=1)
        self.start_btn.pack(fill="x", pady=(5, 2))
        self.finish_btn = tk.Button(right, text="FINISH (record missing side as REVIEW)",
                                    command=lambda: self._send("finish_flip"), state="disabled")
        self.finish_btn.pack(fill="x")
        op = tk.Frame(right, bg="#263238")
        op.pack(fill="x", pady=2)
        self.op_pass = tk.Button(op, text="Operator PASS", state="disabled",
                                 command=lambda: self.operator("PASS"))
        self.op_fail = tk.Button(op, text="Operator FAIL", state="disabled",
                                 command=lambda: self.operator("FAIL"))
        self.op_pass.pack(side="left", expand=True, fill="x")
        self.op_fail.pack(side="left", expand=True, fill="x")
        self.count_lbl = tk.Label(right, text=self._count_text(), fg="white", bg="#263238",
                                  font=("DejaVu Sans", 10))
        self.count_lbl.pack(pady=2)
        tools = tk.Frame(right, bg="#263238")
        tools.pack(fill="x")
        self.preview_btn = tk.Button(tools, text="Preview: off", command=self.toggle_preview)
        self.preview_btn.pack(side="left", expand=True, fill="x")
        tk.Button(tools, text="Settings", command=self.open_settings).pack(side="left", expand=True, fill="x")
        tk.Button(tools, text="History", command=self.open_history).pack(side="left", expand=True, fill="x")
        tk.Button(tools, text="Exit", command=self.on_exit).pack(side="left", expand=True, fill="x")
        self._update_profile_label()

    def _update_profile_label(self):
        g = getattr(self.system, "golden", None) or {}
        self.profile_lbl.configure(
            text=f"profile {self.system.profile_name} | mode {C.INSPECTION_MODE} | "
                 f"golden rev {g.get('revision', '-')}")

    def _count_text(self):
        c = self.counts
        return f"PASS {c['PASS']}   FAIL {c['FAIL']}   REVIEW {c['REVIEW']}"

    # ------------------------------------------------------------------ helpers
    def _show_image(self, side, bgr):
        lab = self.img_labels[side]
        w = max(lab.winfo_width(), 200)
        h = max(lab.winfo_height(), 80)
        ih, iw = bgr.shape[:2]
        s = min(w / iw, h / ih)
        rgb = cv2.cvtColor(cv2.resize(bgr, (max(1, int(iw * s)), max(1, int(ih * s))),
                                      interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        lab.configure(image=photo)
        lab.image = photo                   # keep a reference (Tk garbage-collects)

    def _set_banner(self, text, key):
        self.banner.configure(text=text, bg=COLORS[key])

    def _send(self, cmd):
        self.cmd_q.put(cmd)

    def _clear_flags(self):
        self.flags.delete(*self.flags.get_children())
        self.full_text = {}
        self.details.configure(text="")

    def _add_flag(self, vals, tag, full):
        iid = self.flags.insert("", "end", values=vals, tags=(tag,))
        self.full_text[iid] = full

    def _on_select_flag(self, _e):
        sel = self.flags.selection()
        if sel:
            self.details.configure(text=self.full_text.get(sel[0], ""))

    def _fill_flags(self, out, only_inspected=False):
        self._clear_flags()
        rows = []
        for side, sr in (out.get("side_results") or {}).items():
            if only_inspected and not sr.inspected:
                continue
            tag = "FRONT" if side == "top" else "BACK"
            for f in sr.flags:
                rows.append((1, (tag, "-", f, "", ""), "REVIEW", f"{C.SIDE_LABELS[side]}: {f}"))
            for c in sr.components + sr.extras:
                if c.status in ("OK", "DUPLICATE", "NOISE"):
                    continue
                kind = "FAIL" if STATUS_ORDER.get(c.status, 1) == 0 else "REVIEW"
                rows.append((STATUS_ORDER.get(c.status, 1),
                             (tag, c.id, c.status, "" if c.dx_mm is None else f"{c.dx_mm:+.2f}",
                              "" if c.dy_mm is None else f"{c.dy_mm:+.2f}"), kind,
                             f"{C.SIDE_LABELS[side]}: {c.message}"))
            if sr.inspected:
                ok = sum(1 for c in sr.components if c.status == "OK")
                rows.append((4, (tag, "OK", f"{ok}/{len(sr.components)} parts", "", ""), "INFO",
                             f"{C.SIDE_LABELS[side]}: {ok} of {len(sr.components)} expected parts OK"))
        for note in out.get("notes", []):
            rows.append((5, ("NOTE", "", note, "", ""), "INFO", note))
        rows.sort(key=lambda r: r[0])
        for _, vals, tag, full in rows:
            self._add_flag(vals, tag, full)
        first = next((r[3] for r in rows if r[2] != "INFO"), rows[0][3] if rows else "")
        self.details.configure(text=first + ("\n(tap a row for details)" if len(rows) > 1 else ""))

    def _show_side_info(self, out):
        for side in ("top", "bottom"):
            i = (out.get("side_info") or {}).get(side)
            if not i:
                self.side_info[side].configure(text="not inspected")
                continue
            txt = f"cam {i.get('camera')} | "
            if i.get("status") == "capture_error":
                txt += f"capture error: {i.get('message', '')[:60]}"
            else:
                txt += (f"{i.get('identification', '')[:55]} | rotation {i.get('rotation_deg', 0)} deg"
                        f" | holes {i.get('fiducials', '-')} | {i.get('status')}")
            self.side_info[side].configure(text=txt)

    # ------------------------------------------------------------------ actions
    def request_start(self):
        if not self.busy and self.system.ready:
            self.busy = True
            self.cmd_q.put("inspect")

    def operator(self, decision):
        if self.last_folder is not None:
            self.system.result_logger.set_operator_decision(self.last_folder, decision)
            self.status.configure(text=f"Operator decision saved: {decision}")
        self.op_pass.configure(state="disabled")
        self.op_fail.configure(state="disabled")

    def toggle_preview(self):
        cams = [c for c in C.CAMERA_ORDER if c in self.system.cameras]
        order = [None] + cams
        nxt = order[(order.index(self.preview_cam) + 1) % len(order)] if self.preview_cam in order else None
        self.preview_cam = nxt
        self.preview_btn.configure(text=f"Preview: {nxt or 'off'}")
        self.cmd_q.put(("preview", nxt))

    def open_settings(self):
        from gui.settings_window import SettingsWindow
        if self.settings_win is None or not self.settings_win.alive():
            self.settings_win = SettingsWindow(self)

    def open_history(self):
        from gui.history_window import HistoryWindow
        if self.history_win is None or not self.history_win.alive():
            self.history_win = HistoryWindow(self)

    def request_reload(self, golden_only=False):
        self.busy = True
        self.start_btn.configure(state="disabled")
        self.cmd_q.put("reload_golden" if golden_only else "reload")

    def on_exit(self):
        if messagebox.askyesno("Exit", "Close the inspection program?"):
            self.cmd_q.put("quit")
            self.root.after(400, self.root.destroy)

    # ------------------------------------------------------------------ worker thread
    def _worker(self):
        try:
            self.system.start(progress=lambda m: self.ui_q.put(("status", m)))
        except Exception as exc:
            log.exception("start-up failed")
            self.system.problems = [f"start-up error: {exc}"]
            self.system.ready = False
        self.ui_q.put(("ready", None))
        preview = None
        while True:
            try:
                cmd = self.cmd_q.get(timeout=1.0 / max(1, C.PREVIEW_FPS) if preview else None)
            except queue.Empty:
                try:
                    self.ui_q.put(("preview", (preview, self.system.preview(preview))))
                except Exception as exc:
                    self.ui_q.put(("status", f"preview error: {exc}"))
                    preview = None
                continue
            if isinstance(cmd, tuple) and cmd[0] == "preview":
                preview = cmd[1]
                if preview is None and self.system.leds:
                    self.system.leds.all_off()
                continue
            if preview is not None:          # any real command stops the preview
                preview = None
                self.system.leds.all_off()
                self.ui_q.put(("preview_off", None))
            if cmd == "quit":
                self.system.close()
                return
            try:
                if cmd == "inspect":
                    self.ui_q.put(("busy", None))
                    door = self.inputs.door_closed() if self.inputs else True
                    out = self.system.inspect(
                        door_closed=door, progress=lambda m: self.ui_q.put(("status", m)))
                    self.ui_q.put(("result", out))
                elif cmd == "finish_flip":
                    self.ui_q.put(("result", self.system.finish_flip()))
                elif cmd == "reload":
                    self.system.reload(progress=lambda m: self.ui_q.put(("status", m)))
                    self.ui_q.put(("ready", None))
                elif cmd == "reload_golden":
                    probs = self.system.reload_golden()
                    self.ui_q.put(("status", "Golden reference reloaded" if not probs else probs[0]))
                    self.ui_q.put(("ready", None))
            except Exception as exc:
                log.exception("worker command %s crashed", cmd)
                self.ui_q.put(("result", {"state": "ERROR", "message": str(exc)}))

    # ------------------------------------------------------------------ GUI thread
    def _poll(self):
        try:
            while True:
                kind, data = self.ui_q.get_nowait()
                getattr(self, f"_on_{kind}")(data)
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _on_status(self, msg):
        self.status.configure(text=str(msg)[:110])

    def _on_preview(self, data):
        cam, frame = data
        self._show_image("top", frame)
        self.side_info["top"].configure(text=f"LIVE PREVIEW - {cam} camera")

    def _on_preview_off(self, _):
        self.preview_cam = None
        self.preview_btn.configure(text="Preview: off")

    def _on_ready(self, _):
        self.busy = False
        self._update_profile_label()
        if self.system.ready:
            self.start_btn.configure(state="normal")
            self._set_banner("READY", "READY")
            self.status.configure(text="Insert board, close the drawer, press START")
            self._clear_flags()
            if self.inputs:
                self.inputs.set_status_led("ready")
        else:
            self.start_btn.configure(state="disabled")
            self._set_banner("NOT READY - see list / Settings", "WARN")
            self._clear_flags()
            for p in self.system.problems:
                self._add_flag(("SETUP", "", p, "", ""), "REVIEW", p)
            self.details.configure(text=self.system.problems[0] if self.system.problems else "")
            text = "NOT READY - setup still missing:\n\n" + "\n".join(
                f"- {p}" for p in self.system.problems)
            self._show_image("top", message_image(text, color=(120, 200, 255), wrap=95, scale=0.55))
            self.status.configure(text=f"{len(self.system.problems)} setup problem(s)")
        if C.INSPECTION_MODE == "flip" and self.system.flip_pending is None:
            self.finish_btn.configure(state="disabled")

    def _on_busy(self, _):
        self.start_btn.configure(state="disabled")
        self.op_pass.configure(state="disabled")
        self.op_fail.configure(state="disabled")
        self._set_banner("INSPECTING...", "BUSY")
        if self.inputs:
            self.inputs.set_status_led("busy")

    def _on_result(self, out):
        state = out.get("state")
        if state == "RESULT":
            v = out["verdict"]
            self.counts[v] += 1
            self._set_banner(v, v)
            for side in ("top", "bottom"):
                sr = out["side_results"].get(side)
                img = (out.get("overlays") or {}).get(side)
                if img is None:
                    reason = sr.flags[0][4:] if sr is not None and sr.flags else "not inspected"
                    img = message_image(f"{C.SIDE_LABELS[side]}: {sr.verdict if sr else ''}\n{reason}",
                                        wrap=55, scale=0.9)
                self._show_image(side, img)
            self._fill_flags(out)
            self._show_side_info(out)
            t = out.get("timing", {})
            self.footer.configure(text=f"{out.get('board_id', '')} | "
                                       f"{time.strftime('%Y-%m-%d %H:%M:%S')} | total "
                                       f"{t.get('total_s', 0):.2f} s | golden rev "
                                       f"{(self.system.golden or {}).get('revision', '-')}")
            self.status.configure(text=f"Result {v}")
            self.last_folder = out.get("folder")
            if v == "REVIEW":
                self.op_pass.configure(state="normal")
                self.op_fail.configure(state="normal")
            self.finish_btn.configure(state="disabled")
        elif state == "FLIP_PROMPT":
            self._set_banner(PROMPTS[state], "FLIP")
            for side, sr in out["side_results"].items():
                if side in out.get("canvases", {}):
                    from gui.overlay import draw_side
                    self._show_image(side, draw_side(out["canvases"][side], sr,
                                                     self.system.canvas.ppm, self.system.canvas.m))
            self._fill_flags(out, only_inspected=True)
            self._show_side_info(out)
            self.details.configure(text=out.get("message", ""))
            self.status.configure(text=out.get("message", "")[:110])
            self.finish_btn.configure(state="normal")
        else:
            text = PROMPTS.get(state, state or "ERROR")
            self._set_banner(text, "ERROR" if state == "ERROR" else "WARN")
            self._clear_flags()
            msg = out.get("message", "")
            self._add_flag(("", "", msg, "", ""), "REVIEW", msg)
            self.details.configure(text=msg)
            self.status.configure(text="No verdict yet" if self.system.flip_pending else
                                  "No verdict - board not inspected")
        self.finish_btn.configure(state="normal" if self.system.flip_pending else "disabled")
        self.count_lbl.configure(text=self._count_text())
        self.busy = False
        self.start_btn.configure(state="normal" if self.system.ready else "disabled")
        if self.inputs:
            self.inputs.set_status_led("ready")

    def run(self):
        self.root.mainloop()
