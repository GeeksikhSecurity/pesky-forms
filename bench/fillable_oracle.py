"""Fill each form's own fields (fillable.pdf from build.py) straight from the answer key
with the skill's filler, no agent involved. Checks the fillable-form path of filler.py:
score the outputs with score.py NAME=FORM:OUT_DIR/FORM.pdf:fillable (expect 164/164).

Usage: python fillable_oracle.py CACHE_DIR OUT_DIR
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/pesky-forms/scripts"))
from filler import fill
cache, out = Path(sys.argv[1]), Path(sys.argv[2])
for n in "w9 w4 dcps valley arlington".split():
    truth = json.loads((cache/n/"truth.json").read_text())
    tpl, ans = [], {}
    for t in truth:
        tpl.append({"id": f"f{t['id']}", "page": t["page"], "kind": t["kind"], "question": t["label"],
                    "box": t["rect"], "pdf_field": t["name"]})
        ans[f"f{t['id']}"] = ("yes" if t["value"] else "") if t["kind"] == "checkbox" else t["value"]
    fill(str(cache/n/"fillable.pdf"), {"fields": tpl}, ans, str(out/f"{n}.pdf"))
