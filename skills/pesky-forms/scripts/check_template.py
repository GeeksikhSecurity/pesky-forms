"""Check a template against its blank form, then fill it with SAMPLE text so Claude can look.

Usage: python check_template.py TEMPLATE.json FORM.pdf OUT_DIR
Prints problems (overlaps, boxes off the page, boxes too small, duplicate ids, unknown
pdf_field names) and writes OUT_DIR/check-page-N.png: the form filled with placeholder text
and placeholder signature and initials (never real answers), each field outlined and labeled with its
id. Exit code 1 when there are problems.
"""
import json
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent))
from filler import fill, full_name, on_states, widgets  # noqa: E402

LONG_SIDE = 1500


def problems(template, form):
    pages = PdfReader(str(form)).pages
    out, ids = [], set()
    fields = template.get("fields", [])
    own = [{full_name(w): on_states(w) for w in widgets(p)} for p in pages]
    for f in fields:
        missing = {"id", "page", "kind", "question", "box"} - set(f)
        if missing:
            out.append(f"{f.get('id', '?')}: missing {sorted(missing)}")
            continue
        if f["id"] in ids:
            out.append(f"{f['id']}: duplicate id")
        ids.add(f["id"])
        if f["kind"] not in ("text", "checkbox", "signature", "initials"):
            out.append(f"{f['id']}: kind must be text, checkbox, signature or initials")
        if not 0 <= f["page"] < len(pages):
            out.append(f"{f['id']}: page index {f['page']} is not in the form (0 to {len(pages) - 1})")
            continue
        if f.get("pdf_field") and f["kind"] not in ("signature", "initials"):
            states = own[f["page"]].get(f["pdf_field"])
            if states is None:
                out.append(f"{f['id']}: no field named \"{f['pdf_field']}\" on page index {f['page']}")
            elif f["kind"] == "checkbox" and f.get("on") and not any(
                    f["on"] in on_states(w) for w in widgets(pages[f["page"]]) if full_name(w) == f["pdf_field"]):
                out.append(f"{f['id']}: \"{f['pdf_field']}\" has no state {f['on']}")
        W, H = float(pages[f["page"]].mediabox.width), float(pages[f["page"]].mediabox.height)
        x0, top, x1, bottom = f["box"]
        if not (0 <= x0 < x1 <= W and 0 <= top < bottom <= H):
            out.append(f"{f['id']}: box {f['box']} is not inside the {W:.0f} x {H:.0f} page")
        if f["kind"] == "text" and bottom - top < 7:
            out.append(f"{f['id']}: box is {bottom - top:.1f} pt tall; text needs at least 7")
        if f["kind"] == "signature" and bottom - top < 14:
            out.append(f"{f['id']}: signature box is {bottom - top:.1f} pt tall; make it about 28 pt, ending on the line")
        if f["kind"] == "initials" and bottom - top < 8:
            out.append(f"{f['id']}: initials box is {bottom - top:.1f} pt tall; use the whole printed box or about 14 pt above the line")
        if f["kind"] == "checkbox" and min(x1 - x0, bottom - top) < 6:
            out.append(f"{f['id']}: checkbox is {min(x1 - x0, bottom - top):.1f} pt; a tick needs at least 6")
    for i, a in enumerate(fields):
        for b in fields[i + 1:]:
            if a.get("pdf_field") and b.get("pdf_field"):
                continue  # the form's own fields are placed by the form, whatever their boxes
            if a.get("page") == b.get("page") and "box" in a and "box" in b:
                ax0, at, ax1, ab = a["box"]
                bx0, bt, bx1, bb = b["box"]
                if min(ax1, bx1) - max(ax0, bx0) > 1 and min(ab, bb) - max(at, bt) > 1:
                    out.append(f"{a['id']} and {b['id']}: boxes overlap")
    used = {f.get("pdf_field") for f in fields}
    unused = sorted({n for page in own for n in page} - used)
    if unused:
        print(f"NOTE: {len(unused)} of the form's own fields are not in the template (fine for signatures and "
              f"office-use fields; otherwise add them): " + "; ".join(unused[:30]))
    return out


def sample_mark(path, text):
    im = Image.new("L", (40 + 22 * len(text), 90), 255)
    ImageDraw.Draw(im).text((10, 20), text, fill=0, font_size=40)
    im.save(path)
    return path


def main(template_path, form, out):
    out.mkdir(parents=True, exist_ok=True)
    template = json.loads(Path(template_path).read_text())
    found = problems(template, form)
    sample = {f["id"]: ("yes" if f["kind"] in ("checkbox", "signature", "initials") else f.get("sample") or "Sample answer")
              for f in template.get("fields", []) if "id" in f}
    preview = out / "check-filled.pdf"
    fill(str(form), template, sample, str(preview), sample_mark(out / "sample-signature.png", "Signature (sample)"),
         sample_mark(out / "sample-initials.png", "AB"))
    pdf = pdfium.PdfDocument(str(preview))
    pdf.init_forms()
    for i in range(len(pdf)):
        page = pdf[i]
        scale = LONG_SIDE / max(page.get_size())
        im = page.render(scale=scale, may_draw_forms=True).to_pil().convert("RGB")
        draw = ImageDraw.Draw(im)
        for f in template.get("fields", []):
            if f.get("page") == i and "box" in f:
                x0, top, x1, bottom = (v * scale for v in f["box"])
                draw.rectangle([x0, top, x1, bottom], outline=(0, 90, 220), width=1)
                draw.text((x0, top - 11), f["id"], fill=(0, 90, 220))
        im.save(out / f"check-page-{i + 1}.png")
    for p in found:
        print("PROBLEM:", p)
    print(f"{len(template.get('fields', []))} fields, {len(found)} problems; look at {out}/check-page-N.png")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
