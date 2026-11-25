"""
gui/interface.py - Tkinter operator screen (works on 800x480 and 1024x600).

 +--------------------------------------------------------------+
 | PCB X Inspection                         status: Ready        |
 |                  [  PASS / FAIL / REVIEW banner  ]            |
 | +----------------------------+  +---------------------------+ |
 | | TOP (Side A) overlay       |  | Flagged parts list        | |
 | +----------------------------+  |                           | |
 | +----------------------------+  | [      START      ]       | |
 | | BOTTOM (Side B) overlay    |  | [Operator PASS][Op. FAIL] | |
 | +----------------------------+  | PASS 3  FAIL 1  REVIEW 0  | |
 +--------------------------------------------------------------+

Threading rule: Tkinter may only be touched from the main thread. All camera,
YOLO and logging work runs in ONE worker thread; it sends results back
through a queue that the GUI polls every 50 ms.
"""
import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox

import cv2
from PIL import Image, ImageTk

import config as C
from gui.overlay import message_image

log = logging.getLogger(__name__)

COLORS = {"PASS": "#1f9d3a", "FAIL": "#c62828", "REVIEW": "#ef8c00", "READY": "#455a64",
          "BUSY": "#1565c0", "WARN": "#6a1b9a", "ERROR": "#000000"}


