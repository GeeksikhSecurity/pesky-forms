"""Play a perfect person for a pesky-forms kit: answer each sheet row from the answer key, then
run the kit's own fill script. Claude never sees these answers; this runs after it is done.

Each template field is paired one-to-one with the answer-key field it overlaps most, so a
row gets the value that belongs at that spot on the page. A template field that names one of
the form's own fields (pdf_field) pairs only with that field. Rows with no partner stay empty.
Signature and initials rows are answered yes and fake photos are put in the kit folder, so the
script's signature and initials steps run too.

With "profile" as a 5th argument, rows that name a profile key are left empty in the sheet
and their values go into KIT_DIR/test-profile.csv instead (as child1.* for child.* keys), so
the fill script's profile path is what fills them. A key that two rows would need with
different values keeps the first in the profile and puts the other in the sheet.

Usage: python kit_fill.py CACHE_DIR FORM KIT_DIR NAME [profile]
"""
import csv
import json
import subprocess
import sys
from pathlib import Path


def overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def fake_mark(path, strokes=150):
    """A phone-photo-like fake: shaded off-white paper with a blue pen scribble (short for initials)."""
    import math
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.linear_gradient("L").rotate(90).resize((1600, 900)).point(lambda v: 230 - v // 8).convert("RGB")
    pts = [(200 + i * 8, 450 + 90 * math.sin(i / 8) + 30 * math.sin(i / 3)) for i in range(strokes)]
    ImageDraw.Draw(im).line(pts, fill=(30, 40, 110), width=12, joint="curve")
    im.filter(ImageFilter.GaussianBlur(2)).save(path, quality=85)


def main(cache, form, kit, name, via_profile=False):
    truth = json.loads((cache / form / "truth.json").read_text())
    tpl = json.loads((kit / "work" / "template.json").read_text())
    def score(f, t):  # a thin band on a big box's writing line still counts as that box
        if f.get("pdf_field") and f["pdf_field"] != t["name"]:
            return 0.0
        box, rect = f["box"], t["rect"]
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        inside = rect[0] - 3 <= cx <= rect[2] + 3 and rect[1] - 3 <= cy <= rect[3] + 3
        return max(overlap(box, rect), 0.15 if inside else 0.0)
    pairs = sorted(((score(f, t), f["id"], t["id"]) for f in tpl["fields"] for t in truth
                    if f["page"] == t["page"]), reverse=True)
    by_field, used = {}, set()
    for score, fid, tid in pairs:
        if score < 0.1 or fid in by_field or tid in used:
            continue
        by_field[fid] = tid
        used.add(tid)
    values = {t["id"]: t["value"] for t in truth}
    sheet = kit / f"{name}-answers.csv"
    rows = list(csv.DictReader(open(sheet, encoding="utf-8-sig")))
    kinds = {f["id"]: f["kind"] for f in tpl["fields"]}
    keys = {f["id"]: f.get("profile") for f in tpl["fields"]}
    profile = {}
    for r in rows:
        v = values.get(by_field.get(r["ID"]), "")
        r["Your answer"] = "yes" if v is True or kinds[r["ID"]] in ("signature", "initials") else "" if v is False else v
        key = keys[r["ID"]]
        if via_profile and key and r["Your answer"] and profile.get(key, r["Your answer"]) == r["Your answer"]:
            profile[key] = r["Your answer"]
            r["Your answer"] = ""
    if "signature" in kinds.values():
        fake_mark(kit / "signature.jpg")
    if "initials" in kinds.values():
        fake_mark(kit / "initials.jpg", 40)
    with open(sheet, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{form}: {len(tpl['fields'])} template fields, {len(by_field)} paired with the "
          f"{len(truth)} answer-key fields, {len(profile)} profile keys used")
    cmd = [sys.executable, str(kit / f"fill-{name}.py")]
    if via_profile:
        with open(kit / "test-profile.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Key", "Value"])
            w.writerows([("child1." + k[6:] if k.startswith("child.") else k), v] for k, v in profile.items())
        cmd += ["--profile", str(kit / "test-profile.csv")]
    else:
        cmd += ["--profile", str(kit / "no-profile.csv")]  # never the real ~/.pesky-forms profile
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4], sys.argv[5:] == ["profile"])
