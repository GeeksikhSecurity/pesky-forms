"""Show Claude a blank form: page images plus every candidate blank with exact coordinates.

Usage: python inspect_form.py FORM.pdf OUT_DIR
Writes OUT_DIR/page-N.png and OUT_DIR/candidates.txt. All coordinates are PDF points,
origin at the top-left of the page: [x0, top, x1, bottom]. Candidates are drawn and
numbered on page-N-candidates.png so they can be matched to what the page shows. When the
form has its own fillable fields they are listed first (blue, ids pNfK) with their names.
"""
import sys
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import ImageDraw
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent))
from filler import _rect_top, _up, full_name, on_states, widgets  # noqa: E402

RADIO, PUSH, COMB = 1 << 15, 1 << 16, 1 << 24


def own_fields(page, H):
    """The form's own fields on this page: (kind, name, box, extra)."""
    out = []
    for w in widgets(page):
        ft, flags = _up(w, "/FT"), int(_up(w, "/Ff") or 0)
        extra = ""
        if ft == "/Tx":
            kind = "text"
            if _up(w, "/MaxLen"):
                extra = f" maxlen={_up(w, '/MaxLen')}" + (" comb (one character per box)" if flags & COMB else "")
        elif ft == "/Btn" and not flags & PUSH:
            kind = "radio" if flags & RADIO else "checkbox"
            extra = f' on="{(on_states(w) or ["/Yes"])[0]}"'
        elif ft == "/Ch":
            kind = "choice"
            opts = [o[-1] if isinstance(o, list) else o for o in _up(w, "/Opt") or []]
            extra = f" options={[str(o) for o in opts][:20]}"
        elif ft == "/Sig":
            kind = "signature"
        else:
            continue
        out.append((kind, full_name(w), [round(v, 1) for v in _rect_top(w, H)], extra))
    return sorted(out, key=lambda f: (round(f[2][1] / 6), f[2][0]))

LONG_SIDE = 1500  # px; Claude reads images up to 1568 px on the long side


def near_text(words, x0, top, x1, bottom):
    """Printed text to the left on the same row, else just above, else just below."""
    words = [w for w in words if "___" not in w["text"]]  # blanks are not labels, and their font boxes can be off
    cy = (top + bottom) / 2
    left = [w for w in words if abs((w["top"] + w["bottom"]) / 2 - cy) < max(6, (bottom - top) / 2)
            and w["x1"] <= x0 + 2 and x0 - w["x1"] < 160]
    above = [w for w in words if top - 16 <= w["bottom"] <= top + 2 and w["x1"] > x0 and w["x0"] < x1]
    below = [w for w in words if bottom - 2 <= w["top"] <= bottom + 14 and w["x1"] > x0 and w["x0"] < x1]
    right = [w for w in words if abs((w["top"] + w["bottom"]) / 2 - cy) < 6 and w["x0"] >= x1 - 1 and w["x0"] - x1 < 40]
    out = []
    for name, ws in (("left", left[-6:]), ("above", above[:8]), ("below", below[:8]), ("right", right[:6])):
        if ws:
            out.append(f'{name}: "{" ".join(w["text"] for w in sorted(ws, key=lambda w: (round(w["top"]), w["x0"])))}"')
    return "; ".join(out)


def underscore_runs(ppage, H):
    """Runs of 4+ "_" as writing lines, placed where pdfium draws the glyphs. pdfplumber's box
    for "_" comes from font metrics, which some fonts get 15-30 pt wrong (EPA lead-paint form)."""
    tp, runs, run = ppage.get_textpage(), [], []
    for i in range(tp.count_chars() + 1):
        box = tp.get_charbox(i) if i < tp.count_chars() and tp.get_text_range(i, 1) == "_" else None
        if box and (not run or abs(box[0] - run[-1][2]) < 1.5):
            run.append(box)
            continue
        if len(run) >= 4:
            y = H - min(b[1] for b in run)  # glyph bottom, top-left origin: the drawn line
            runs.append(("underscores", run[0][0], y - 14, run[-1][2], y))
        run = [box] if box else []
    return runs


