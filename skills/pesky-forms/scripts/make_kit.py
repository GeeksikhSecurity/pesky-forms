"""Turn a checked template into the two files a person uses: an answer sheet and a fill script.

Usage: python make_kit.py TEMPLATE.json FORM.pdf OUT_DIR NAME
Writes OUT_DIR/NAME-answers.csv (opens in Numbers or Excel) and OUT_DIR/fill-NAME.py.
Fields with a "profile" key fill from the person's profile when their sheet row is empty.
The fill script embeds the template and the form's sha256, so it only fills that form.
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent

SCRIPT = '''#!/usr/bin/env python3
"""Fill @@TITLE@@.

1. Open @@NAME@@-answers.csv in Numbers or Excel and type your answers in the "Your answer"
   column. For a checkbox, type yes to tick it or leave it empty. Rows that name a profile key
   in "From your profile" fill themselves from your profile when you leave them empty.
2. Save it as CSV again. In Numbers: File > Export To > CSV, and save it over the same file.
   Keep it on this Mac: an online spreadsheet would upload your answers.
3. Run:  python3 fill-@@NAME@@.py          (add --child 2 for your second child, and so on)
   It writes @@NAME@@-filled.pdf next to this file. Open it in Preview, check every answer,
   fix anything by typing into the field, then sign.

Profile (optional): ~/.pesky-forms/profile.csv, one row per fact (Key, Value). Keys like
child1.first_name are for your first child; this script reads child.first_name from the
child you pick with --child. An answer typed in the sheet always wins over the profile.

Signature and initials (optional): a signature or initials row answered yes gets your saved
signature or initials. Put them next to this file, or in ~/.pesky-forms/ to use them for every form:
  signature.png  or signature.jpg: a photo of your signature in dark pen on plain white paper
  initials.png   or initials.jpg: the same for your initials
  (or signature.pdf / initials.pdf: a blank PDF you signed once in Preview with Markup > Sign)
Each is placed as a stamp: in Preview you can move, resize or delete it. You can also skip all
this and sign in Preview: Markup > Sign, pick your saved signature, drag it onto the line.

This script runs on your Mac and makes no network connections. It prints which questions
were left empty, never your answers. Needs: pypdf (and Pillow for a signature or initials photo).
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

TEMPLATE = json.loads(r"""@@TEMPLATE@@""")
FORM_SHA256 = "@@SHA@@"
HERE = Path(__file__).resolve().parent
HOME = Path.home() / ".pesky-forms"

@@FILLER@@


def read_profile(path, child):
    """{key: value} from a Key,Value CSV; childN.x is also available as child.x for the chosen child."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = {(r.get("Key") or "").strip(): (r.get("Value") or "").strip() for r in csv.DictReader(fh)}
    prefix = f"child{child}."
    rows.update({"child." + k[len(prefix):]: v for k, v in list(rows.items()) if k.startswith(prefix)})
    return rows


def main():
    ap = argparse.ArgumentParser(description="Fill @@TITLE@@ on this Mac.")
    ap.add_argument("form", nargs="?", default=HERE / "@@FORM@@", type=Path)
    ap.add_argument("sheet", nargs="?", default=HERE / "@@NAME@@-answers.csv", type=Path)
    ap.add_argument("--child", type=int, default=1, help="which child in your profile (child1, child2, ...)")
    ap.add_argument("--profile", type=Path, default=HOME / "profile.csv")
    ap.add_argument("--out", type=Path, default=HERE / "@@NAME@@-filled.pdf")
    args = ap.parse_args()
    if hashlib.sha256(args.form.read_bytes()).hexdigest() != FORM_SHA256:
        sys.exit(f"{args.form} is not the form this script was made for.")
    with open(args.sheet, newline="", encoding="utf-8-sig") as fh:
        answers = {row["ID"]: (row.get("Your answer") or "").strip() for row in csv.DictReader(fh) if row.get("ID")}
    profile = read_profile(args.profile, args.child)
    from_profile, missing_keys = [], set()
    for f in TEMPLATE["fields"]:
        key = f.get("profile")
        if key and not answers.get(f["id"]):
            if profile.get(key):
                answers[f["id"]] = profile[key]
                from_profile.append(f["id"])
            else:
                missing_keys.add(key)
    marks = {}
    for kind in ("signature", "initials"):
        marks[kind] = next((p for d in (HERE, HOME) for p in
                            (d / f"{kind}.{ext}" for ext in ("png", "jpg", "jpeg", "pdf")) if p.exists()), None)
        wanted = any(f["kind"] == kind and answers.get(f["id"]) for f in TEMPLATE["fields"])
        if wanted and not marks[kind]:
            print(f"No {kind}.png, {kind}.jpg or {kind}.pdf found; those lines are left for you to sign by hand.")
        elif wanted:
            print(f"Using {marks[kind]} for {kind} lines.")
    filled, empty = fill(str(args.form), TEMPLATE, answers, str(args.out), marks["signature"], marks["initials"])
    questions = {f["id"]: f["question"] for f in TEMPLATE["fields"]}
    print(f"Filled {len(filled)} of {len(TEMPLATE['fields'])} blanks into {args.out.name} "
          f"({len(from_profile)} from your profile).")
    for fid in empty:
        print("  left empty:", questions[fid])
    if missing_keys:
        print(f"Add these to {args.profile} to fill them next time: " + ", ".join(sorted(missing_keys)))


if __name__ == "__main__":
    main()
'''


def main(template_path, form, out, name):
    out.mkdir(parents=True, exist_ok=True)
    template = json.loads(Path(template_path).read_text())
    with open(out / f"{name}-answers.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Question", "Your answer", "How to answer", "From your profile", "ID"])
        for f in template["fields"]:
            how = {"checkbox": "type yes to tick, or leave empty",
                   "signature": "type yes to add your saved signature (see the fill script), or leave empty to sign by hand",
                   "initials": "type yes to add your saved initials (see the fill script), or leave empty to initial by hand",
                   }.get(f["kind"], f.get("hint", ""))
            w.writerow([f["question"], "", how, f.get("profile", ""), f["id"]])
    filler = (HERE / "filler.py").read_text().split('"""', 2)[2].strip()  # drop the module docstring
    text = SCRIPT
    for key, value in (("@@TITLE@@", template.get("title", name)), ("@@NAME@@", name),
                       ("@@FORM@@", Path(form).name), ("@@SHA@@", hashlib.sha256(Path(form).read_bytes()).hexdigest()),
                       ("@@TEMPLATE@@", json.dumps(template, indent=1)), ("@@FILLER@@", filler)):
        text = text.replace(key, value)
    (out / f"fill-{name}.py").write_text(text)
    print(f"wrote {out / (name + '-answers.csv')} ({len(template['fields'])} questions) and {out / ('fill-' + name + '.py')}")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
