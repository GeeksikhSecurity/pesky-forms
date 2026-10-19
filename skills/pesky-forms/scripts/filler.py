"""Fill a PDF form from a template and an answer sheet. Copied unchanged into every
generated fill script, so it must stay self-contained: standard library + pypdf (+ Pillow
only when a signature or initials photo is used).

template: {"fields": [{"id", "page", "kind": "text"|"checkbox"|"signature"|"initials", "question", "box": [x0, top, x1, bottom],
           "font_size", "cells" (optional: N equal printed boxes, one character each),
           "pdf_field" (optional: the form's own field to fill, by full name), "on" (its checkbox state)}]}
           box is in PDF points with the origin at the TOP-left of the page.
answers:  {field id: text}  checkbox, signature and initials answers count as yes for yes/y/x/true/checked/1.
signature, initials: a PNG/JPEG photo of the person's signature or initials, or a PDF signed once in
Preview; placed on "signature" and "initials" fields.
The output is a fillable PDF: every blank is a real form field holding its answer, so a
person can still correct any value in Preview. A placed signature is a stamp they can move or delete.
"""
import datetime
import re
import zlib

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject, FloatObject,
                           NameObject, NumberObject, StreamObject, TextStringObject)

TICKED = {"yes", "y", "x", "true", "checked", "check", "1", "✓", "✔"}
UNTICKED = {"no", "n", "false", "0", "blank"}
MIN_FONT = 6
INK = (26, 35, 64)  # signature color, dark blue-black
MARKS = ("signature", "initials")  # field kinds filled with the person's saved signature or initials


def _font(writer, base):
    return writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject(base),
        **({NameObject("/Encoding"): NameObject("/WinAnsiEncoding")} if base == "/Helvetica" else {})}))


def _stream(writer, w, h, content, resources):
    s = DecodedStreamObject()
    s.set_data(content.encode("latin-1", "replace"))
    s.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
              NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(w), FloatObject(h)]),
              NameObject("/Resources"): resources})
    return writer._add_object(s)


def _fit(text, size, w, h):
    """Largest size <= size that fits the box. ponytail: 0.52 em average Helvetica width;
    use real glyph widths if long text overflows in practice."""
    size = min(size, h * 0.8)
    while size > MIN_FONT and len(text) * 0.52 * size > w - 3:
        size -= 0.5
    return max(size, MIN_FONT)


