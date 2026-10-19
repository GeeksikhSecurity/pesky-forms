"""Turn real fillable PDFs into flat test forms with a known answer key.

For each form in forms.json: download it (sha256-pinned), keep the pages that have fields,
save that as fillable.pdf, record every field's box as the truth, then delete the fields so
flat.pdf has none. A fake
value is made for each field, and answers.json lists them by a human label read from the
text printed next to the box, so a tool has to work out which blank is which.

Usage: python build.py CACHE_DIR    (needs pymupdf; run with the bench venv)
"""
# ponytail: pymupdf is AGPL; this harness is bench-only and never part of the skill.
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

import pymupdf
from pypdf import PdfWriter

HERE = Path(__file__).parent
OVERRIDES = json.loads((HERE / "overrides.json").read_text()) if (HERE / "overrides.json").exists() else {}
NAMES = ["Jordan Testperson", "Riley Sample", "Casey Example", "Morgan Placeholder", "Avery Demo",
         "Quinn Fakename", "Taylor Mockup", "Drew Specimen"]


def fetch(form, cache):
    path = cache / form["name"] / "orig.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        req = urllib.request.Request(form["url"], headers={"User-Agent": "Mozilla/5.0"})
        path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if got != form["sha256"]:
        sys.exit(f"{form['name']}: sha256 {got} does not match the pinned {form['sha256']}")
    return path


def words_text(ws):
    return " ".join(w[4] for w in sorted(ws, key=lambda w: (round(w[1]), w[0]))).strip(" :_")


def label_for(r, kind, words):
    """Printed text a person would read as this blank's label."""
    cy = (r.y0 + r.y1) / 2
    row = [w for w in words if abs((w[1] + w[3]) / 2 - cy) <= max(r.height / 2, 5)]
    if kind == "checkbox":
        right = sorted((w for w in row if w[0] >= r.x1 - 1 and w[0] - r.x1 < 260), key=lambda w: w[0])
        out, last = [], r.x1
        for w in right:  # contiguous words to the right
            if w[0] - last > 14:
                break
            out.append(w)
            last = w[2]
        return words_text(out[:14])
    left = sorted((w for w in row if w[2] <= r.x0 + 2 and r.x0 - w[2] < 220), key=lambda w: -w[2])
    out, edge = [], r.x0
    for w in left:
        if edge - w[2] > 14:
            break
        out.append(w)
        edge = w[0]
    if out:
        return words_text(out[:10])
    inside = [w for w in words if pymupdf.Rect(w[:4]).intersects(r) and w[3] <= r.y0 + r.height * 0.6]
    above = [w for w in words if r.y0 - 14 <= w[3] <= r.y0 + 3 and w[2] > r.x0 and w[0] < r.x1]
    below = [w for w in words if r.y1 - 3 <= w[1] <= r.y1 + 12 and w[2] > r.x0 and w[0] < r.x1]
    for group in (inside, above, below):
        if group:
            return words_text(group[:12])
    return ""


def fake_value(label, i, maxlen):
    low = label.lower()
    if maxlen and maxlen <= 4:
        v = str(1000 + 37 * i)[-maxlen:]
    elif "e-mail" in low or "email" in low:
        v = f"test{i}@example.com"
    elif "birth" in low:
        v = f"0{1 + i % 9}/{10 + i % 18}/19{70 + i % 25}"
    elif "date" in low:
        v = f"0{1 + i % 9}/{10 + i % 18}/2026"
    elif "phone" in low or "fax" in low:
        v = f"555-01{i % 100:02d}"
    elif "zip" in low:
        v = f"9{8000 + i}"[:5]
    elif re.search(r"\bstate\b", low) and "address" not in low:
        v = "WA"
    elif "city" in low:
        v = "Testville"
    elif "address" in low or "street" in low:
        v = f"{100 + i} Example St"
    elif "name" in low:
        v = NAMES[i % len(NAMES)]
    elif "$" in label or "amount" in low or "multiply" in low or "add " in low or "total" in low:
        v = str(100 * (i + 1))
    else:
        v = f"Sample {i}"
    return v[:maxlen] if maxlen else v