class App:
    def __init__(self, system, inputs=None):
        self.system = system
        self.inputs = inputs
        self.cmd_q, self.ui_q = queue.Queue(), queue.Queue()
        self.busy = True
        self.last_folder = None
        self.counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0}

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
        threading.Thread(target=self._worker, daemon=True).start()
        self.root.after(50, self._poll)

    # ------------------------------------------------------------------ layout
    def _build(self):
        r = self.root
        top = tk.Frame(r, bg="#263238")
        top.pack(fill="x")
        tk.Label(top, text=f"{C.BOARD_NAME} Inspection", fg="white", bg="#263238",
                 font=("DejaVu Sans", 14, "bold")).pack(side="left", padx=8, pady=4)
        self.status = tk.Label(top, text="Starting...", fg="#cfd8dc", bg="#263238",
                               font=("DejaVu Sans", 11))
        self.status.pack(side="right", padx=8)

        self.banner = tk.Label(r, text="STARTING", fg="white", bg=COLORS["BUSY"],
                               font=("DejaVu Sans", 30, "bold"), height=1)
        self.banner.pack(fill="x", padx=6, pady=(0, 4))

        body = tk.Frame(r, bg="#263238")
        body.pack(fill="both", expand=True, padx=6, pady=4)
        left = tk.Frame(body, bg="#263238")
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg="#263238", width=300)
        right.pack(side="right", fill="y", padx=(6, 0))
        right.pack_propagate(False)

        self.img_labels = {}
        for side, title in (("top", "TOP - Side A"), ("bottom", "BOTTOM - Side B")):
            tk.Label(left, text=title, fg="#b0bec5", bg="#263238",
                     font=("DejaVu Sans", 10)).pack(anchor="w")
            lab = tk.Label(left, bg="#37474f")
            lab.pack(fill="both", expand=True, pady=(0, 4))
            self.img_labels[side] = lab

        tk.Label(right, text="Flagged parts", fg="#b0bec5", bg="#263238").pack(anchor="w")
        self.flag_list = tk.Listbox(right, font=("DejaVu Sans Mono", 10), height=10,
                                    bg="#eceff1")
        self.flag_list.pack(fill="both", expand=True)
        self.start_btn = tk.Button(right, text="START", font=("DejaVu Sans", 22, "bold"),
                                   bg="#1565c0", fg="white", activebackground="#0d47a1",
                                   command=self.request_start, state="disabled", height=2)
        self.start_btn.pack(fill="x", pady=6)
        op = tk.Frame(right, bg="#263238")
        op.pack(fill="x")
        self.op_pass = tk.Button(op, text="Operator\nPASS", state="disabled",
                                 command=lambda: self.operator("PASS"))
        self.op_fail = tk.Button(op, text="Operator\nFAIL", state="disabled",
                                 command=lambda: self.operator("FAIL"))
        self.op_pass.pack(side="left", expand=True, fill="x")
        self.op_fail.pack(side="left", expand=True, fill="x")
        self.count_lbl = tk.Label(right, text=self._count_text(), fg="white", bg="#263238",
                                  font=("DejaVu Sans", 11))
        self.count_lbl.pack(pady=4)
        tk.Button(right, text="Exit", command=self.on_exit).pack(fill="x")

    def _count_text(self):
        c = self.counts
        return f"PASS {c['PASS']}   FAIL {c['FAIL']}   REVIEW {c['REVIEW']}"

    # ------------------------------------------------------------------ helpers
    def _show_image(self, side, bgr):
        lab = self.img_labels[side]
        w = max(lab.winfo_width(), 200)
        h = max(lab.winfo_height(), 100)
        ih, iw = bgr.shape[:2]
        s = min(w / iw, h / ih)
        rgb = cv2.cvtColor(cv2.resize(bgr, (int(iw * s), int(ih * s)),
                                      interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        lab.configure(image=photo)
        lab.image = photo                   # keep a reference (Tk garbage-collects)

    def _set_banner(self, text, key):
        self.banner.configure(text=text, bg=COLORS[key])

    # ------------------------------------------------------------------ actions
    def request_start(self):
        if not self.busy:
            self.busy = True
            self.cmd_q.put("inspect")

    def operator(self, decision):
        if self.last_folder is not None:
            self.system.result_logger.set_operator_decision(self.last_folder, decision)
            self.status.configure(text=f"Operator decision saved: {decision}")
        self.op_pass.configure(state="disabled")
        self.op_fail.configure(state="disabled")

    def on_exit(self):
        if messagebox.askyesno("Exit", "Close the inspection program?"):
            self.cmd_q.put("quit")
            self.root.after(300, self.root.destroy)

    # ------------------------------------------------------------------ worker thread
    def _worker(self):
        try:
            self.system.start(progress=lambda m: self.ui_q.put(("status", m)))
            self.ui_q.put(("ready", None))
        except Exception as exc:
            log.exception("start-up failed")
            self.ui_q.put(("fatal", str(exc)))
            return
        while True:
            cmd = self.cmd_q.get()
            if cmd == "quit":
                self.system.close()
                return
            if cmd == "inspect":
                self.ui_q.put(("busy", None))
                try:
                    door = self.inputs.door_closed() if self.inputs else True
                    self.ui_q.put(("result", self.system.inspect(door_closed=door)))
                except Exception as exc:
                    log.exception("inspection crashed")
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
        self.status.configure(text=msg)

    def _on_fatal(self, msg):
        self._set_banner("START-UP ERROR", "ERROR")
        self.status.configure(text=msg[:120])
        messagebox.showerror("Start-up error", msg)

    def _on_ready(self, _):
        self.busy = False
        self.start_btn.configure(state="normal")
        self._set_banner("READY", "READY")
        self.status.configure(text="Insert board, close the drawer, press START")
        if self.inputs:
            self.inputs.set_status_led("ready")

    def _on_busy(self, _):
        self.start_btn.configure(state="disabled")
        self.op_pass.configure(state="disabled")
        self.op_fail.configure(state="disabled")
        self._set_banner("INSPECTING...", "BUSY")
        self.flag_list.delete(0, "end")
        if self.inputs:
            self.inputs.set_status_led("busy")

    def _on_result(self, out):
        state = out.get("state")
        self.flag_list.delete(0, "end")
        if state == "RESULT":
            v = out["verdict"]
            self.counts[v] += 1
            self._set_banner(v, v)
            for side in ("top", "bottom"):
                self._show_image(side, out["overlays"][side])
            for line in out["flagged"] or ["All components OK"]:
                self.flag_list.insert("end", line)
            t = out["timing"]
            self.status.configure(text=f"{out['board_id']}  total {t['total_s']:.2f} s")
            self.last_folder = out["folder"]
            if v == "REVIEW":
                self.op_pass.configure(state="normal")
                self.op_fail.configure(state="normal")
        else:
            text = {"WRONG_SIDE": "FLIP THE BOARD", "UNKNOWN_BOARD": "NOT PCB X",
                    "NO_BOARD": "NO BOARD", "DOOR_OPEN": "CLOSE THE DOOR",
                    "ERROR": "ERROR - TRY AGAIN"}.get(state, state)
            self._set_banner(text, "WARN" if state != "ERROR" else "ERROR")
            msg = out.get("message", "")
            self.flag_list.insert("end", *[msg[i:i + 34] for i in range(0, len(msg), 34)])
            for side in ("top", "bottom"):
                self._show_image(side, message_image(text))
            self.status.configure(text="No verdict - board not inspected")
        self.count_lbl.configure(text=self._count_text())
        self.busy = False
        self.start_btn.configure(state="normal")
        if self.inputs:
            self.inputs.set_status_led("ready")

    def run(self):
        self.root.mainloop()
