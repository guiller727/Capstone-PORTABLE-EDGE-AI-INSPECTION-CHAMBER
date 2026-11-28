"""
storage/report.py - NEW in V2: export one inspection as a self-contained
HTML report (opens in any browser, prints to PDF from the browser).
Images are embedded as base64 so the single file can be e-mailed.
"""
import base64
import html
import json
from pathlib import Path

LABELS = {"top": "FRONT - Side A", "bottom": "BACK - Side B"}
COLORS = {"PASS": "#1f9d3a", "FAIL": "#c62828", "REVIEW": "#ef8c00"}


def _img(path: Path):
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f'<img src="data:image/jpeg;base64,{b64}" style="max-width:100%;border:1px solid #ccc">'


def make_html_report(folder: Path) -> Path:
    folder = Path(folder)
    rec = json.loads((folder / "result.json").read_text())
    e = html.escape
    parts = [f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Inspection {e(rec.get('board_id', ''))}</title>
<style>body{{font-family:Arial,sans-serif;max-width:1100px;margin:20px auto;color:#222}}
table{{border-collapse:collapse;width:100%;margin:8px 0 18px}}td,th{{border:1px solid #ccc;padding:4px 6px;font-size:13px}}
th{{background:#eee}}.v{{color:#fff;padding:6px 14px;border-radius:4px;font-weight:bold}}</style></head><body>
<h1>PCB inspection report</h1>
<p><b>Board ID:</b> {e(rec.get('board_id', ''))} &nbsp; <b>Time:</b> {e(rec.get('timestamp', ''))}
&nbsp; <b>Profile:</b> {e(str(rec.get('profile', '')))} &nbsp; <b>Mode:</b> {e(str(rec.get('mode', '')))}
&nbsp; <b>Golden reference rev.</b> {e(str(rec.get('golden_revision', '')))} ({e(str(rec.get('golden_hash', '')))})</p>
<p><span class="v" style="background:{COLORS.get(rec.get('verdict'), '#555')}">SYSTEM: {e(rec.get('verdict', ''))}</span>
{'&nbsp; <b>Operator decision:</b> ' + e(rec['operator_decision']) if rec.get('operator_decision') else ''}</p>"""]
    if rec.get("notes"):
        parts.append(f"<p><i>{e(rec['notes'])}</i></p>")
    for side, sd in rec.get("sides", {}).items():
        info = (rec.get("side_info") or {}).get(side, {})
        parts.append(f"<h2>{LABELS.get(side, side)} &mdash; "
                     f"<span style='color:{COLORS.get(sd['verdict'], '#555')}'>{e(sd['verdict'])}</span></h2>")
        parts.append(f"<p>Camera: {e(str(info.get('camera', '')))} &nbsp; Identification: "
                     f"{e(str(info.get('identification', '')))} &nbsp; Orientation correction: "
                     f"{e(str(info.get('rotation_deg', '')))}&deg; &nbsp; Alignment: "
                     f"{e(str(info.get('message', '')))}</p>")
        for f in sd.get("flags", []):
            parts.append(f"<p style='color:#ef8c00'><b>{e(f)}</b></p>")
        parts.append(_img(folder / f"overlay_{side}.jpg"))
        rows = sd.get("components", []) + [x for x in sd.get("extras", [])
                                           if x["status"] not in ("DUPLICATE", "NOISE")]
        if rows:
            parts.append("<table><tr><th>ID</th><th>Expected</th><th>Detected</th><th>Conf</th>"
                         "<th>dx mm</th><th>dy mm</th><th>Offset mm</th><th>Tol mm</th>"
                         "<th>Status</th></tr>")
            for c in rows:
                col = "#c62828" if c["status"] in ("MISSING", "WRONG_TYPE", "MISPLACED") else \
                    ("#1f9d3a" if c["status"] == "OK" else "#ef8c00")
                cells = [c.get("id"), c.get("expected_class"), c.get("detected_class"), c.get("conf"),
                         c.get("dx_mm"), c.get("dy_mm"), c.get("offset_mm"), c.get("tol_mm")]
                parts.append("<tr>" + "".join(f"<td>{e('' if x is None else str(x))}</td>" for x in cells)
                             + f"<td style='color:{col}'><b>{e(c['status'])}</b></td></tr>")
            parts.append("</table>")
    t = rec.get("timing", {})
    parts.append(f"<p style='color:#777;font-size:12px'>Timing: {e(json.dumps(t))}</p></body></html>")
    out = folder / "report.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
