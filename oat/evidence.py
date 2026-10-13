"""Evidence for the three instructor-only confirmations, a drafted summary for the rubric's last page,
and a prompt file the instructor can upload to Claude to review and finish the PDF.

The confirmations (copyright, learner feedback, accessibility of external tools) are the instructor's own
statements. This module only gathers evidence; it never answers for the instructor."""
import re
from datetime import date

from . import rubric_spec as spec
from .analyze import Ctx, SEARCH, copyright_report

QUESTIONS = [
    ("1.23", "copyright",
     "Do you confirm that all necessary copyright clearance has been obtained for all material used in this course (graphics, videos, etc.)?"),
    ("7.05", "feedback",
     "Do you review learner feedback and adjust course elements in response to learner needs and feedback?"),
    ("8.01", "accessibility",
     "Do you confirm that the external tools and publisher resources used in this course meet accessibility standards?"),
]
PUBLISHERS = r"\b(pearson|cengage|mcgraw|wiley|elsevier|openstax|wolters kluwer|lippincott|f\.? ?a\.? davis|davis's|mosby|saunders|sherpath|hesi|kaplan)\b"


def _domains(d):
    import json
    out = set()
    for n in d.get("announcements") or []:
        out |= set(re.findall(r"https?://(?:www\.)?([^/\s\"'<>)\\]+)", json.dumps(n.get("Body"))))
    for t in d.get("topics") or []:
        u = t.get("url") or ""
        if u.startswith("http") and "/d2l/" not in u:
            m = re.match(r"https?://(?:www\.)?([^/]+)", u)
            out.add(m.group(1)) if m else None
    return sorted(x for x in out if "jalc.edu" not in x)


def collect(d, result):
    c = Ctx(d)
    ev = {}

    # ---- copyright ----
    lines = []
    for f in copyright_report(d)["flags"]:
        lines.append(f)
    for p in d.get("pages") or []:
        t = p.get("text", "")
        title = p.get("title", "")
        if re.match(r"^\s*chapter[ _]*\d+", title, re.I):
            lines.append(f"'{title}' is named like a textbook chapter: confirm it is your own work or licensed instructor material.")
        m = SEARCH(PUBLISHERS, t)
        if m and not SEARCH("copyright notice", title):
            lines.append(f"'{title}' mentions '{m.group(0)}': confirm you may share it with students.")
    unread = [p for p in d.get("pages") or [] if p.get("error")]
    if unread:
        lines.append(f"{len(unread)} uploaded files could not be downloaded or read (too large?), so they were not checked: "
                     + ", ".join(p.get("title", "") for p in unread[:4]) + ("..." if len(unread) > 4 else ""))
    imgs = [t for t in c.topics if (t.get("url") or "").lower().split("?")[0].endswith((".png", ".jpg", ".jpeg", ".gif"))]
    if imgs:
        lines.append(f"{len(imgs)} image files are uploaded ({', '.join(i['title'] for i in imgs[:4])}...): confirm you own them or have a license.")
    if c.videos:
        lines.append(f"{len(c.videos)} uploaded videos (e.g. '{c.videos[0]['title']}'): confirm you recorded them or hold the rights.")
    dom = _domains(d)
    if dom:
        lines.append("Links to outside sites (linking is fine per OAT training): " + ", ".join(dom))
    ev["copyright"] = list(dict.fromkeys(lines)) or ["Nothing in the collected files was flagged."]

    # ---- feedback ----
    fb = []
    titles = [t for t in c.titles if not t.lower().endswith((".mp4", ".mp3"))]
    fb += [f"Item titled '{t}'" for t in dict.fromkeys(titles) if SEARCH(r"survey|feedback|evaluation|check.?in", t)][:6]
    for n in c.news:
        text = (n.get("Title") or "") + " " + str((n.get("Body") or {}).get("Text") if isinstance(n.get("Body"), dict) else "")
        if SEARCH(r"let me know|suggest|how (is|are) (the|you)|your feedback|questions\?", text):
            fb.append(f"Announcement '{n.get('Title')}' invites student input.")
    found = {iid: result["items"].get(iid, {}).get("score") for iid in ("7.01", "7.02", "7.03", "7.04")}
    fb.append("Tool's findings: early check-in=%s, midterm feedback=%s, end-of-course wrap-up=%s, other evaluation=%s (1=found, X=none found)"
              % tuple(found.values()))
    if all(v == "X" for v in found.values()):
        fb.append("No survey, check-in or feedback item was found in D2L. Answer 'yes' only if you gather and act on feedback another way (e.g. in class), and add a note.")
    ev["feedback"] = fb

    # ---- external tools / accessibility ----
    tools = []
    seen = set()
    for l in (d.get("nav") or {}).get("links", []):
        if "type=lti" in (l.get("href") or "") and l["text"] not in seen and not l["text"].startswith("Syllabus"):
            seen.add(l["text"])
            tools.append(f"{l['text']} (external tool linked in the course navbar)")
    if any("Syllabus" in (l.get("text") or "") and "type=lti" in (l.get("href") or "") for l in (d.get("nav") or {}).get("links", [])):
        tools.append("Syllabus (Simple Higher Ed, external tool)")
    for pat, label in ((r"sherpath", "Sherpath (Elsevier) pre-labs and adaptive quizzing"), (r"integrity advocate", "Integrity Advocate (proctoring)"),
                       (r"verity", "Verity proctoring"), (r"panorama", "Panorama (the college's ADA tool)")):
        if SEARCH(pat, c.corpus + " " + " ".join(c.grade_names) + " " + " ".join(l.get("text", "") for l in (d.get("nav") or {}).get("links", []))):
            if not any(label.split(" ")[0].lower() in x.lower() for x in tools):
                tools.append(label)
    dom = _domains(d)
    if dom:
        tools.append("Outside websites linked in announcements/content: " + ", ".join(dom))
    tools.append("Ask each vendor for its accessibility statement (VPAT). The OAT training says the instructor must confirm publisher platforms.")
    ev["accessibility"] = tools
    return ev