def build(form, cache):
    src = pymupdf.open(fetch(form, cache))
    keep = [p.number for p in src if any(w.field_type_string in ("Text", "CheckBox") for w in p.widgets())]
    over = OVERRIDES.get(form["name"], {})
    truth, seen = [], {}
    for new_no, old_no in enumerate(keep):
        page = src[old_no]
        words = page.get_text("words")
        for w in sorted(page.widgets(), key=lambda w: (round(w.rect.y0 / 4), w.rect.x0)):
            if w.field_type_string not in ("Text", "CheckBox"):
                continue
            kind = "checkbox" if w.field_type_string == "CheckBox" else "text"
            o = over.get(w.field_name, {})
            if o.get("skip"):
                continue
            label = o.get("label") or label_for(w.rect, kind, words) or f"unlabeled {kind}"
            i = len(truth)
            if o.get("blank"):
                value = "" if kind == "text" else False
            elif kind == "checkbox":
                value = i % 2 == 0
            else:
                value = o.get("value") or fake_value(label, i, w.text_maxlen)
            base = f"Page {new_no + 1}: {label}"
            seen[base] = seen.get(base, 0) + 1
            truth.append({"id": i, "page": new_no, "kind": kind, "name": w.field_name,
                          "rect": [round(v, 2) for v in w.rect], "label": base, "nth": seen[base],
                          "value": value, "comb": bool(w.field_flags & (1 << 24))})
    for t in truth:  # number repeated labels top to bottom so answers stay unambiguous
        if seen[t["label"]] > 1:
            t["label"] += f" (#{t['nth']} of {seen[t['label']]}, top to bottom)"
    out = pymupdf.open()
    for k in keep:
        out.insert_pdf(src, from_page=k, to_page=k)
    d = cache / form["name"]
    fillable = PdfWriter(clone_from=d / "orig.pdf")  # same pages with the form's own fields, for the fillable test
    for i in reversed(range(len(fillable.pages))):  # pypdf: pymupdf's insert_pdf and select drop the form dictionary
        if i not in keep:
            fillable.remove_page(i)
    fillable.write(d / "fillable.pdf")
    for page in out:
        for w in list(page.widgets()):
            page.delete_widget(w)
    out.xref_set_key(out.pdf_catalog(), "AcroForm", "null")  # no orphan field tree left behind
    out.save(d / "flat.pdf", garbage=3)
    (d / "truth.json").write_text(json.dumps(truth, indent=1))
    answers = {}
    for t in truth:
        if t["kind"] == "checkbox":
            answers[t["label"]] = "checked" if t["value"] else "leave unchecked"
        else:
            answers[t["label"]] = t["value"] or "leave blank"
    (d / "answers.json").write_text(json.dumps(answers, indent=1))
    preview(d, truth)
    print(f"{form['name']}: {len(keep)} page(s), {sum(t['kind'] == 'text' for t in truth)} text, "
          f"{sum(t['kind'] == 'checkbox' for t in truth)} checkboxes")


def preview(d, truth):
    """Answer key drawn on the flat form, for a person checking the labels. Never shown to tools."""
    doc = pymupdf.open(d / "flat.pdf")
    for t in truth:
        p = doc[t["page"]]
        r = pymupdf.Rect(t["rect"])
        p.draw_rect(r, color=(0.85, 0.2, 0), width=0.8)
        p.insert_text((r.x0, r.y0 - 1), str(t["id"]), fontsize=6, color=(0.85, 0.2, 0))
    for p in doc:
        p.get_pixmap(dpi=110).save(d / f"key-p{p.number + 1}.png")


if __name__ == "__main__":
    cache = Path(sys.argv[1])
    for f in json.loads((HERE / "forms.json").read_text()):
        build(f, cache)
