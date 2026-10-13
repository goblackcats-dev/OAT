"""Turn collected course data (course.json) into proposed rubric scores.

Every score is a PROPOSAL from keyword/structure rules. Items that need a person's
judgment (or the instructor's verbal confirmation) are left unscored and listed in the
review file instead of being guessed.
"""
import datetime as dt
import json
import re
import sys
from collections import Counter

from . import rubric_spec as spec

SEARCH = lambda pat, text: re.search(pat, text or "", re.I)


def _t(x):
    return (x or {}).get("Text") if isinstance(x, dict) else (x or "")


class Ctx:
    def __init__(self, d):
        self.d = d
        self.topics = d.get("topics") or []
        self.modules = d.get("modules") or []
        self.pages = [p for p in d.get("pages") or [] if p.get("text")]
        self.news = d.get("announcements") or []
        self.quizzes = d.get("quizzes") or []
        self.dropbox = d.get("dropbox") or []
        self.forums = d.get("forums") or []
        self.forum_topics = [t for f in self.forums for t in (f.get("Topics") or [])]
        self.grades = d.get("grade_items") or []
        self.top_modules = [m for m in self.modules if len(m["path"]) == 1]
        self.syllabus = " ".join(p["text"] for p in self.pages if SEARCH("syllabus", p["title"] + p["url"]))
        mod_text = " ".join((m.get("title") or "") + " " + re.sub("<[^>]+>", " ", m.get("description") or "")
                            for m in self.modules)
        topic_text = " ".join((t.get("title") or "") + " " + re.sub("<[^>]+>", " ", t.get("description") or "")
                              for t in self.topics)
        news_text = " ".join((n.get("Title") or "") + " " + re.sub("<[^>]+>", " ", _t(n.get("Body")) or "")
                             for n in self.news)
        self.page_text = " ".join(p["text"] for p in self.pages)
        self.corpus = " ".join([self.page_text, mod_text, topic_text, news_text])
        self.titles = [x.get("Name") or x.get("Title") or "" for x in
                       (self.quizzes + self.dropbox + self.forums + self.forum_topics)] + \
                      [t.get("title") or "" for t in self.topics] + [m.get("title") or "" for m in self.modules]

    def names_matching(self, pat, pool=None):
        pool = pool if pool is not None else self.titles
        return sorted({n for n in pool if SEARCH(pat, n)})[:5]


def grade_fraction(frac, full=0.9, partial=0.01):
    return "1" if frac >= full else ("0" if frac >= partial else "X")


