---
name: pesky-forms
description: Fill PDF forms (school permission slips, field trips, camp, sports and medical forms, tax forms like the W-9), flat or fillable, without sending the answers to Claude. Claude reads only the blank form and writes an answer sheet plus a fill script; answers come from the person's sheet and their local family profile, and their saved signature and initials can be added, all on their Mac. Use when someone wants to fill out a PDF form and keep their family's details off AI services.
---

# pesky-forms

You read the blank form and write a kit: an answer sheet and a fill script. Answers come from
the person's family profile (`~/.pesky-forms/profile.csv`, which you know only by its keys) and
from what they type into the sheet. They run the script themselves. Their answers never pass
through you.

## Privacy rules (never break these)

1. Never ask for answers in chat. If the person pastes personal details, tell them they do not
   need to, and do not repeat the details back.
2. Never open, read, list the contents of, or summarize `*-answers.csv` after you write it,
   `*-filled.pdf`, `profile.csv`, or any `signature.*` or `initials.*` file (in the form's folder
   or `~/.pesky-forms/`). Learn the profile only through `profile_keys.py`, which prints keys,
   never values. Never run the fill script: the person runs it in their own Terminal app.
   (Running it with `!` in Claude Code would put its output in this conversation.)
3. Work only from a blank form. If the page images show typed or handwritten answers
   (names, dates, signatures, ticked boxes), stop and ask for a blank copy.

## Setup (once per Mac)

```bash
python3 -m venv ~/.pesky-forms/venv && ~/.pesky-forms/venv/bin/pip install -q pypdf pdfplumber pypdfium2 pillow
```

`S` below is this skill's `scripts/` folder; `PY=~/.pesky-forms/venv/bin/python`.

## Steps

1. **Pick a folder and a short name.** Default `~/Documents/Forms/NAME/` with NAME like
   `field-trip-2026`. Copy the blank form into it as `NAME.pdf`.
2. **Inspect:** `$PY $S/inspect_form.py NAME.pdf work/`. Read `work/candidates.txt` and look at
   every `work/page-N-candidates.png`. Candidates are lines, boxes, underscore runs and
   checkboxes with exact coordinates and the text printed next to them. Do the privacy rule 3
   check on these images now. If `candidates.txt` starts with "This form has N fillable fields",
   the form has its own fields (blue boxes, ids like `p1f0`): see "Fillable forms" below.
   Then run `$PY $S/profile_keys.py` for the profile's keys. If there is no profile yet, use the
   keys in this skill's `profile-template.csv` (they are what the person will fill in).
