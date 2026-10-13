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

from . import analyze, content, creds, evidence, pdf_fill, schedule
from .collect import run_collect

DEFAULT_BASE = "https://learn.jalc.edu"
CONFIG = Path.home() / ".oat_config.json"


def resource(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / name


def update_config(**kv):
    cfg = load_config()
    cfg.update(kv)
    CONFIG.write_text(json.dumps(cfg))


def make_picker(a, base, primary_org):
    """Choose which of my other courses count toward 'all my online/hybrid/HyFlex courses' (remembered)."""
    from datetime import date, timedelta

    def pick(courses):
        cfg = load_config()
        saved = (cfg.get("courses") or {}).get(base)
        if getattr(a, "courses", None):
            choice = {"include": [x.strip() for x in a.courses.split(",") if x.strip()], "meets": (saved or {}).get("meets", {})}
        elif saved and not getattr(a, "pick_courses", False):
            return saved
        elif not sys.stdin.isatty():
            return saved or {"include": [], "meets": {}}
        else:
            cutoff = (date.today() - timedelta(days=400)).isoformat()
            print("\nCourses where you are an instructor (newest first):")
            sug = []
            for i, cx in enumerate(courses, 1):
                mark = "  <- the course being assessed" if cx["id"] == primary_org else ""
                print(f"  [{i}] {cx['code']:<24} {cx['term']:<12} {cx['mode'] or '?':<7} "
                      f"{'active' if cx['active'] else 'ended ' + cx['end']}{mark}")
                if cx["id"] != primary_org and cx["mode"] and (cx["active"] or cx["end"] >= cutoff):
                    sug.append(i)
            print("The rubric applies to ALL your online, hybrid and HyFlex courses, so pick the others to include.")
            raw = input(f"Numbers to include (e.g. 2,3), Enter = suggested {sug}, 0 = none: ").strip()
            nums = sug if raw == "" else [] if raw == "0" else [int(x) for x in re.findall(r"\d+", raw)]
            include = [courses[n - 1]["id"] for n in nums if 0 < n <= len(courses) and courses[n - 1]["id"] != primary_org]
            meets = dict((saved or {}).get("meets", {}))
            for cid in include + [primary_org]:
                cx = next((c for c in courses if c["id"] == cid), None)
                if cx:
                    v = input(f"In-person meetings for {cx['code']} (Enter to skip): ").strip()
                    if v:
                        meets[cid] = v
            choice = {"include": include, "meets": meets}
        update_config(courses={**(cfg.get("courses") or {}), base: choice})
        return choice
    return pick


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


def attach_syllabus(data, path):
    """Use a syllabus file (PDF/Word/HTML/text) the instructor supplies, e.g. exported from Simple Syllabus."""
    p = Path(path.strip('"'))
    if not p.exists():
        sys.exit(f"Syllabus file not found: {p}")
    kind, text, _ = content.extract(p.name, p.read_bytes())
    if not text.strip():
        sys.exit(f"Could not read any text from {p.name} (supported: .pdf .docx .pptx .html .txt; scanned PDFs need OCR).")
    data["syllabus_tool"] = {"found": True, "source": "file", "file": p.name,
                             "frames": [{"frame": "file:" + p.name, "external": True, "text": text[:60000]}]}
    print(f"Using syllabus file: {p.name} ({len(text):,} characters)")


def finish(a, data, extras=()):
    if getattr(a, "syllabus", None):
        attach_syllabus(data, a.syllabus)
    primary = analyze.analyze(data)
    org = data["orgUnitId"]
    label = lambda d: ((d.get("course") or {}).get("Code") or d.get("orgUnitId"))
    others = [(label(xd), analyze.analyze(xd)) for _, xd in extras]
    if others:
        from . import combine
        result = combine.combine([(label(data), primary)] + others)
        print(f"Combined {1 + len(others)} courses: 1 = in all, 0 = in some, X = in none.")
    else:
        result = primary
    # page-1 table: my other online/hybrid/HyFlex courses
    from datetime import date
    choice = data.get("_course_choice") or {}
    mine = {c["id"]: c for c in data.get("_my_courses") or []}
    rows = []
    for cid in choice.get("include", []):
        cx = mine.get(cid)
        if cx and cid != org:
            rows.append({"id": cx["code"], "title": cx["name"] if cx["name"] != cx["code"] else (cx["term"] + " " + cx["mode"]).strip(),
                         "meets": choice.get("meets", {}).get(cid, ""), "active": bool(cx["active"] and cx["end"] >= date.today().isoformat()),
                         "last_semester": cx["term"], "notes": cx["mode"]})
    if choice.get("meets", {}).get(org):
        result["header"]["in_person_meets"] = choice["meets"][org]
    result["additional_courses"] = rows[:6]
    ev = evidence.collect(data, result, others=[xd for _, xd in extras])

    # --- the three instructor-only confirmations: evidence first, then YOUR answer ---
    answers_in = {}
    if getattr(a, "answers", None):
        answers_in = json.loads(Path(a.answers.strip('"')).read_text())
    answers = {}
    print("\nThree confirmations only you can give. The tool shows evidence, then records YOUR answer.")
    for iid, key, q in evidence.QUESTIONS:
        print(f"\n[{iid}] {q}")
        for line in ev[key]:
            print("   -", line[:230])
        if key in answers_in:
            raw = str(answers_in[key]).strip().lower()
            ans = True if raw in ("yes", "y", "true") else False if raw in ("no", "n", "false") else None
        elif getattr(a, "skip_questions", False):
            ans = None
        elif getattr(a, "yes_confirm", False):   # test only
            ans = True
        else:
            ans = ask_yn("Your answer")
        answers[key] = ans
        if ans is True:
            result["items"][iid] = {"score": "1", "note": "instructor confirmed (own answer; evidence shown)"}
        elif ans is False:
            result["items"][iid] = {"score": "X", "note": "instructor did not confirm"}
        if ans is not None:
            result["review"] = [x for x in result["review"] if x["id"] != iid]
        elif not any(x["id"] == iid for x in result["review"]):
            result["review"].append({"id": iid, "reason": "Unanswered instructor confirmation (see evidence in review.md)."})
    result["verbal_answers"] = answers

    # --- the rubric's fourth statement: the rubric applies to ALL my online/hybrid/HyFlex courses ---
    print("\n[page 1] Instructor acknowledges that the rubric items apply to ALL of your online, hybrid and HyFlex courses.")
    if "acknowledgement" in answers_in:
        ack = str(answers_in["acknowledgement"]).strip().lower() in ("yes", "y", "true")
    elif getattr(a, "skip_questions", False):
        ack = False
    elif getattr(a, "yes_confirm", False):
        ack = True
    else:
        ack = ask_yn("Do you acknowledge this")
    result["header"]["acknowledged"] = bool(ack)
    answers["acknowledgement"] = ack

    # --- page-1 header from the schedule spreadsheet ---
    sched_path = (getattr(a, "schedule", None) or load_config().get("schedule") or "").strip('"')
    if sched_path and Path(sched_path).exists():
        try:
            rows = schedule.load(sched_path)
            who = data.get("whoami") or {}
            me = schedule.find_instructor(rows, who.get("LastName", ""), who.get("FirstName", ""))
            if me:
                result["header"].update(schedule.header_for(me))
                print(f"Schedule: found you ({me['instructor']}); facilitator {me.get('facilitator') or '(none yet)'}; "
                      f"date {me.get('when') or '(not set yet)'}.")
            else:
                print("Schedule: your name was not found in the sign-up sheet.")
            mine = schedule.my_sessions(rows, f"{who.get('FirstName', '')} {who.get('LastName', '')}")
            print("Your committee assignments:" if mine else "You are not listed on any session in the schedule yet.")
            for s in mine:
                print(f"   - {s['instructor']} ({s['discipline']}), {s['role']}, {s['when']}")
        except Exception as e:
            print("Could not read the schedule file:", e)
    elif sched_path:
        print("Schedule file not found:", sched_path)

    # --- drafted text for the rubric's last page (only if empty) ---
    for k, v in evidence.draft_summary(result).items():
        if not result.get(k):
            result[k] = v

    outdir = Path(a.out) / org
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "scores.json").write_text(json.dumps(result, indent=2))
    analyze.write_review(result, analyze.copyright_report(data), outdir / "review.md")
    with open(outdir / "review.md", "a") as f:
        f.write(evidence.evidence_markdown(ev))
    prompt = outdir / "claude_prompt.md"
    prompt.write_text(evidence.build_prompt(data, result, ev, answers))
    pdf = outdir / f"OAT_Rubric_{org}.pdf"
    pdf_fill.build(result, str(resource("rubric.pdf")), str(pdf))
    print(f"\nDone.\n  Filled rubric : {pdf}\n  Review report : {outdir / 'review.md'}\n"
          f"  Prompt for Claude (upload with scores.json): {prompt}\n  Scores (editable): {outdir / 'scores.json'}")
    print("To change a score, edit scores.json and run:  OAT.exe --refill", org)
    open_file(pdf)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("course", nargs="?")
    ap.add_argument("--refill", metavar="COURSE_ID", help="rebuild the PDF from an edited scores.json")
    ap.add_argument("--syllabus", metavar="FILE", help="syllabus file to read (PDF/Word/text) if the Syllabus tool can't be read")
    ap.add_argument("--reanalyze", metavar="COURSE_ID", help="re-score saved data (no login needed)")
    ap.add_argument("--set-login", action="store_true")
    ap.add_argument("--forget-login", action="store_true")
    ap.add_argument("--out", default="OAT_output")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--browser-path")
    ap.add_argument("--courses", metavar="IDS", help="comma-separated D2L ids of your OTHER online/hybrid/HyFlex courses")
    ap.add_argument("--pick-courses", action="store_true", help="choose your other courses again")
    ap.add_argument("--schedule", metavar="XLSX", help="the OAT Assessment Schedule spreadsheet (fills page 1; remembered)")
    ap.add_argument("--answers", metavar="FILE", help='JSON with your own answers, e.g. {"copyright":"yes","feedback":"no","accessibility":"skip"}')
    ap.add_argument("--skip-questions", action="store_true", help="do not ask the three confirmations (they stay unanswered)")
    ap.add_argument("--yes-confirm", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()

    if a.reanalyze and getattr(a, "schedule", None):
        _c = load_config()
        _c["schedule"] = a.schedule.strip('"')
        CONFIG.write_text(json.dumps(_c))
    if a.reanalyze:
        f = Path(a.out) / "data" / a.reanalyze / "course.json"
        if not f.exists():
            sys.exit(f"No saved data at {f}. Run the full collection first.")
        data = json.loads(f.read_text())
        extras = []
        for xo in (data.get("_course_choice") or {}).get("include", []):
            xf = Path(a.out) / "data" / xo / "course.json"
            if xo != a.reanalyze and xf.exists():
                extras.append((xo, json.loads(xf.read_text())))
        finish(a, data, extras)
        return

    if a.refill:
        d = Path(a.out) / a.refill
        pdf = d / f"OAT_Rubric_{a.refill}.pdf"
        pdf_fill.build(json.loads((d / "scores.json").read_text()), str(resource("rubric.pdf")), str(pdf))
        print("Rebuilt", pdf)
        open_file(pdf)
        return

    cfg = load_config()
    if getattr(a, "schedule", None):
        cfg["schedule"] = a.schedule.strip('"')
        CONFIG.write_text(json.dumps(cfg))
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
            path, data, how, extras = run_collect(course, out=a.out + "/data", profile=str(Path.home() / ".oat_session"),
                                                  headless=a.headless, browser_path=a.browser_path, login=login,
                                                  channel=channel, pick=make_picker(a, base, m.group(2)))
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

    finish(a, data, extras)


if __name__ == "__main__":
    main()
