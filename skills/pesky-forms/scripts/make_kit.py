"""Turn a checked template into the two files a person uses: an answer sheet and a fill script.

Usage: python make_kit.py TEMPLATE.json FORM.pdf OUT_DIR NAME
Writes OUT_DIR/NAME-answers.csv (opens in Numbers or Excel) and OUT_DIR/fill-NAME.py.
Fields with a "profile" key fill from the person's profile when their sheet row is empty.
The fill script embeds the template and the form's sha256, so it only fills that form.
"""
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent

SCRIPT = '''#!/usr/bin/env python3
"""Fill @@TITLE@@.

1. Open @@NAME@@-answers.csv in Numbers or Excel and type your answers in the "Your answer"
   column. For a checkbox, type yes to tick it or leave it empty. Rows that name a profile key
   in "From your profile" fill from your profile when you leave them empty; type blank to
   keep one of them empty.
2. Save it as CSV again. In Numbers: File > Export To > CSV, and save it over the same file.
   Keep it on this Mac: an online spreadsheet would upload your answers.
3. Run:  python3 fill-@@NAME@@.py          (add --child 2 for your second child, and so on)
   It checks the answers first (dates, digit counts, lengths, one choice per question) and
   writes nothing if something is off. Then it writes @@NAME@@-filled.pdf next to this file
   (@@NAME@@-child2-filled.pdf with --child 2). It will not replace a PDF you edited or signed
   in Preview. Open it in Preview, check every answer, fix anything by typing into it, then sign.

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


def stop(lines, force_hint=True):
    for line in lines:
        print(line)
    sys.exit("Nothing was written." + (" Add --force to fill anyway." if force_hint else ""))


def read_sheet(sheet):
    """{ID: answer}; stops on a sheet that lost its columns or repeats a row."""
    with open(sheet, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = {"ID", "Your answer"} - set(reader.fieldnames or [])
        if missing:
            stop([f"{sheet.name} has no {' or '.join(sorted(missing))} column. Export it again from Numbers or "
                  "Excel without renaming or deleting columns."], force_hint=False)
        rows = [r for r in reader if (r.get("ID") or "").strip()]
    ids = [r["ID"].strip() for r in rows]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        stop([f"{sheet.name} repeats these row IDs: {', '.join(dupes)}. Delete the extra rows."], force_hint=False)
    known = {f["id"] for f in TEMPLATE["fields"]}
    for i in sorted(set(ids) - known):
        print(f"Ignoring row {i}: this form has no such question.")
    return {r["ID"].strip(): (r.get("Your answer") or "").strip() for r in rows}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Fill @@TITLE@@ on this Mac.")
    ap.add_argument("form", nargs="?", default=HERE / @@FORM@@, type=Path)
    ap.add_argument("sheet", nargs="?", default=HERE / "@@NAME@@-answers.csv", type=Path)
    ap.add_argument("--child", type=int, help="which child in your profile (child1, child2, ...); default 1")
    ap.add_argument("--profile", type=Path, default=HOME / "profile.csv")
    ap.add_argument("--out", type=Path, help="output PDF (default @@NAME@@-filled.pdf, or @@NAME@@-child2-filled.pdf)")
    ap.add_argument("--force", action="store_true", help="fill even when the checks below find problems")
    args = ap.parse_args()
    child = args.child or 1
    out = args.out or HERE / ("@@NAME@@-filled.pdf" if args.child is None else f"@@NAME@@-child{child}-filled.pdf")
    stamp = out.with_name(f".{out.name}.sha256")  # what this script last wrote, to spot later edits
    if sha(args.form) != FORM_SHA256:
        sys.exit(f"{args.form} is not the form this script was made for. Make a new kit for it.")
    for ext in (".numbers", ".xlsx"):
        doc = args.sheet.with_suffix(ext)
        if doc.exists() and doc.stat().st_mtime > args.sheet.stat().st_mtime + 1 and not args.force:
            stop([f"{doc.name} was saved after {args.sheet.name}. Export it to CSV again (Numbers: File > "
                  "Export To > CSV) over the same file."])
    if out.exists() and not args.force and (not stamp.exists() or stamp.read_text().strip() != sha(out)):
        stop([f"{out.name} was changed after it was filled (edited or signed in Preview?), or this script did "
              "not make it. Rename it to keep it, or choose another file with --out."])
    answers = read_sheet(args.sheet)
    profile = read_profile(args.profile, child)
    typed_over_profile = []
    from_profile, missing_keys = [], set()
    for f in TEMPLATE["fields"]:
        key, typed = f.get("profile"), answers.get(f["id"], "")
        if typed.lower() == "blank":  # keep it empty even when the profile has a value
            answers[f["id"]] = ""
        elif key and typed:
            typed_over_profile.append(f["question"])
        elif key:
            if profile.get(key):
                answers[f["id"]] = profile[key]
                from_profile.append(f["id"])
            else:
                missing_keys.add(key)
    if args.child and args.child > 1 and typed_over_profile and not args.force:
        stop([f"These rows have typed answers that replace child {child}'s profile. If they belong to another "
              "child, clear them in the sheet (or type blank):"] + [f"  - {q}" for q in typed_over_profile])
    problems = check_answers(TEMPLATE, answers)
    if problems and not args.force:
        source = set(from_profile)
        ids = {f["question"]: f["id"] for f in TEMPLATE["fields"]}
        stop(["Fix these in the sheet (or your profile), export again, and rerun:"] +
             [f"  - {q}: {why}" + (" (from your profile)" if ids.get(q) in source else "") for q, why in problems])
    marks = {}
    for kind in ("signature", "initials"):
        wanted = any(f["kind"] == kind and answers.get(f["id"], "").lower() in TICKED for f in TEMPLATE["fields"])
        found = next((p for d in (HERE, HOME) for p in
                      (d / f"{kind}.{ext}" for ext in ("png", "jpg", "jpeg", "pdf")) if p.exists()), None)
        marks[kind] = found if wanted else None
        if wanted and not found:
            print(f"No {kind}.png, {kind}.jpg or {kind}.pdf found; those lines are left for you to sign by hand.")
        elif wanted:
            print(f"Using {found} for {kind} lines.")
    try:
        filled, empty = fill(str(args.form), TEMPLATE, answers, str(out), marks["signature"], marks["initials"])
    except ValueError as e:  # a signature file this script cannot use
        sys.exit(f"Nothing was written. {e}")
    stamp.write_text(sha(out))
    questions = {f["id"]: f["question"] for f in TEMPLATE["fields"]}
    print(f"Filled {len(filled)} of {len(TEMPLATE['fields'])} blanks into {out.name} "
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
            how = {"checkbox": "type yes to tick, or leave empty" + ("; leave empty to use your profile, "
                                                                    "or type no" if f.get("profile") else ""),
                   "signature": "type yes to add your saved signature (see the fill script), or leave empty to sign by hand",
                   "initials": "type yes to add your saved initials (see the fill script), or leave empty to initial by hand",
                   }.get(f["kind"], f.get("hint", ""))
            if f.get("profile") and f["kind"] == "text":
                how = (how + "; " if how else "") + "leave empty to use your profile, or type blank to keep it empty"
            w.writerow([f["question"], "", how, f.get("profile", ""), f["id"]])
    filler = (HERE / "filler.py").read_text().split('"""', 2)[2].strip()  # drop the module docstring
    text = SCRIPT
    # Form-derived text becomes data, never code: the title is reduced to plain characters, NAME
    # must be a plain file name, and the form's file name goes in as a Python literal.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", name):
        sys.exit("NAME must be letters, digits, dot, dash or underscore, like field-trip-2026")
    title = re.sub(r"[^A-Za-z0-9 .,:;()&'/-]", " ", str(template.get("title", name)))[:120].strip() or name
    for key, value in (("@@TITLE@@", title), ("@@NAME@@", name),
                       ("@@FORM@@", repr(Path(form).name)), ("@@SHA@@", hashlib.sha256(Path(form).read_bytes()).hexdigest()),
                       ("@@TEMPLATE@@", json.dumps(template, indent=1)), ("@@FILLER@@", filler)):
        text = text.replace(key, value)
    (out / f"fill-{name}.py").write_text(text)
    print(f"wrote {out / (name + '-answers.csv')} ({len(template['fields'])} questions) and {out / ('fill-' + name + '.py')}")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
