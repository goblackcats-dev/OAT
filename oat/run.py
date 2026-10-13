"""One-click OAT self-assessment: log in, collect the course, score it, fill the rubric PDF.

    python -m oat.run                      # asks for the course URL
    python -m oat.run https://learn.jalc.edu/d2l/home/99316
    python -m oat.run --set-login          # (re)enter and store your D2L login
    python -m oat.run --forget-login
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import analyze, creds, pdf_fill
from .collect import run_collect

DEFAULT_BASE = "https://learn.jalc.edu"
CONFIG = Path.home() / ".oat_config.json"
CONFIRMATIONS = [
    ("1.23", "Do you confirm that all necessary copyright clearance has been obtained for all material in this course?"),
    ("7.05", "Do you review learner feedback and adjust the course in response?"),
    ("8.01", "Do you confirm external tools/publisher materials meet accessibility standards?"),
]


def resource(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / name


def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def ask_yn(q, default=False):
    a = input(f"{q} [{'Y/n' if default else 'y/N'}/skip]: ").strip().lower()
    if a in ("skip", "s"):
        return None
    return default if not a else a.startswith("y")


def open_file(p):
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(p)])
        else:
            subprocess.run(["xdg-open", str(p)])
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("course", nargs="?")
    ap.add_argument("--refill", metavar="COURSE_ID", help="rebuild the PDF from an edited scores.json")
    ap.add_argument("--set-login", action="store_true")
    ap.add_argument("--forget-login", action="store_true")
    ap.add_argument("--out", default="OAT_output")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--browser-path")
    ap.add_argument("--yes-confirm", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()

    if a.refill:
        d = Path(a.out) / a.refill
        pdf = d / f"OAT_Rubric_{a.refill}.pdf"
        pdf_fill.build(json.loads((d / "scores.json").read_text()), str(resource("rubric.pdf")), str(pdf))
        print("Rebuilt", pdf)
        open_file(pdf)
        return

    cfg = load_config()
    course = a.course
    if not course:
        last = cfg.get("last_course", "")
        course = input(f"Course URL [{last}]: ").strip() or last
    m = re.match(r"(https?://[^/]+)/d2l/home/(\d+)", course or "")
    if not m:
        sys.exit("That doesn't look like a D2L course URL, e.g. https://learn.jalc.edu/d2l/home/99316")
    base = m.group(1)
    CONFIG.write_text(json.dumps({**cfg, "last_course": course}))

    if a.forget_login:
        creds.forget(base)
        print("Saved login removed.")
        return
    login = creds.load(base)
    if a.set_login or login is None:
        if a.set_login or ask_yn("Save your D2L login on this computer (OS credential vault) so it signs in automatically?", True):
            login = creds.prompt(base, login)
        if a.set_login:
            return

    channel = None
    path = data = None
    for channel in ([None] if a.browser_path else ["msedge", "chrome", None]):
        try:
            path, data, how = run_collect(course, out=a.out + "/data", profile=str(Path.home() / ".oat_session"),
                                          headless=a.headless, browser_path=a.browser_path, login=login,
                                          channel=channel)
            break
        except Exception as e:
            if "Executable doesn't exist" in str(e) or "not found" in str(e).lower() or "channel" in str(e).lower():
                continue
            raise
    if data is None:
        sys.exit("Could not start a browser. Install Microsoft Edge or Google Chrome, or run: playwright install chromium")

    if how == "manual_after_auto_failed":
        if ask_yn("The saved login didn't work. Update it now?", True):
            login = creds.prompt(base, login)

    result = analyze.analyze(data)
    org = data["orgUnitId"]
    print("\nVerbal confirmations (only you can give these; answer honestly, or 'skip' to leave blank):")
    for iid, q in CONFIRMATIONS:
        ans = True if a.yes_confirm else ask_yn(q)
        if ans is True:
            result["items"][iid] = {"score": "1", "note": "instructor verbally confirmed"}
            result["review"] = [r for r in result["review"] if r["id"] != iid]
        elif ans is False:
            result["items"][iid] = {"score": "X", "note": "instructor did not confirm"}
            result["review"] = [r for r in result["review"] if r["id"] != iid]

    outdir = Path(a.out) / org
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "scores.json").write_text(json.dumps(result, indent=2))
    analyze.write_review(result, analyze.copyright_report(data), outdir / "review.md")
    pdf = outdir / f"OAT_Rubric_{org}.pdf"
    pdf_fill.build(result, str(resource("rubric.pdf")), str(pdf))
    print(f"\nDone.\n  Filled rubric : {pdf}\n  Review report : {outdir / 'review.md'}\n  Scores (editable): {outdir / 'scores.json'}")
    print("To change a score, edit scores.json and run:  OAT.exe --refill", org)
    open_file(pdf)


if __name__ == "__main__":
    main()