def draft_summary(result):
    """Short, honest drafts for the rubric's last page, from the proposed scores. Edit before submitting."""
    items, labels = result["items"], {i: a for i, _, a in spec.ITEMS}
    by_sec = {}
    for iid, v in items.items():
        by_sec.setdefault(int(iid.split(".")[0]), []).append((iid, v.get("score"), v.get("note", "")))

    def label(i):
        return labels.get(i, i).rstrip(":")
    strengths = []
    for sec in (3, 4, 5, 6, 9, 1):
        ones = [label(i) for i, s, _ in by_sec.get(sec, []) if s == "1" and not i.startswith(("1.23",))]
        if len(ones) >= 3:
            strengths.append(f"S{sec} {spec.SECTIONS[sec]}: " + "; ".join(ones[:5]) + ("..." if len(ones) > 5 else ""))
    improve, changes = [], []
    for sec in sorted(by_sec):
        bad = [(i, s, n) for i, s, n in by_sec[sec] if s in ("X", "0") and sec not in (4, 5)]
        if bad:
            improve.append(f"S{sec}: " + "; ".join(f"{label(i)} ({'missing' if s == 'X' else 'partial'})" for i, s, _ in bad[:6]))
        if sec in (1, 2, 3, 9):
            req = [label(i) for i, s, _ in bad if s == "X"]
            if req:
                changes.append(f"S{sec} required: " + "; ".join(req[:6]))
    tag = "(Auto-drafted from proposed scores; please edit.) "
    cut = lambda s: (s[:1100] + "...") if len(s) > 1100 else s
    return {"strengths": cut(tag + " | ".join(strengths)) if strengths else "",
            "improvements": cut(tag + " | ".join(improve)) if improve else "",
            "changes": cut(tag + " | ".join(changes)) if changes else ""}


def build_prompt(d, result, ev, answers):
    c = d.get("course") or {}
    L = ["# OAT rubric: review and finish my self-assessment", "",
         "I ran my OAT assessment tool on my own D2L course. Please review the proposed scores below, tell me which look wrong "
         "(with reasons), and finish the filled rubric PDF.", "",
         "## What to do",
         "1. Review the table of proposed scores and the 'needs my judgment' list. Flag anything that looks wrong, and ask me about any item you can't decide.",
         "2. Use only the answers I gave under 'My confirmations'. **Never mark a verbal-confirmation item as confirmed unless my answer says so.** If it says UNANSWERED, ask me.",
         "3. Update `scores.json` (scores X/0/1/NA and notes) and the 'strengths / improvements / changes' text.",
         "4. Build the PDF with the OAT repo: `python -m oat.pdf_fill scores.json rubric.pdf OAT_Rubric_final.pdf`, then show me the result.",
         "",
         "Scale: **1** = present/accomplished, **0** = not present in all courses / developing, **X** = not present, **NA** = not applicable.",
         "Sections 4 and 5 are scored by variety (base 10: 80%+ Advanced, 40-70% Essential, 10-30% Being Developed). Section 6 (RSI) needs "
         "at least 1 regular and 2 substantive interactions.", "",
         "## Course", f"- Course: {c.get('Name', '')} (D2L id {d.get('orgUnitId')})",
         f"- Dates: {str(c.get('StartDate', ''))[:10]} to {str(c.get('EndDate', ''))[:10]}",
         f"- Prepared: {date.today():%m/%d/%Y}", "",
         "## My confirmations (instructor's own answers)"]
    for iid, key, q in QUESTIONS:
        a = answers.get(key)
        L += [f"### {iid} {key}", f"Question: {q}",
              f"**My answer: {'YES' if a is True else 'NO' if a is False else 'UNANSWERED'}**", "Evidence the tool found:"]
        L += [f"- {x}" for x in ev[key]] + [""]
    L += ["## Proposed scores", "", "| Item | Section | Row | Score | Evidence |", "|---|---|---|---|---|"]
    labels = {i: (a, p) for i, p, a in spec.ITEMS}
    for iid in sorted(result["items"]):
        v = result["items"][iid]
        L.append(f"| {iid} | {spec.SECTIONS[int(iid.split('.')[0])]} | {labels.get(iid, ('', 0))[0]} | {v.get('score')} | {str(v.get('note', '')).replace('|', '/')[:140]} |")
    L += ["", "## Needs my judgment (not scored)"] + [f"- **{r['id']}**: {r['reason']}" for r in result["review"]]
    L += ["", "## Drafted summary text"] + [f"- **{k}**: {result.get(k) or '(none)'}" for k in ("strengths", "improvements", "changes")]
    L += ["", "## Notes", "- No student names or emails are included in this file (the tool never stores them).",
          "- The Syllabus tool (Simple Higher Ed) may not have been readable; if so syllabus rows were scored from other text or left for review."]
    return "\n".join(L) + "\n"


def evidence_markdown(ev):
    out = ["", "## Evidence for the three confirmations", ""]
    for iid, key, q in QUESTIONS:
        out += [f"### {iid} {key}", q] + [f"- {x}" for x in ev[key]] + [""]
    return "\n".join(out)