def candidates(page, ppage):
    words = page.extract_words(keep_blank_chars=False, use_text_flow=True)
    found = []
    for e in page.edges:  # long horizontal rules: writing lines
        if e["orientation"] == "h" and e["x1"] - e["x0"] >= 30:
            found.append(("line", e["x0"], e["top"] - 14, e["x1"], e["top"]))
    for r in page.rects:
        w, h = r["x1"] - r["x0"], r["bottom"] - r["top"]
        if 5 <= w <= 16 and 5 <= h <= 16 and abs(w - h) < 3:
            found.append(("checkbox", r["x0"], r["top"], r["x1"], r["bottom"]))
        elif w >= 30 and 10 <= h <= 120:
            found.append(("box", r["x0"], r["top"], r["x1"], r["bottom"]))
    found += underscore_runs(ppage, float(page.height))  # "_____" runs are writing lines too
    for c in page.chars:  # checkbox glyphs such as ☐ in a symbol font
        if c["text"] in "☐□❑❒■◻" or "Wingdings" in c.get("fontname", "") or "ZapfDingbats" in c.get("fontname", ""):
            found.append(("checkbox-glyph", c["x0"], c["top"], c["x1"], c["bottom"]))
    found = sorted({(k, round(a, 1), round(b, 1), round(c, 1), round(d, 1)) for k, a, b, c, d in found},
                   key=lambda f: (round(f[2] / 6), f[1]))
    return [(k, [a, b, c, d], near_text(words, a, b, c, d)) for k, a, b, c, d in found]


def main(form, out):
    out.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(form))
    lines = []
    reader = PdfReader(str(form))
    total = 0
    with pdfplumber.open(str(form)) as doc:
        for i, page in enumerate(doc.pages):
            W, H = float(page.width), float(page.height)
            scale = LONG_SIDE / max(W, H)
            im = pdf[i].render(scale=scale).to_pil().convert("RGB")
            im.save(out / f"page-{i + 1}.png")
            cands = candidates(page, pdf[i])
            marked = im.copy()
            draw = ImageDraw.Draw(marked)
            lines.append(f"## Page {i + 1} (index {i}): {W:.0f} x {H:.0f} pt, image {im.width} x {im.height} px, "
                         f"{scale:.4f} px per pt")
            own = own_fields(reader.pages[i], float(reader.pages[i].mediabox.height))
            total += len(own)
            if own:
                words = page.extract_words(use_text_flow=True)
                lines.append("### The form's own fields (use these; pdf_field is the name in quotes)")
                for k, (kind, name, (a, b, c, d), extra) in enumerate(own):
                    fid = f"p{i + 1}f{k}"
                    draw.rectangle([a * scale, b * scale, c * scale, d * scale], outline=(0, 90, 220), width=2)
                    draw.text((a * scale, b * scale - 11), fid, fill=(0, 90, 220))
                    lines.append(f'{fid} {kind} pdf_field="{name}" box=[{a}, {b}, {c}, {d}]{extra} '
                                 f'{near_text(words, a, b, c, d)}')
                lines.append("### Printed blanks (only for blanks the form's own fields do not cover)")
            for n, (kind, (a, b, c, d), text) in enumerate(cands):
                cid = f"p{i + 1}c{n}"
                draw.rectangle([a * scale, b * scale, c * scale, d * scale], outline=(220, 0, 0), width=2)
                draw.text((a * scale, b * scale - 11), cid, fill=(220, 0, 0))
                lines.append(f"{cid} {kind} box=[{a}, {b}, {c}, {d}] {text}")
            marked.save(out / f"page-{i + 1}-candidates.png")
            if not cands:
                lines.append("(no drawn lines or boxes found: likely a scan; estimate blanks from page image)")
    if total:
        lines.insert(0, f"This form has {total} fillable fields of its own. Fill them through pdf_field; "
                        "add printed blanks only where no field covers a blank.\n")
    (out / "candidates.txt").write_text("\n".join(lines) + "\n")
    print(f"{len(pdf)} page(s), {total} fillable fields; candidates in {out / 'candidates.txt'}; images in {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