3. **Write `work/template.json`:**
   ```json
   {"title": "DC Public Schools field trip permission",
    "fields": [
     {"id": "student_name", "page": 0, "kind": "text", "question": "Page 1: Student's name",
      "box": [149.0, 174.3, 308.0, 187.3], "font_size": 10, "hint": "as the school has it",
      "profile": "child.full_name"},
     {"id": "child_insured", "page": 1, "kind": "checkbox",
      "question": "Page 2: My child is covered by accident/medical insurance", "box": [130.1, 676.0, 140.9, 686.8]}]}
   ```
   - One field per blank a parent or signer could fill in, on every page: include worksheets
     and optional sections too. People can leave a row empty; they cannot add a blank you left
     out. Skip only sections marked for office, school or employer use, and anything already printed.
   - Each line the person signs is a `"kind": "signature"` field, question like
     "Page 3: Your signature (parent or guardian)". Its box spans the signature line, up to 28 pt
     tall (at least 10), with its bottom on the line: `[x0, line_y - 28, x1, line_y]`, and must
     not cover printed words: on a tight form, lower its top until check_template stops flagging it. A form's own signature
     field (`signature` in the listing) uses that field's box, without `pdf_field`. Skip lines
     someone else signs (a school official, an employer). The date next to it is a text field.
   - Each small box or short line where the person writes their initials ("Initial here",
     "____ Initials") is a `"kind": "initials"` field, question like "Page 2: Your initials
     next to item 4". Its box is the printed box, or about 14 pt tall above a short line.
   - `page` is the 0-based page index. `box` is `[x0, top, x1, bottom]` in PDF points with the
     origin at the top-left, exactly as in `candidates.txt`.
   - Take coordinates from a matching candidate whenever one exists. For a writing line
     (`line` or `underscores`), the candidate box already sits on top of the line; keep it.
     For a drawn text box, shrink it by 1.5 pt on each side. For a checkbox, use its box as is. Estimate from the page image only when
     no candidate fits: points = pixels / (px per pt shown in `candidates.txt`).
   - `question` is what a person reads in the sheet: start with the page, then the form's own
     label in plain words. When labels repeat (two "Phone" lines), say whose it is
     ("Page 1: Emergency contact's phone").
   - `hint` gives the format when it matters: `MM/DD/YYYY`, `9 digits`, `as on your driver's license`.
   - A number printed one box per digit is one field per group the form prints, with
     `"cells": N` (the number of digit boxes in that group) and a box spanning the whole group:
     an SSN printed as 3, 2 and 4 boxes is three fields, "Social security number, first 3
     digits" with `"cells": 3`, and so on.
   - `font_size` 10; use 8 for tight boxes.
   - `"cover": true` when the blank already holds printed placeholder text, such as a draft
     with "[Enter]" or "Name: [add surname]": the box spans the placeholder and the answer is
     written on white over it. Leave printed text that is already a final answer alone.
   - `profile`: the profile key whose value answers this blank exactly, if one does
     ("Student's date of birth" is `child.dob`; "Parent/guardian cell" is `parent1.cell_phone`).
     Use `child.` keys, not `child1.`: the person picks the child when they run the script.
     Leave `profile` out when no key fits exactly, when the blank needs a different format
     than the key's note says, or for one-off answers (trip date, a yes/no about this trip).
     A checkbox can use a yes/empty key such as `child.has_medical_insurance`.

   **Fillable forms** (the listing shows the form's own fields): one template field per listed
   field, except office-use ones, with `"pdf_field"` set to the name in quotes and `box` copied
   from the listing. The filler then fills the form's own fields, so placement is exact.
   - `text`: `"kind": "text"`. With `maxlen` or `comb`, say the length in `hint` ("9 digits").
   - `checkbox`: `"kind": "checkbox"` plus the listed `"on"` value.
   - `radio`: one `"kind": "checkbox"` field per listed option, each with the same `pdf_field`,
     its own `on` and box, and a question naming the option ("Page 1: Filing status: Single").
   - `choice`: `"kind": "text"`, with the listed options in `hint` ("one of: Yes, No").
   - `signature`: a `"kind": "signature"` field on its box, without `pdf_field`. A text field
     the form labels as initials becomes a `"kind": "initials"` field on its box, without `pdf_field`.
   - Add printed blanks from the candidate list only where no field of the form's own covers
     a blank the person fills in.
4. **Check:** `$PY $S/check_template.py work/template.json NAME.pdf work/check/`. Fix every
   PROBLEM it prints, and read its NOTE about unused fields: add any the person fills in. Then
   look at every `work/check/check-page-N.png`: the form is filled with the words "Sample answer"
   and "Signature (sample)" / "AB" for initials (placeholders only). Each sample must sit on its own blank, not on a
   label, not crossing a line, not spilling out of its box. Every blank a parent fills must have
   a sample. Fix the template and re-run until both are true.
5. **Make the kit:** `$PY $S/make_kit.py work/template.json NAME.pdf . NAME`. It writes
   `NAME-answers.csv` and `fill-NAME.py`.
6. **Tell the person, as numbered steps:**
   1. Open `NAME-answers.csv` in Numbers or Excel and type each answer in "Your answer". For a
      checkbox, type yes or leave it empty. Use an app on this Mac, not an online spreadsheet.
      Rows with a key in "From your profile" fill from your profile when left empty; type
      blank to keep one empty.
   2. Save as CSV: in Numbers, File > Export To > CSV, saved over the same file.
   3. First time only: copy this skill's `profile-template.csv` to `~/.pesky-forms/profile.csv`,
      fill in the Value column in Numbers, and export it as CSV over the same file. Every
      later form reuses it.
   4. Optional, to have your signature and initials added: answer yes on those rows and put
      `signature.png` and `initials.png` (or `.jpg`: photos in dark pen on white paper, cropped
      or not) in the form's folder, or in `~/.pesky-forms/` to use them for every form. A blank
      PDF signed once in Preview (Markup > Sign), saved as `signature.pdf`, works too.
   5. In the Terminal app: `~/.pesky-forms/venv/bin/python ~/Documents/Forms/NAME/fill-NAME.py`
      (add `--child 2` for a second child; that writes `NAME-child2-filled.pdf`). It checks the
      answers first and writes nothing if a date, digit count, length or choice is off, telling
      you which question to fix. It will not replace a filled PDF you edited or signed in Preview.
      It lists any blanks left empty and any profile keys to add.
   6. Open `NAME-filled.pdf` in Preview, read every answer, fix any by typing into the field.
      Sign any signature line still empty (Preview: Markup > Sign, pick your saved signature,
      drag it onto the line). An added signature or initials can be moved, resized or deleted.

   Keep the folder: next year's copy of the same form can reuse the sheet.
