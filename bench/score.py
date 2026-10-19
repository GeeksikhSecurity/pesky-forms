"""Score a filled copy of a flat real form against its answer key (from build.py).

Text field: correct when the text written inside the original field's box (a few points of
slack) equals the expected value, ignoring spaces and case. A field meant to stay blank is
correct when nothing was written there. Checkbox: correct when it is marked exactly when it
should be (new dark pixels in its box versus the flat form). Stray: new text that lands
outside every field box.

Usage: python score.py CACHE_DIR NAME=FORM:FILLED.pdf[:fillable] ...   (needs pymupdf; bench venv)
Add :fillable when FILLED.pdf was made from fillable.pdf: the blank fillable form, with its
fields' own borders baked in, is then the reference instead of flat.pdf.
"""
# ponytail: pymupdf is AGPL; bench-only.
import json
import sys
from pathlib import Path

import pymupdf


def spans(page):
    return [s for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]
            if s["text"].strip()]


def norm(t):
    return "".join(str(t).split()).lower()


def dark(page, r):
    pix = page.get_pixmap(clip=r, dpi=144, colorspace=pymupdf.csGRAY)
    return sum(1 for b in pix.samples if b < 128)


def grade(cache, form, filled, ref_name="flat.pdf"):
    truth = json.loads((cache / form / "truth.json").read_text())
    ref = pymupdf.open(cache / form / ref_name)
    ref.bake()
    doc = pymupdf.open(filled)
    doc.bake()
    rows, stray = [], 0
    for p in range(len(ref)):
        old = {(round(s["bbox"][0]), round(s["bbox"][1]), s["text"]) for s in spans(ref[p])}
        new = [s for s in spans(doc[p]) if (round(s["bbox"][0]), round(s["bbox"][1]), s["text"]) not in old]
        boxes = [t for t in truth if t["page"] == p]
        owner = {}  # each new span belongs to at most one box: the nearest one that holds its center
        for s in new:
            c = pymupdf.Point((s["bbox"][0] + s["bbox"][2]) / 2, (s["bbox"][1] + s["bbox"][3]) / 2)
            near = [t for t in boxes if t["kind"] == "text" and c in pymupdf.Rect(t["rect"]) + (-3, -3, 3, 4)]
            if near:
                rc = lambda t: pymupdf.Rect(t["rect"])
                owner[id(s)] = min(near, key=lambda t: abs(c.y - (rc(t).y0 + rc(t).y1) / 2) * 3
                                   + abs(c.x - (rc(t).x0 + rc(t).x1) / 2) / 10)["id"]
        used = set(owner)
        for t in boxes:
            if t["kind"] == "checkbox":
                tight = pymupdf.Rect(t["rect"]) + (-1, -1, 1, 1)
                marked = dark(doc[p], tight) - dark(ref[p], tight) > 15
                rows.append((t, marked == t["value"], "marked" if marked else "empty"))
                continue
            inside = [s for s in new if owner.get(id(s)) == t["id"]]
            got = " ".join(s["text"].strip() for s in sorted(inside, key=lambda s: (round(s["origin"][1]), s["bbox"][0])))
            rows.append((t, norm(got) == norm(t["value"]), got))
        stray += sum(1 for s in new if id(s) not in used and s["text"].strip() not in ("X", "x", "4", "✓", "✔", "\x14", "3"))
    return rows, stray


def summary(rows, stray):
    def frac(sel):
        sel = list(sel)
        return f"{sum(ok for _, ok, _ in sel)}/{len(sel)}"
    text = [r for r in rows if r[0]["kind"] == "text"]
    return {
        "text filled": frac(r for r in text if r[0]["value"]),
        "text left blank": frac(r for r in text if not r[0]["value"]),
        "checkboxes": frac(r for r in rows if r[0]["kind"] == "checkbox"),
        "all": frac(rows), "stray text": stray,
    }


if __name__ == "__main__":
    cache = Path(sys.argv[1])
    table = {}
    for arg in sys.argv[2:]:
        name, rest = arg.split("=", 1)
        form, filled, *mode = rest.split(":")
        if not Path(filled).exists():
            table.setdefault(name, {})[form] = "NO OUTPUT"
            continue
        rows, stray = grade(cache, form, filled, "fillable.pdf" if mode == ["fillable"] else "flat.pdf")
        table.setdefault(name, {})[form] = summary(rows, stray)
        misses = [(t["id"], t["label"][:60], t["value"], got) for t, ok, got in rows if not ok]
        (Path(filled).parent / f"misses-{name}-{form}.json").write_text(json.dumps(misses, indent=1, ensure_ascii=False))
    print(json.dumps(table, indent=1))