def _esc(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _up(obj, key):
    """A field attribute, looked up through the /Parent chain as PDF inheritance works."""
    while obj is not None:
        if key in obj:
            return obj[key]
        obj = obj["/Parent"].get_object() if "/Parent" in obj else None
    return None


def full_name(widget):
    parts, obj = [], widget
    while obj is not None:
        if "/T" in obj:
            parts.append(str(obj["/T"]))
        obj = obj["/Parent"].get_object() if "/Parent" in obj else None
    return ".".join(reversed(parts))


def widgets(page):
    annots = page.get("/Annots")
    for ref in annots.get_object() if annots else []:
        a = ref.get_object()
        if a.get("/Subtype") == "/Widget":
            yield a


def on_states(widget):
    """A checkbox or radio widget's ticked state names, such as /Yes or /1."""
    ap = widget["/AP"].get_object() if "/AP" in widget else {}
    n = ap.get("/N")
    n = n.get_object() if n is not None else None
    return [k for k in n if k != "/Off"] if isinstance(n, dict) and not hasattr(n, "get_data") else []


def _rect_top(widget, H):
    x0, y0, x1, y1 = (float(v) for v in widget["/Rect"])
    return [min(x0, x1), H - max(y0, y1), max(x0, x1), H - min(y0, y1)]


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _fill_existing(writer, fields, answers):
    """Fill the form's own fields. Text goes through pypdf; checkboxes and radio options are
    set directly, matched by name, then state, then the widget nearest the template box."""
    filled, empty, text_by_page = [], [], {}
    for f in fields:
        page = writer.pages[f["page"]]
        raw = str(answers.get(f["id"], "") or "").strip()
        if f["kind"] == "checkbox":
            on = raw.lower() in TICKED
            H = float(page.mediabox.height)
            ws = [w for w in widgets(page) if full_name(w) == f["pdf_field"]
                  and (not f.get("on") or f["on"] in on_states(w))]
            if ws:
                w = max(ws, key=lambda w: _overlap(_rect_top(w, H), f["box"]))
                state = NameObject(f.get("on") or (on_states(w) or ["/Yes"])[0])
                holder = w if "/T" in w else w["/Parent"].get_object()
                if on:
                    w[NameObject("/AS")] = state
                    holder[NameObject("/V")] = state
                else:
                    w[NameObject("/AS")] = NameObject("/Off")
                    if holder.get("/V") == state:
                        holder[NameObject("/V")] = NameObject("/Off")
            (filled if on and ws else empty).append(f["id"])
        else:
            text_by_page.setdefault(f["page"], {})[f["pdf_field"]] = raw
            (filled if raw else empty).append(f["id"])
    for p, values in text_by_page.items():
        writer.update_page_form_field_values(writer.pages[p], values, auto_regenerate=False)
    return filled, empty


def _signature_image(writer, path):
    """A photo of a signature on paper: keep the ink, drop the paper, crop to the ink."""
    from PIL import Image, ImageOps  # only needed for signature photos

    g = ImageOps.exif_transpose(Image.open(path)).convert("L")
    g.thumbnail((1600, 1600))
    hist = g.histogram()
    paper = max(range(256), key=lambda v: hist[v] if v > 100 else -1)  # most common light tone
    cut = paper * 0.6
    alpha = g.point(lambda v: 255 if v < cut - 25 else 0 if v > cut + 25 else int((cut + 25 - v) * 255 / 50))
    box = alpha.getbbox()
    if not box:
        raise ValueError("no ink found in the signature photo")
    alpha = alpha.crop(box)
    w, h = alpha.size
    smask = StreamObject()
    smask._data = zlib.compress(alpha.tobytes())
    smask.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                  NameObject("/Width"): NumberObject(w), NameObject("/Height"): NumberObject(h),
                  NameObject("/ColorSpace"): NameObject("/DeviceGray"), NameObject("/BitsPerComponent"): NumberObject(8),
                  NameObject("/Filter"): NameObject("/FlateDecode")})
    img = StreamObject()
    img._data = zlib.compress(bytes(INK) * (w * h))
    img.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(w), NameObject("/Height"): NumberObject(h),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8),
                NameObject("/Filter"): NameObject("/FlateDecode"), NameObject("/SMask"): writer._add_object(smask)})
    return writer._add_object(img), [0.0, 0.0, 1.0, 1.0], w / h  # an image paints the unit square


def _signature_pdf(writer, path):
    """A PDF the person signed once in Preview (Markup > Sign): reuse that signature's drawing.
    It must hold exactly one ink or stamp mark, so a stray note or a text box is never used."""
    marks = []
    for page in PdfReader(path).pages:
        annots = page.get("/Annots")
        for ref in annots.get_object() if annots else []:
            a = ref.get_object()
            n = a["/AP"].get_object().get("/N") if "/AP" in a else None
            if a.get("/Subtype") in ("/Ink", "/Stamp") and n is not None and hasattr(n.get_object(), "get_data"):
                marks.append(n.get_object())
    if len(marks) != 1:
        raise ValueError(f"{path} has {len(marks)} signature-like marks; it needs exactly one. Open a blank "
                         "PDF in Preview, add only your signature with Markup > Sign, and save it under that name.")
    form = marks[0].clone(writer)
    ref = form.indirect_reference or writer._add_object(form)
    bx = [float(v) for v in form["/BBox"]]  # ponytail: ignores /Matrix; add it if a rotated signature lands wrong
    return ref, bx, (bx[2] - bx[0]) / (bx[3] - bx[1])


def load_signature(writer, path):
    return _signature_pdf(writer, path) if str(path).lower().endswith(".pdf") else _signature_image(writer, path)


def _place_signature(writer, page, f, sig):
    """Fit the signature in the box without stretching it, sitting on the box's bottom edge (the
    line): a signature starts at the left, initials are centered in their small box."""
    xobj, bx, aspect = sig
    H = float(page.mediabox.height)
    x0, top, x1, bottom = f["box"]
    bw, bh = x1 - x0, bottom - top
    w = min(bw, bh * aspect)
    h = w / aspect
    dx = (bw - w) / 2 if f["kind"] == "initials" else 0
    sx, sy = w / (bx[2] - bx[0]), h / (bx[3] - bx[1])
    res = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Sig"): xobj})})
    ap = _stream(writer, bw, bh, f"q {sx:.4f} 0 0 {sy:.4f} {dx - bx[0] * sx:.2f} {-bx[1] * sy:.2f} cm /Sig Do Q", res)
    annot = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Stamp"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (x0, H - bottom, x1, H - top)]),
        NameObject("/F"): NumberObject(4), NameObject("/Name"): NameObject("/Signature"),
        NameObject("/Contents"): TextStringObject(f["kind"].capitalize()), NameObject("/P"): page.indirect_reference,
        NameObject("/AP"): DictionaryObject({NameObject("/N"): ap})})
    page.setdefault(NameObject("/Annots"), ArrayObject()).append(writer._add_object(annot))


