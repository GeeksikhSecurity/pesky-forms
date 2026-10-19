# pesky-forms

Field trips, camp, sports physicals, the W-9 for the new piano teacher. The forms keep coming,
and they all want the same twenty facts about your family.

pesky-forms is a Claude Code skill that fills PDF forms for you. Claude reads the blank form
and works out every blank on it. Your answers come from a profile file on your Mac and are
written into the PDF by a small script that runs on your Mac. Claude never sees them.

## What you get

- **A filled PDF you can still edit.** Every answer is a real form field, so you fix a typo in
  Preview instead of starting over.
- **One profile for every form.** Type your family's details once. Each new form fills from it,
  and the sheet asks only for what is new (the trip date, the permission checkbox).
- **Flat or fillable PDFs.** Printed forms with no fields, fillable PDFs, checkboxes,
  one-digit-per-box number fields, signature lines and "initial here" boxes.
- **Your signature, if you want it.** Snap a photo of your signature on white paper once;
  the script places it on every signature line as a stamp you can move or delete.

## How it works

1. You give Claude the blank form.
2. Claude finds each blank, checks its placement with sample text, and writes two files:
   `NAME-answers.csv`, a list of questions, and `fill-NAME.py`, the script that fills this form.
3. You open the answer sheet in Numbers or Excel. Rows linked to your profile fill themselves;
   you type the rest.
4. You run the script in Terminal. It writes `NAME-filled.pdf`. You check it in Preview and sign.

Next year's copy of the same form reuses the kit. A second child is `--child 2`.

## What Claude sees, and what it never sees

| Claude sees | Claude never sees |
|---|---|
| The blank form | Your answers in the sheet |
| The names of your profile's rows (`child.dob`) | The values in your profile |
| The questions it wrote | The filled PDF |
| | Your signature and initials |

The fill script makes no network connections and prints only which questions were left
empty. The skill tells Claude never to open your profile, your answers or the filled PDF, and
never to run the fill script for you; you run it in your own Terminal app.

One limit, stated plainly: Claude Code can read files on your computer, so these are rules
Claude follows, backed by a design that never needs your values. They are not a lock. If you
want a lock, keep `profile.csv` somewhere Claude Code is not allowed to read.

## Install

In Claude Code:

```
/plugin marketplace add abe238/pesky-forms
/plugin install pesky-forms@pesky-forms
```

Or copy `skills/pesky-forms` into `~/.claude/skills/`.

The first time, the skill sets up a small Python environment in `~/.pesky-forms/venv`
(pypdf, pdfplumber, pypdfium2, Pillow). macOS is the tested platform.

## Your first form

1. In Claude Code: "Help me fill out this form" and give it the PDF.
2. First time only: copy `skills/pesky-forms/profile-template.csv` to
   `~/.pesky-forms/profile.csv`, fill in the Value column in Numbers, and export it as CSV
   over the same file. It covers children, parents, home, emergency contacts, doctor and
   insurance. For more children, copy the `child1` rows as `child2`.
3. Open `NAME-answers.csv`, answer what is new, and export it as CSV over the same file.
4. In Terminal: `~/.pesky-forms/venv/bin/python fill-NAME.py`
5. Open `NAME-filled.pdf` in Preview, check every answer, sign.

## Tested on real forms

Five public forms with their own fields removed: IRS W-9, IRS W-4 (2026), DC Public Schools
field trip permission, Arlington Public Schools field trip permission, and a hospital
records release. 164 blanks in all, scored by where each answer lands on the page.

| Run | Score |
|---|---|
| Fresh Claude Sonnet agent per form, flat versions, answers typed in the sheet | 164/164 |
| Same kits, profile-linked rows filled from a test profile instead | 164/164 |
| Fresh agent per form, original fillable versions (earlier version of the skill) | 164/164 |
| Script only, answers straight from the key | 164/164 |

Each agent ran once per form. The agents linked 2 to 7 rows per form to profile keys; the
rest were one-off questions such as trip dates and checkboxes.

The harness is in `bench/`: it downloads the forms (pinned by hash), builds the test
versions, plays a perfect parent and scores the result. It needs PyMuPDF, which only the
bench uses.

## Limits

- Tested on macOS with Claude Code. Other platforms may work; they are untested.
- One run per form in the tests above. Results can vary between runs, so check every
  filled PDF before you sign.
- Forms built with XFA only (some government forms) are not supported. Scanned forms are untested.
- A signature photo works best in dark pen on plain white paper.
- Right-to-left and CJK text are untested.

## Related projects

The idea of letting the AI see field names while code fills in the values is an established
pattern; see Simon Willison's "Dual LLM" post (2023) and DeepMind's CaMeL (2025). Projects
in the same space: [pdf-autofillr](https://github.com/Engineersmind/pdf-autofillr),
[pdf-fill-studio](https://github.com/KevinDoremy/pdf-fill-studio),
[ericmjl's pdf-form-filler](https://github.com/ericmjl/skills/tree/main/skills/pdf-form-filler).

## License

MIT