def analyze(d):
    c = Ctx(d)
    S, REVIEW = {}, []

    def put(iid, score, note=""):
        S[iid] = {"score": score, "note": note}

    def review(iid, why):
        REVIEW.append({"id": iid, "reason": why})

    def kw(iid, pat, text=None, label=None, absent_note="not found in collected course text"):
        text = c.corpus if text is None else text
        m = SEARCH(pat, text)
        if m:
            put(iid, "1", f"auto: found '{m.group(0)[:30]}'" + (f" in {label}" if label else ""))
        else:
            put(iid, "X", f"auto: {absent_note}")

    # ---------- Section 1 ----------
    syl_pages = [p for p in c.pages if SEARCH("syllabus", p["title"] + p["url"])]
    syl_topics = [t for t in c.topics if SEARCH("syllabus", t.get("title") or "")]
    if syl_pages or syl_topics:
        put("1.01", "1", "auto: syllabus found: " + (syl_pages or syl_topics)[0].get("title", ""))
    else:
        put("1.01", "X", "auto: no topic titled syllabus")
    st = c.syllabus or c.corpus
    lbl = "syllabus" if c.syllabus else "course text"
    if not c.syllabus:
        review("1.02-1.05", "Syllabus text could not be read (file type not supported or not found); these were checked against other course text only.")
    kw("1.02", r"(learning )?(objectives?|outcomes?)", st, lbl)
    kw("1.03", r"required (materials|text|resources)|materials|textbook|supplies", st, lbl)
    kw("1.04", r"\bISBN\b|\bedition\b", st, lbl)
    kw("1.05", r"schedule|calendar|week\s*1|weekly", st, lbl)
    kw("1.06", r"start here|getting started|get started|begin here|how to get started")
    if any(SEARCH("welcome", n.get("Title") or "") for n in c.news) or SEARCH("welcome", " ".join(t["title"] or "" for t in c.topics)):
        put("1.07", "1", "auto: welcome announcement/topic found")
    else:
        put("1.07", "X", "auto: no welcome announcement or topic")
    kw("1.08", r"navigat")
    kw("1.09", r"pacing|course (structure|format)|self-paced|weekly module|modules? (open|are released)")
    kw("1.10", r"tutorial|step-by-step|how.to|quick ?guide")
    kw("1.11", r"netiquette")
    kw("1.12", r"late (work|policy|submission)|grading policy|AI (policy|guideline)|due date policy")
    kw("1.13", r"support|help ?desk|tech(nical)? (help|support)")
    kw("1.14", r"accommodation")
    kw("1.15", r"disabilit")
    who = d.get("whoami") or {}
    staff = [u for u in (d.get("classlist_staff") or {}).get("Items", [])] if isinstance(d.get("classlist_staff"), dict) else []
    if SEARCH(r"instructor|professor|dr\.|taught by", st) or staff:
        put("1.16", "1", "auto: instructor name/role text found")
    else:
        put("1.16", "X", "auto: no instructor name found")
    kw("1.17", r"[\w.+-]+@[\w-]+\.[\w.]+|e-?mail")
    kw("1.18", r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}|ext\.? ?\d+")
    kw("1.19", r"respon\w+ (time|within)|within \d+ (hours|business|days)|(24|48|72) hours")
    kw("1.20", r"office (location|:)|\broom\b|\bbuilding\b|\bhall\b")
    kw("1.21", r"office hours")
    kw("1.22", r"\b(Ph\.?D|Ed\.?D|M\.?S\.?N?|M\.?A\.?|M\.?B\.?A|B\.?S\.?N?|D\.?N\.?P|M\.?D)\b|master'?s|bachelor|doctor(ate)?")
    review("1.23", "Verbal confirmation: the instructor must state copyright clearance (see review report).")

    # ---------- Section 2 ----------
    kw("2.01", r"integrity advocate|proctor|respondus|lockdown|technology (requirements|preparedness)|technical requirements")
    kw("2.02", r"orientation")
    kw("2.03", r"technology skills|technical skills|readiness|self-assessment")
    kw("2.04", r"learning styles?")
    kw("2.05", r"access to (a )?(computer|technology|internet)|computer with internet|technical requirements")

    # ---------- Section 3 ----------
    n_mod = len(c.top_modules)
    if n_mod >= 2:
        put("3.01", "1", f"auto: {n_mod} top-level modules, e.g. " + "; ".join((m['title'] or '') for m in c.top_modules[:3]))
    else:
        put("3.01", "X", "auto: fewer than 2 modules found")
    if n_mod:
        def mod_has(m, pat):
            kids = [t for t in c.topics if t["module_path"][:1] == m["path"][:1]]
            return SEARCH(pat, re.sub("<[^>]+>", " ", m.get("description") or "")) or \
                any(SEARCH(pat, t["title"] or "") for t in kids)
        obj = sum(1 for m in c.top_modules if mod_has(m, r"objective|outcome|learning goal"))
        ovw = sum(1 for m in c.top_modules if mod_has(m, r"overview|checklist|summary|introduction|to do|learning goal")
                  or len(re.sub("<[^>]+>", "", m.get("description") or "")) > 40)
        put("3.02", grade_fraction(obj / n_mod), f"auto: objectives found in {obj}/{n_mod} modules")
        put("3.03", grade_fraction(ovw / n_mod), f"auto: overview/checklist in {ovw}/{n_mod} modules")
    linked = Counter()
    for t in c.topics:
        u = (t.get("url") or "").lower()
        for kind in ("quiz", "dropbox", "discuss"):
            if f"type={kind}" in u or f"/{kind}" in u:
                linked[kind] += 1
    present = {"quiz": len(c.quizzes), "dropbox": len(c.dropbox), "discuss": len(c.forum_topics)}
    tot, got = sum(present.values()), sum(min(linked[k], present[k]) for k in present)
    if tot:
        put("3.04", grade_fraction(got / tot, 0.9), f"auto: {got}/{tot} quizzes/dropboxes/discussions linked inside modules (needed for Pulse notifications)")
    review("3.05", "Broken links/spelling/incorrect info need a person (or a link checker).")
    items = [(x.get("Name") or "", _t(x.get("CustomInstructions")) or _t(x.get("Instructions")) or _t(x.get("Description")))
             for x in c.dropbox + c.quizzes] + [(x.get("Name") or "", _t(x.get("Description"))) for x in c.forum_topics]
    if items:
        have = sum(1 for _, ins in items if len(re.sub("<[^>]+>", "", ins or "")) > 25)
        put("3.06", grade_fraction(have / len(items), 0.9), f"auto: instructions present on {have}/{len(items)} assessments")
    due = [x for x in c.dropbox + c.quizzes if x.get("DueDate")]
    if c.dropbox or c.quizzes:
        n = len(c.dropbox) + len(c.quizzes)
        put("3.07", grade_fraction(len(due) / n, 0.9), f"auto: due dates on {len(due)}/{n} dropboxes+quizzes")
    review("3.08", "Navigation being intuitive/consistent is a judgment call (see screenshots).")

    # ---------- Section 4 / 5 (variety) ----------
    work = c.dropbox + c.quizzes + c.forum_topics
    wnames = [(x.get("Name") or "") + " " + re.sub("<[^>]+>", " ", _t(x.get("CustomInstructions")) or _t(x.get("Description")) or "")
              for x in work] + [t["title"] or "" for t in c.topics]

    def variety(iid, pat, pool=None, always=None):
        pool = wnames if pool is None else pool
        hits = sorted({w.strip()[:40] for w in pool if SEARCH(pat, w)})[:3]
        if always or hits:
            put(iid, "1", "auto: " + (always or "e.g. " + "; ".join(hits)))
        else:
            put(iid, "X", "auto: no matching activity found by name")
    variety("4.01", r"$^", always=f"{len(c.forum_topics)} discussion topics" if c.forum_topics else None)
    variety("4.02", r"role.?play|pretend|scenario|simulat")
    variety("4.03", r"problem|solve|calculat|dosage|worksheet")
    variety("4.04", r"essay|paper|reflect|journal|writ")
    variety("4.05", r"group|team|collaborat")
    variety("4.06", r"case stud|case")
    variety("4.07", r"peer|critique")
    variety("4.08", r"virtual|simulation|interactive|game|tour|h5p|lab\b|3d")
    review("4.09", "Open 'other activity' slots are left to the committee.")
    variety("5.01", r"$^", always=f"{len(c.quizzes)} quizzes" if c.quizzes else None)
    variety("5.02", r"$^", always=f"{len(c.forum_topics)} discussion topics" if c.forum_topics else None)
    variety("5.03", r"practice|self.?(check|assess)|study guide|review|ungraded|survey", [(q.get("Name") or "") for q in c.quizzes + c.dropbox])
    variety("5.04", r"reflect|journal|self.?assess")
    variety("5.05", r"peer|review|critique")
    variety("5.06", r"case")
    variety("5.07", r"project")
    variety("5.08", r"paper|essay|research|report")
    variety("5.09", r"video|presentation|powerpoint|slides|podcast|poster")

    # ---------- Section 6 (RSI) ----------
    dates = []
    for n in c.news:
        raw = n.get("StartDate") or n.get("CreatedDate") or ""
        try:
            dates.append(dt.datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except ValueError:
            pass
    if len(dates) >= 2:
        weeks = {x.isocalendar()[:2] for x in dates}
        span = (max(dates) - min(dates)).days // 7 + 1
        frac = len(weeks) / max(1, span)
        put("6.01", grade_fraction(frac, 0.8, 0.3), f"auto: announcements in {len(weeks)} of {span} weeks (cannot judge whether they are substantive)")
        review("6.01", "Check that announcements are content-related, not just logistics/reminders.")
    elif c.news:
        put("6.01", "0", f"auto: only {len(c.news)} announcement(s)")
    else:
        put("6.01", "X", "auto: no announcements")
    review("6.02", "Monitoring student progress / outreach is not visible in D2L data.")
    kw("6.03", r"office hours|ask the instructor|q&a|virtual office|drop.?in")
    kw("6.04", r"zoom|teams|webex|live (session|class)|mini.?lesson|lecture|tutorial|video")
    review("6.04", "Posted lectures alone do NOT count; confirm there is live interaction or a lecture + instructor-led discussion.")
    rubrics = sum(1 for x in c.dropbox if (x.get("Assessment") or {}).get("Rubrics"))
    if c.dropbox:
        put("6.05", "1" if rubrics else "0", f"auto: rubrics on {rubrics}/{len(c.dropbox)} dropboxes; personal feedback not visible")
    review("6.05", "Personal (non-automated) feedback needs a look at graded submissions.")
    kw("6.06", r"question|ask|help|q&a", " ".join(x.get("Name") or "" for x in c.forums + c.forum_topics), "forum names")
    review("6.07", "Instructor replies in discussions need to be checked in the forum.")
    review("6.08", "Other instructional activities are a committee judgment.")
    put("6.09", "1" if c.news else "X", f"auto: {len(c.news)} announcements")
    put("6.10", "1" if c.forums else "X", f"auto: {len(c.forums)} forums")
    put("6.11", "1" if c.forum_topics else "X", f"auto: {len(c.forum_topics)} discussion topics")
    review("6.12", "Feedback method (rubric/comments) needs a look at graded work.")
    kw("6.13", r"video|audio|podcast|record|kaltura|panopto|youtube")
    kw("6.14", r"zoom|teams|webex|live (session|class)|synchronous")
    kw("6.15", r"e-?mail")
    review("6.16", "Other communication is optional.")

    # ---------- Section 7 ----------
    kw("7.01", r"check.?in|introduc|getting to know|icebreaker", " ".join(c.titles))
    kw("7.02", r"mid.?(term|course|semester).*(feedback|survey|evaluation)|(feedback|survey).*mid", " ".join(c.titles) + " " + c.corpus)
    kw("7.03", r"end.of.(course|semester)|wrap.?up|course evaluation|final (feedback|survey)|closing", " ".join(c.titles))
    kw("7.04", r"feedback|survey|evaluation", " ".join(c.titles))
    review("7.05", "Verbal confirmation: instructor reviews learner feedback and adjusts the course.")

    # ---------- Section 8 (accessibility, measurable parts) ----------
    stats = [p["stats"] for p in c.pages if p.get("kind") == "html"]
    imgs = sum(s.get("images", 0) for s in stats)
    noalt = sum(s.get("images_missing_alt", 0) for s in stats)
    gen = sum(s.get("generic_link_text", 0) for s in stats)
    red = sum(s.get("red_text", 0) for s in stats)
    blink = sum(s.get("blink", 0) for s in stats)
    pdfs = [p for p in c.pages if p.get("kind") == "pdf"]
    badpdf = [p for p in pdfs if not p["stats"].get("tagged") or p["stats"].get("looks_scanned")]
    review("8.01", "External tools/publisher accessibility: instructor confirms with the publisher.")
    put("8.02", "1" if not blink else "0", f"auto: {blink} blinking elements, {sum(s.get('headings',0) for s in stats)} headings in {len(stats)} HTML pages (screen-reader navigation needs a manual check)")
    put("8.03", "0" if red else "1", f"auto: {red} red-text uses (color-only cue risk); contrast needs a manual check")
    if imgs:
        put("8.04", "1" if not noalt else "0", f"auto: {noalt} of {imgs} images in pages have no alt attribute; video captions/transcripts need a manual check")
    else:
        review("8.04", "No images found in collected pages; captions/transcripts need a manual check.")
    if pdfs:
        put("8.05", "1" if not badpdf else "0", f"auto: {len(badpdf)} of {len(pdfs)} PDFs untagged or scanned: " + "; ".join(p['title'] for p in badpdf[:3]))
    else:
        review("8.05", "No PDFs found; Word/PowerPoint accessibility needs a manual check.")
    put("8.06", "1" if not gen else "0", f"auto: {gen} 'click here'-style links; keyboard-only use needs a manual check")
    review("8.07", "LMS-built components are accessible by default; confirm.")
    kw("8.08", r"accommodation")
    review("8.09", "Extended time / accessible question types: check quiz settings.")

    # ---------- Section 9 ----------
    q = d.get("qwickly") or {}
    if q.get("found"):
        txt = " ".join(f.get("text", "") for f in q.get("frames", []))
        put("9.01", "1" if SEARCH(r"present|absent|attendance|session", txt) else "0",
            "auto: Qwickly found; see screenshots/qwickly.png (confirm sessions are taken regularly)")
        review("9.01", "Confirm attendance is taken on a regular schedule (Qwickly screenshot attached).")
    else:
        review("9.01", "Qwickly could not be opened automatically; check attendance records by hand.")
    review("9.02", "Participation visible to students: check the student view of Qwickly / gradebook.")
    gi = [g for g in c.grades if isinstance(g, dict)]
    if gi:
        put("9.03", "1", f"auto: {len(gi)} grade items; verify they match the syllabus grading method")
        n_assess = len(c.dropbox) + len(c.quizzes) + len(c.forum_topics)
        put("9.04", grade_fraction(len(gi) / max(1, n_assess), 0.8, 0.2),
            f"auto: {len(gi)} grade items vs {n_assess} assessments")
    else:
        review("9.03", "No grade items could be read (role may not allow it).")
    review("9.05", "Current/accurate grades need a look at the gradebook.")
    review("9.06", "Gradebook item visibility: check Grades > Settings or the student view.")
    review("9.07", "Overall/current grade visibility: check Grades > Settings or the student view.")

    # ---------- header ----------
    course = d.get("course") or {}
    staff_name = f"{who.get('LastName', '')}, {who.get('FirstName', '')}".strip(", ")
    header = {"instructor": staff_name, "date": dt.date.today().strftime("%m/%d/%Y"),
              "course_id": course.get("Code", ""), "course_title": course.get("Name", ""),
              "attendee": "(self-assessment)"}
    return {"header": header, "items": S, "review": REVIEW,
            "section_notes": {}, "strengths": "", "improvements": "", "changes": ""}


def copyright_report(d):
    """Flag material that raises copyright questions. This does not certify clearance."""
    c = Ctx(d)
    flags = []
    for p in c.pages:
        t = p.get("text", "")
        if SEARCH(r"all rights reserved|©|copyright (\d{4}|by)|do not (copy|distribute|reproduce)", t):
            flags.append(f"'{p['title']}' contains a copyright notice: confirm you have permission to post it.")
        if SEARCH(r"pearson|cengage|mcgraw|wiley|elsevier|openstax", t) and p.get("kind") == "pdf":
            flags.append(f"'{p['title']}' is a PDF mentioning a publisher: confirm it is your own or licensed material.")
    for p in c.pages:
        if p.get("kind") == "pdf" and p["stats"].get("pages", 0) > 25:
            flags.append(f"'{p['title']}' is a {p['stats']['pages']}-page PDF: confirm it is not a scanned textbook chapter.")
    ext = [t for t in c.topics if (t.get("url") or "").startswith("http")]
    yt = [t for t in ext if "youtube.com" in t["url"] or "youtu.be" in t["url"]]
    return {"flags": flags, "external_links": len(ext), "youtube_links": len(yt),
            "note": "Linking to public YouTube/web content is fine per OAT training. Uploaded files and images are the risk. Only the instructor can give the verbal copyright confirmation."}


def write_review(result, copy, path):
    lines = ["# OAT self-assessment review", "",
             "Scores marked `auto:` are proposals from rules. Please check them.", "",
             "## Needs your judgment", ""]
    for r in result["review"]:
        lines.append(f"- **{r['id']}**: {r['reason']}")
    lines += ["", "## Copyright (Section 1, verbal confirmation)", "", copy["note"], ""]
    lines += [f"- {f}" for f in copy["flags"]] or ["- Nothing in the collected files was flagged."]
    lines += ["", f"External links: {copy['external_links']} (YouTube: {copy['youtube_links']})"]
    open(path, "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m oat.analyze course.json scores.json")
    data = json.load(open(sys.argv[1]))
    res = analyze(data)
    json.dump(res, open(sys.argv[2], "w"), indent=2)
    write_review(res, copyright_report(data), sys.argv[2].replace(".json", "_review.md"))
    print("scores:", len(res["items"]), "needs review:", len(res["review"]))
