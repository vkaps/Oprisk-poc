"""
run_all.py - run the whole model on this computer, in order.

    py -u run_all.py --sec-contact "Your Name your@email"

1. extract_sources.py   fines from FCA and ESMA
2. build_universe.py    bank universe (EBA works from a normal connection), FX, matching
3. the workbook          executed on real data -> results/ (incl. model.json for the phone page)

Then push to GitHub so the cloud runs reuse the EBA bank sizes:
    git add -A && git commit -m "Laptop run" && git push
"""
import argparse, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--sec-contact", required=True, help='e.g. "Jane Doe jane@example.com"')
a = ap.parse_args()
py = sys.executable


def step(title, cmd, env=None):
    print(f"\n=== {title} ===", flush=True)
    r = subprocess.run(cmd, cwd=ROOT, env={**os.environ, **(env or {})})
    if r.returncode:
        sys.exit(f"Stopped: '{title}' failed (exit {r.returncode}). Copy the messages above to Claude.")


step("1/3 Extract fines", [py, "-u", "extract_sources.py"])
step("2/3 Build bank universe", [py, "-u", "build_universe.py", "--sec-contact", a.sec_contact])
try:
    import nbconvert, ipykernel  # noqa: F401
except ImportError:
    step("Installing notebook runner", [py, "-m", "pip", "install", "-q", "nbconvert", "ipykernel"])
step("3/3 Run the workbook", [py, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "OpRisk_PoC.ipynb",
                              "--output", "OpRisk_PoC_executed.ipynb", "--ExecutePreprocessor.timeout=1800"],
     env={"OPRISK_DATA_MODE": "REAL"})
print("\nDone. Results are in the results folder; data/universe_report.txt says where every bank size came from.")
