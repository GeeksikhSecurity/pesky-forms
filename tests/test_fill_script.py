"""Offline checks of a generated fill script: profile, children, overwrite guard, sheet checks,
"blank", signatures and form-derived text. No network, no AI.

Usage: python tests/test_fill_script.py     (needs pypdf, pdfplumber, pypdfium2, Pillow)
"""
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, StreamObject

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "pesky-forms" / "scripts"
TEMPLATE = {"title": 'Test form """; import os; os.system("touch PWNED"); """', "fields": [
    {"id": "name", "page": 0, "kind": "text", "question": "Student's name", "box": [72, 100, 300, 116],
     "profile": "child.full_name"},
    {"id": "dob", "page": 0, "kind": "text", "question": "Date of birth", "box": [72, 130, 200, 146],
     "hint": "MM/DD/YYYY", "profile": "child.dob"},
    {"id": "zip", "page": 0, "kind": "text", "question": "ZIP code", "box": [72, 160, 172, 176], "cells": 5},
    {"id": "ok", "page": 0, "kind": "checkbox", "question": "I agree", "box": [72, 190, 82, 200]},
    {"id": "sig", "page": 0, "kind": "signature", "question": "Your signature", "box": [72, 230, 300, 256]},
]}
PROFILE = [("child1.full_name", "Avery Example"), ("child1.dob", "02/03/2015"),
           ("child2.full_name", "Quinn Example"), ("child2.dob", "04/05/2017")]


def sheet(d, **answers):
    with open(d / "t-answers.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Question", "Your answer", "How to answer", "From your profile", "ID"])
        for f in TEMPLATE["fields"]:
            w.writerow([f["question"], answers.get(f["id"], ""), "", f.get("profile", ""), f["id"]])


def run(d, *args):
    r = subprocess.run([sys.executable, str(d / "fill-t.py"), "--profile", str(d / "profile.csv"), *args],
                       capture_output=True, text=True, cwd=d)
    return r.returncode, r.stdout + r.stderr


def values(pdf):
    return {k: str(v.get("/V", "")) for k, v in (PdfReader(pdf).get_fields() or {}).items()}


def sig_pdf(path, marks):
    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    for i in range(marks):
        ap = StreamObject()
        ap._data = b"0 0 m 50 20 l S"
        ap.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                   NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(50), FloatObject(20)])})
        page.setdefault(NameObject("/Annots"), ArrayObject()).append(w._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Ink"),
            NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (100, 100 + 40 * i, 150, 120 + 40 * i)]),
            NameObject("/AP"): DictionaryObject({NameObject("/N"): w._add_object(ap)})})))
    w.write(path)


def main():
    d = Path(tempfile.mkdtemp())
    w = PdfWriter()
    w.add_blank_page(612, 792)
    w.write(d / "t.pdf")
    (d / "work").mkdir()
    (d / "work" / "template.json").write_text(json.dumps(TEMPLATE))
    with open(d / "profile.csv", "w", newline="") as fh:
        csv.writer(fh).writerows([("Key", "Value"), *PROFILE])
    subprocess.run([sys.executable, str(SCRIPTS / "make_kit.py"), str(d / "work/template.json"), str(d / "t.pdf"),
                    str(d), "t"], check=True, capture_output=True)
    assert not (d / "PWNED").exists(), "form title ran as code"

    sheet(d, zip="98101", ok="yes")
    code, out = run(d)
    assert code == 0, out
    v = values(d / "t-filled.pdf")
    assert v["name"] == "Avery Example" and v["dob"] == "02/03/2015" and v["zip"] == "98101", v
    assert "Avery" not in out and "98101" not in out, "an answer was printed"

    code, out = run(d, "--child", "2")
    assert code == 0 and values(d / "t-child2-filled.pdf")["name"] == "Quinn Example", out
    assert values(d / "t-filled.pdf")["name"] == "Avery Example", "child 2 overwrote child 1"

    with open(d / "t-filled.pdf", "ab") as fh:  # as if edited or signed in Preview
        fh.write(b"\n% edited\n")
    code, out = run(d)
    assert code != 0 and "changed after it was filled" in out, out
    (d / "t-filled.pdf").unlink()

    sheet(d, zip="8101")
    code, out = run(d)
    assert code != 0 and "leading zero" in out and not (d / "t-filled.pdf").exists(), out

    sheet(d, zip="98101", dob="1/5/2016", name="blank")
    code, out = run(d)
    v = values(d / "t-filled.pdf")
    assert code == 0 and v["dob"] == "01/05/2016" and v["name"] == "", (out, v)
    (d / "t-filled.pdf").unlink()

    sheet(d, zip="98101", dob="not a date")
    code, out = run(d)
    assert code != 0 and "is not a date" in out, out

    sheet(d, zip="98101", name="Avery Example")
    code, out = run(d, "--child", "2", "--out", str(d / "x.pdf"))
    assert code != 0 and "replace child 2" in out, out

    with open(d / "t-answers.csv", "w", newline="") as fh:
        csv.writer(fh).writerows([("Question", "Answer", "ID"), ("ZIP code", "98101", "zip")])
    code, out = run(d)
    assert code != 0 and "no Your answer column" in out, out

    (d / "signature.png").write_bytes(b"not an image")
    sheet(d, zip="98101")
    code, out = run(d)
    assert code == 0, "an unrequested signature file was loaded: " + out
    (d / "t-filled.pdf").unlink()
    (d / "signature.png").unlink()
    sig_pdf(d / "signature.pdf", 2)
    sheet(d, zip="98101", sig="yes")
    code, out = run(d)
    assert code != 0 and "exactly one" in out, out
    sig_pdf(d / "signature.pdf", 1)
    code, out = run(d)
    assert code == 0 and "Using" in out, out

    shutil.rmtree(d)
    print("all fill-script checks passed")


if __name__ == "__main__":
    main()
