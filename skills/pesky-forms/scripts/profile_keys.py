"""Print the KEYS of the person's profile, never its values, so Claude can point template
fields at them. Usage: python profile_keys.py [PROFILE.csv]   (default ~/.pesky-forms/profile.csv)
child1.x, child2.x ... are printed once as child.x: the fill script picks the child.
"""
import csv
import re
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".pesky-forms" / "profile.csv"
if not path.exists():
    sys.exit(f"No profile at {path}. Use the keys in profile-template.csv instead.")
with open(path, newline="", encoding="utf-8-sig") as fh:
    keys = {re.sub(r"^child\d+\.", "child.", (r.get("Key") or "").strip()) for r in csv.DictReader(fh)}
for k in sorted(k for k in keys if re.fullmatch(r"[a-z0-9_]+(\.[a-z0-9_]+)+", k)):  # a value typed into Key is never echoed
    print(k)