def _date(raw):
    """MM/DD/YYYY from 1/5/2026, 01/05/26, 2026-01-05 and similar; None when it is not a real date."""
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})", raw)
    y_first = re.fullmatch(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", raw)
    if m:
        mo, d, y = int(m[1]), int(m[2]), int(m[3])
    elif y_first:
        y, mo, d = int(y_first[1]), int(y_first[2]), int(y_first[3])
    else:
        return None
    if y < 100:
        y += 2000 if y < 50 else 1900
    try:
        return datetime.date(y, mo, d).strftime("%m/%d/%Y")
    except ValueError:
        return None


def check_answers(template, answers):
    """Problems with the answers, as (question, problem) pairs that never quote a value.
    Dates whose hint says MM/DD/YYYY are rewritten in that format in place."""
    problems, ticked = [], {}
    for f in template["fields"]:
        raw = str(answers.get(f["id"], "") or "").strip()
        if not raw:
            continue
        q, low = f["question"], raw.lower()
        if f["kind"] in ("checkbox",) + MARKS:
            if low not in TICKED | UNTICKED:
                problems.append((q, "answer yes, no, or leave it empty"))
            elif low in TICKED and f.get("pdf_field") and f.get("on"):
                ticked.setdefault((f["page"], f["pdf_field"]), []).append(q)
            continue
        cells = int(f.get("cells", 0))
        if cells:
            chars = re.sub(r"[\s-]", "", raw)
            if len(chars) != cells:
                short = " (a spreadsheet may have dropped a leading zero)" if len(chars) < cells and chars.isdigit() else ""
                problems.append((q, f"needs {cells} characters but has {len(chars)}{short}"))
            continue
        if "MM/DD/YYYY" in f.get("hint", "").upper():
            date = _date(raw)
            if not date:
                problems.append((q, "is not a date like 12/31/2026"))
                continue
            answers[f["id"]] = raw = date
        x0, top, x1, bottom = f["box"]
        if not f.get("pdf_field") and len(raw) * 0.52 * MIN_FONT > x1 - x0 - 3:
            problems.append((q, "is too long to fit its box even at the smallest size; shorten it"))
    for qs in ticked.values():
        if len(qs) > 1:
            problems.append((qs[0], f"and {len(qs) - 1} other option(s) of the same question are all ticked; pick one"))
    return problems


def fill(form_pdf, template, answers, out_pdf, signature=None, initials=None):
    """Returns (filled ids, empty ids). Never prints or logs a value."""
    writer = PdfWriter(clone_from=PdfReader(form_pdf))
    helv, zadb = _font(writer, "/Helvetica"), _font(writer, "/ZapfDingbats")
    fonts = DictionaryObject({NameObject("/Helv"): helv, NameObject("/ZaDb"): zadb})
    res = DictionaryObject({NameObject("/Font"): fonts})
    own = [f for f in template["fields"] if f.get("pdf_field") and f["kind"] not in MARKS]
    filled, empty = _fill_existing(writer, own, answers) if own else ([], [])
    wanted = {f["kind"] for f in template["fields"]
              if f["kind"] in MARKS and str(answers.get(f["id"], "")).strip().lower() in TICKED}
    marks = {k: load_signature(writer, path) for k, path in zip(MARKS, (signature, initials)) if path and k in wanted}
    fields = ArrayObject()
    for f in template["fields"]:
        if f in own:
            continue
        page = writer.pages[f["page"]]
        H = float(page.mediabox.height)
        x0, top, x1, bottom = f["box"]
        rect = [x0, H - bottom, x1, H - top]
        w, h = x1 - x0, bottom - top
        raw = str(answers.get(f["id"], "") or "").strip()
        if f["kind"] in MARKS:
            if f["kind"] in marks and raw.lower() in TICKED:
                _place_signature(writer, page, f, marks[f["kind"]])
                filled.append(f["id"])
            else:
                empty.append(f["id"])
            continue
        annot = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]), NameObject("/F"): NumberObject(4),
            NameObject("/T"): TextStringObject(f["id"]), NameObject("/TU"): TextStringObject(f.get("question", "")),
            NameObject("/P"): page.indirect_reference})
        if f["kind"] == "checkbox":
            on = raw.lower() in TICKED
            size = max(0.8 * min(w, h), 7)  # a tick smaller than 7 pt is hard to see on paper
            yes = _stream(writer, w, h, f"q BT 0 g /ZaDb {size:.2f} Tf {(w - 0.75 * size) / 2:.2f} "
                                        f"{(h - 0.7 * size) / 2:.2f} Td (4) Tj ET Q", res)
            off = _stream(writer, w, h, "", res)
            state = NameObject("/Yes" if on else "/Off")
            annot.update({NameObject("/FT"): NameObject("/Btn"), NameObject("/V"): state, NameObject("/AS"): state,
                          NameObject("/DA"): TextStringObject("/ZaDb 0 Tf 0 g"),
                          NameObject("/AP"): DictionaryObject({NameObject("/N"): DictionaryObject(
                              {NameObject("/Yes"): yes, NameObject("/Off"): off})})})
            (filled if on else empty).append(f["id"])
        else:
            cells = int(f.get("cells", 0))
            if cells and raw:  # one character per printed box, e.g. a 3-box slice of an SSN
                cw = w / cells
                size = min(float(f.get("font_size", 10)), h * 0.8, cw * 1.3)
                base = (h - size) / 2 + 0.22 * size
                runs = " ".join(f"1 0 0 1 {i * cw + (cw - 0.55 * size) / 2:.2f} {base:.2f} Tm ({_esc(ch)}) Tj"
                                for i, ch in enumerate(re.sub(r"[\s-]", "", raw)[:cells]))
                body = f"/Tx BMC q BT /Helv {size:.2f} Tf 0 g {runs} ET Q EMC"
            elif raw:
                size = _fit(raw, float(f.get("font_size", 10)), w, h)
                base = (h - size) / 2 + 0.22 * size  # vertically centered, baseline above the descenders
                body = f"/Tx BMC q BT /Helv {size:.2f} Tf 0 g 2 {base:.2f} Td ({_esc(raw)}) Tj ET Q EMC"
            else:
                size, body = float(f.get("font_size", 10)), "/Tx BMC EMC"
            annot.update({NameObject("/FT"): NameObject("/Tx"), NameObject("/V"): TextStringObject(raw),
                          NameObject("/DA"): TextStringObject(f"/Helv {size:.2f} Tf 0 g"),
                          NameObject("/AP"): DictionaryObject({NameObject("/N"): _stream(writer, w, h, body, res)})})
            if cells:  # comb field: viewers that redraw from /V (Apple PDFKit, Preview) keep one character per box
                annot.update({NameObject("/Ff"): NumberObject(1 << 24), NameObject("/MaxLen"): NumberObject(cells),
                              NameObject("/V"): TextStringObject(re.sub(r"[\s-]", "", raw)[:cells])})
            (filled if raw else empty).append(f["id"])
        ref = writer._add_object(annot)
        page.setdefault(NameObject("/Annots"), ArrayObject()).append(ref)
        fields.append(ref)
    acro = writer._root_object.get("/AcroForm")
    acro = acro.get_object() if acro is not None else None
    if isinstance(acro, DictionaryObject):  # a fillable form: keep its fields, add ours beside them
        acro.setdefault(NameObject("/Fields"), ArrayObject()).extend(fields)
        dr = acro.setdefault(NameObject("/DR"), DictionaryObject()).get_object()
        dr_fonts = dr.setdefault(NameObject("/Font"), DictionaryObject()).get_object()
        for k, v in fonts.items():
            dr_fonts.setdefault(k, v)
        acro.pop("/XFA", None)  # Acrobat shows XFA data over the fields; without it every viewer shows these values
        acro[NameObject("/NeedAppearances")] = BooleanObject(bool(own))
    else:
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
            NameObject("/Fields"): fields, NameObject("/DR"): res,
            NameObject("/DA"): TextStringObject("/Helv 0 Tf 0 g"), NameObject("/NeedAppearances"): BooleanObject(False)})
    with open(out_pdf, "wb") as fh:
        writer.write(fh)
    return filled, empty
