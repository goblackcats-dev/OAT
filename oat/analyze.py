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
    """D2L 'rich text' can be a string, {'Text','Html'}, or nested {'Text': {'Text','Html'}}. Always return str."""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return _t(x.get("Text") or x.get("Html") or "")
    return ""


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
        # Only text from the tool's own frame counts. D2L's own page chrome (menus) is not syllabus text.
        ERR = r"error has occurred|could not locate a matching account|unable to locate account"
        syl_frames = [f for f in (d.get("syllabus_tool") or {}).get("frames", [])
                      if f.get("external") or (f.get("frame") and "/d2l/" not in f["frame"])]
        self.syl_file = (d.get("syllabus_tool") or {}).get("source") == "file"
        self.syl_error = (not self.syl_file) and any(SEARCH(ERR, f.get("text", "")) for f in syl_frames)
        def _syllabus_like(t):
            hits = sum(bool(SEARCH(p, t)) for p in (r"objectives?|outcomes", r"office hours", r"required (text|materials)|textbook",
                                                      r"grading|grade scale", r"schedule|calendar", r"policy|policies"))
            return len(t) > 1500 and hits >= 3
        direct = [f for f in (d.get("syllabus_direct") or {}).get("frames", [])
                  if _syllabus_like(f.get("text", "")) and not SEARCH(ERR, f.get("text", ""))]
        self.syl_direct = bool(direct)
        self.syl_tool = " ".join(f.get("text", "") for f in syl_frames + direct if not SEARCH(ERR, f.get("text", "")))
        self.syllabus = (" ".join(p["text"] for p in self.pages if SEARCH("syllabus", p["title"] + p["url"]))
                         + " " + self.syl_tool).strip()
        self.grade_names = [g.get("Name") or "" for g in self.grades if isinstance(g, dict)]
        self.videos = [t for t in self.topics if ":video:" in (t.get("url") or "")
                       or (t.get("title") or "").lower().endswith((".mp4", ".mov", ".mp3"))]
        mod_text = " ".join((m.get("title") or "") + " " + re.sub("<[^>]+>", " ", m.get("description") or "")
                            for m in self.modules)
        topic_text = " ".join((t.get("title") or "") + " " + re.sub("<[^>]+>", " ", t.get("description") or "")
                              for t in self.topics)
        news_text = " ".join((n.get("Title") or "") + " " + re.sub("<[^>]+>", " ", _t(n.get("Body")) or "")
                             for n in self.news)
        self.page_text = " ".join(p["text"] for p in self.pages) + " " + self.syl_tool
        self.corpus = " ".join([self.page_text, mod_text, topic_text, news_text])
        self.titles = [x.get("Name") or x.get("Title") or "" for x in
                       (self.quizzes + self.dropbox + self.forums + self.forum_topics)] + \
                      [t.get("title") or "" for t in self.topics] + [m.get("title") or "" for m in self.modules] \
            + self.grade_names

    def names_matching(self, pat, pool=None):
        pool = pool if pool is not None else self.titles
        return sorted({n for n in pool if SEARCH(pat, n)})[:5]


_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def attendance_dates(text):
    """Pull calendar dates (e.g. 'Sep 16, 2025', '9/16/2025', '2025-09-16') out of page text."""
    out = set()
    for m in re.finditer(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2})(?:,? (\d{4}))?", text or ""):
        try:
            out.add(dt.date(int(m.group(3) or dt.date.today().year), _MONTHS[m.group(1).lower()], int(m.group(2))))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text or ""):
        y = int(m.group(3)); y += 2000 if y < 100 else 0
        try:
            out.add(dt.date(y, int(m.group(1)), int(m.group(2))))
        except ValueError:
            pass
    for m in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text or ""):
        try:
            out.add(dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    return sorted(out)


def spelling_suspects(c, limit=25):
    """Words that are not in a standard dictionary (typos OR technical terms): evidence only, never scored."""
    try:
        from spellchecker import SpellChecker
    except Exception:
        return []
    texts = [m.get("title") or "" for m in c.modules] + [re.sub(r"\.(mp4|mp3|docx|pptx|pdf)$", "", t.get("title") or "", flags=re.I) for t in c.topics]
    texts += c.grade_names + [(n.get("Title") or "") + " " + re.sub("<[^>]+>", " ", _t(n.get("Body"))) for n in c.news]
    texts += [(x.get("Name") or "") + " " + re.sub("<[^>]+>", " ", _t(x.get("CustomInstructions")) or _t(x.get("Description")) or "")
              for x in c.dropbox + c.quizzes + c.forum_topics]
    words = {}
    for t in texts:
        for w in re.findall(r"[A-Za-z][A-Za-z']{4,}", t):
            if "'" in w or re.search(r"[a-z][A-Z]", w):   # possessives and CamelCase names (ChatGPT) are not typos
                continue
            words.setdefault(w.lower(), w)
    sp = SpellChecker()
    bad = sorted(sp.unknown(list(words)))
    return [words[w] for w in bad][:limit]


def week_consistency(c):
    """Do the weekly/unit modules share the same layout (discussion, quiz, files, video, overview)? Returns (fraction, detail)."""
    from collections import Counter
    weeks = [m for m in c.top_modules if re.match(r"\s*(week|unit|chapter|module|lesson)\b", m.get("title") or "", re.I)]
    sigs = {}
    for m in weeks:
        kids = [t for t in c.topics if t["module_path"][:1] == m["path"][:1]]
        urls = " ".join((t.get("url") or "").lower() for t in kids)
        f = set()
        if "type=discuss" in urls:
            f.add("discussion")
        if "type=quiz" in urls:
            f.add("quiz")
        if "type=dropbox" in urls:
            f.add("dropbox")
        if any(t.get("type") == "File" for t in kids):
            f.add("files")
        if any(":video:" in (t.get("url") or "") for t in kids):
            f.add("video")
        if len(re.sub("<[^>]+>", "", m.get("description") or "")) > 40:
            f.add("overview")
        sigs[(m.get("title") or "")[:18]] = frozenset(f)
    if len(sigs) < 3:
        return None, ""
    modal, n = Counter(sigs.values()).most_common(1)[0]
    odd = [k for k, v in sigs.items() if v != modal]
    return n / len(sigs), f"{n} of {len(sigs)} weekly modules share the layout [{', '.join(sorted(modal)) or 'empty'}]" + \
        (f"; different: {', '.join(odd[:4])}" if odd else "")


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
    nav_syl = any(re.fullmatch(r"syllabus", (l.get("text") or "").strip(), re.I)
                  for l in (d.get("nav") or {}).get("links", [])) \
        or "Syllabus" in (d.get("qwickly") or {}).get("nav_links", []) \
        or (d.get("syllabus_tool") or {}).get("found")
    if c.syl_error:
        review("1.01", "The Syllabus tab opens Simple Higher Ed, which showed the error 'could not locate a matching account' for your login" +
               (" (the direct-login worked, but it opened the Simple Syllabus dashboard, not your course's syllabus: open ADN 207 there, choose View or Print, save it as a PDF, and rerun with --syllabus)" if (d.get("syllabus_direct") or {}).get("found") and not c.syl_direct else "") +
               ". Check with the Teaching and Learning Center, and confirm that students can open the syllabus. Not scored automatically.")
    elif syl_pages or syl_topics or nav_syl:
        put("1.01", "1", "auto: syllabus found" + (" (Syllabus tool in the course navbar)" if nav_syl else ": " + (syl_pages or syl_topics)[0].get("title", "")))
    else:
        put("1.01", "X", "auto: no syllabus topic or Syllabus tool found")
    if c.syl_file:
        review("1.01", "Syllabus text came from a file you supplied. Confirm that students can open the same syllabus inside the course.")
    st = c.syllabus or c.corpus
    lbl = "syllabus" if c.syllabus else "course text"
    if not c.syllabus:
        review("1.02-1.05", "The syllabus text could not be read, so syllabus items (1.02-1.05, 1.16-1.22) were checked against other course text only. "
                            "Give me the syllabus as a file: OAT.exe --reanalyze 99316 --syllabus \"C:\\path\\syllabus.pdf\"")
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
    kw("1.18", r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}|\bext(ension)?\.? ?\d{2,5}\b")
    kw("1.19", r"respon\w+ (time|within)|within \d+ (hours|business|days)|(24|48|72) hours")
    kw("1.20", r"office (location|:)|\broom\b|\bbuilding\b|\bhall\b")
    kw("1.21", r"office hours")
    kw("1.22", r"(?-i:\b(Ph\.?D|Ed\.?D|MSN|MS|MA|MBA|BSN|BS|DNP|MD|APRN|RN)\b)|master'?s|bachelor|doctor(ate)?|degree")
    review("1.23", "Verbal confirmation: the instructor must state copyright clearance (see review report).")

    # ---------- Section 2 ----------
    navtxt = " ".join((l.get("text") or "") for l in (d.get("nav") or {}).get("links", []))
    kw("2.01", r"integrity advocate|proctor|verity|respondus|lockdown|technology (requirements|preparedness)|technical requirements",
       c.corpus + " " + navtxt)
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
    lc = d.get("link_check") or []
    sus = spelling_suspects(c)
    broken = [x for x in lc if x.get("status") in (404, 410, "dns")]
    unreach = [x for x in lc if x.get("status") == "unreachable"]
    if lc:
        host = lambda u: re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
        put("3.05", "0" if broken else "1",
            f"auto: {len(lc)} outside links checked, {len(broken)} broken" + (" (" + ", ".join(sorted({host(x['url']) + ' ' + str(x['status']) for x in broken})[:3]) + ")" if broken else "") +
            (f", {len(unreach)} unreachable or blocked (not counted)" if unreach else "") +
            (f"; {len(sus)} words not in the dictionary, see review" if sus else ""))
    review("3.05", "Only outside links were checked automatically; spelling and incorrect information need a person." +
           (" Words not in the dictionary (typos or technical terms): " + ", ".join(sus) if sus else ""))
    items = [(x.get("Name") or "", _t(x.get("CustomInstructions")) or _t(x.get("Instructions")) or _t(x.get("Description")))
             for x in c.dropbox + c.quizzes] + [(x.get("Name") or "", _t(x.get("Description"))) for x in c.forum_topics]
    if items:
        have = sum(1 for _, ins in items if len(re.sub("<[^>]+>", "", ins or "")) > 25)
        put("3.06", grade_fraction(have / len(items), 0.9), f"auto: instructions present on {have}/{len(items)} assessments")
    dueable = c.dropbox + c.quizzes + c.forum_topics
    due = [x for x in dueable if x.get("DueDate")]
    if dueable:
        put("3.07", grade_fraction(len(due) / len(dueable), 0.9),
            f"auto: due dates on {len(due)}/{len(dueable)} dropboxes, quizzes and discussion topics")
    frac, detail = week_consistency(c)
    if frac is not None:
        put("3.08", "1" if frac >= 0.8 else "0" if frac >= 0.5 else "X", "auto: " + detail)
    review("3.08", "Whether navigation is intuitive is your judgment (see screenshots); the tool only compared the layout of the weekly modules.")

    # ---------- Section 4 / 5 (variety) ----------
    work = c.dropbox + c.quizzes + c.forum_topics
    wnames = [((x.get("Name") or ""), (x.get("Name") or "") + " " + re.sub("<[^>]+>", " ", _t(x.get("CustomInstructions")) or _t(x.get("Instructions")) or _t(x.get("Description")) or ""))
              for x in work] + [(t["title"] or "", t["title"] or "") for t in c.topics] + [(g, g) for g in c.grade_names]

    # per-assessment facts for the Section 5 "Course Objective(s)" and "Rubric" columns
    OBJ = r"objective|outcome|\bSLO|learning goal"
    info = {}
    for x in c.dropbox:
        info[(x.get("Name") or "").strip()] = {"text": _t(x.get("CustomInstructions")), "rubric": bool((x.get("Assessment") or {}).get("Rubrics")), "kind": "dropbox"}
    for x in c.forum_topics:
        rc = x.get("_rubric_count")
        info[(x.get("Name") or "").strip()] = {"text": _t(x.get("Description")), "rubric": (None if rc is None else rc > 0), "kind": "discussion"}
    for x in c.quizzes:
        info[(x.get("Name") or "").strip()] = {"text": _t(x.get("Description")) + " " + _t(x.get("Instructions")), "rubric": None, "kind": "quiz"}
    for p in c.pages:
        info.setdefault((p.get("title") or "").strip(), {"text": p.get("text", "")[:3000], "rubric": None, "kind": "file"})

    def columns(iid, names):
        known = [info[n] for n in names if n in info]
        if not known:
            return
        withtext = [k for k in known if k["text"].strip()]
        if withtext:
            S[iid]["obj"] = grade_fraction(sum(bool(SEARCH(OBJ, k["text"])) for k in withtext) / len(withtext), 0.9, 0.01)
        gradable = [k for k in known if k["kind"] in ("dropbox", "discussion") and k["rubric"] is not None]
        if gradable:
            S[iid]["rubric"] = grade_fraction(sum(k["rubric"] for k in gradable) / len(gradable), 0.9, 0.01)
        elif all(k["kind"] == "quiz" for k in known):
            S[iid]["rubric"] = "NA"

    def variety(iid, pat, pool=None, always=None):
        pool = wnames if pool is None else pool
        allhits = sorted({name.strip() for name, full in pool if SEARCH(pat, full) and name.strip()})
        hits = [h[:45] for h in allhits[:3]]
        if always or hits:
            put(iid, "1", "auto: " + (always or "e.g. " + "; ".join(hits)))
            if iid.startswith("5."):
                columns(iid, allhits or ([(q.get("Name") or "").strip() for q in c.quizzes] if iid == "5.01" else
                                         [(x.get("Name") or "").strip() for x in c.forum_topics] if iid == "5.02" else []))
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
    variety("5.03", r"practice|self.?(check|assess)|study guide|review guide|adaptive|pre-?lab|ungraded|survey|reflect|journal")
    variety("5.05", r"peer review|literature review|article review|website review|critique|peer")
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
        def monday(x):
            return (x - dt.timedelta(days=x.weekday())).date()
        start, end = min(dates), max(dates)
        cs, ce = (d.get("course") or {}).get("StartDate"), (d.get("course") or {}).get("EndDate")
        try:  # use the course's own start/end when available
            start = min(start, dt.datetime.fromisoformat(cs.replace("Z", "+00:00")))
            end = max(end, dt.datetime.fromisoformat(ce.replace("Z", "+00:00")))
        except Exception:
            pass
        weeks = {monday(x) for x in dates}
        span = (monday(end) - monday(start)).days // 7 + 1
        frac = min(1.0, len(weeks) / max(1, span))
        def _words(n):
            return len(re.sub("<[^>]+>", " ", _t(n.get("Body"))).split())
        long_ = sum(1 for n in c.news if _words(n) >= 45)
        put("6.01", grade_fraction(frac, 0.8, 0.3),
            f"auto: announcements in {len(weeks)} of {span} weeks; {long_} of {len(c.news)} are over 45 words (likelier content, not just reminders)")
        review("6.01", "Check that announcements are content-related, not just logistics/reminders.")
    elif c.news:
        put("6.01", "0", f"auto: only {len(c.news)} announcement(s)")
    else:
        put("6.01", "X", "auto: no announcements")
    tools = {(l.get("text") or "").strip() for l in (d.get("nav") or {}).get("links", [])}
    has_ra = any(re.search("retention alert", t, re.I) for t in tools)
    review("6.02", "Outreach to inactive or at-risk students is not visible in D2L data." +
           (" The Retention Alert tool is available in the course; whether you use it is for you to confirm." if has_ra else ""))
    kw("6.03", r"office hours|ask the instructor|q&a|virtual office|drop.?in")
    kw("6.04", r"zoom|teams|webex|live (session|class)|mini.?lesson|lecture|tutorial|video")
    review("6.04", "Posted lectures alone do NOT count; confirm there is live interaction or a lecture + instructor-led discussion.")
    rubrics = sum(1 for x in c.dropbox if (x.get("Assessment") or {}).get("Rubrics"))
    subs = sum(x.get("TotalUsersWithSubmissions") or 0 for x in c.dropbox)
    fbk = sum(x.get("TotalUsersWithFeedback") or 0 for x in c.dropbox)
    if c.dropbox and subs:
        put("6.05", "1" if fbk / subs >= 0.9 else "0" if fbk else "X",
            f"auto: feedback given on {fbk} of {subs} dropbox submissions; rubrics on {rubrics}/{len(c.dropbox)} dropboxes (quiz and exam feedback not visible)")
    elif c.dropbox:
        put("6.05", "1" if rubrics else "0", f"auto: rubrics on {rubrics}/{len(c.dropbox)} dropboxes; no submissions to measure feedback")
    review("6.05", "Check that the feedback is personal (written, audio, video, rubric comments), not only a grade.")
    acts = [(t, t.get("_activity")) for t in c.forum_topics if t.get("_activity")]
    n_topics = len(acts)
    with_inst = [t for t, x in acts if x["instructor_posts"] > 0]
    replies = sum(x["instructor_replies"] for _, x in acts)
    total_inst = sum(x["instructor_posts"] for _, x in acts)
    if n_topics:
        weeks_inst = {dt.date.fromisoformat(x) - dt.timedelta(days=dt.date.fromisoformat(x).weekday())
                      for _, a_ in acts for x in a_["instructor_dates"]}
        put("6.07", grade_fraction(len(with_inst) / n_topics, 0.8, 0.01),
            f"auto: you posted in {len(with_inst)} of {n_topics} discussion topics ({total_inst} posts, {replies} replies) across {len(weeks_inst)} weeks; "
            "counts only, quality not judged")
        if replies:
            put("6.06", "1", f"auto: {replies} instructor replies in discussions (answering student posts)")
        else:
            kw("6.06", r"question|ask|help|q&a", " ".join(x.get("Name") or "" for x in c.forums + c.forum_topics), "forum names")
    else:
        kw("6.06", r"question|ask|help|q&a", " ".join(x.get("Name") or "" for x in c.forums + c.forum_topics), "forum names")
        review("6.07", "Instructor replies in discussions could not be counted; check the forums.")
    review("6.07", "Check that your discussion replies are probing and content-based, not just 'good job'.")
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
    fb = " ; ".join(t for t in c.titles if not t.lower().endswith((".mp4", ".mp3")))
    kw("7.01", r"check.?in|getting to know|icebreaker|introduce yourself|how.s the course|welcome survey|start.of.course survey", fb)
    kw("7.02", r"mid.?(term|course|semester)\W*(feedback|survey|evaluation|check)|(feedback|survey|evaluation)\W*mid", fb)
    kw("7.03", r"end.of.(course|semester)|wrap.?up|course evaluation|final (feedback|survey)|closing (survey|message)", fb)
    kw("7.04", r"course (feedback|evaluation)|student (feedback|evaluation)|feedback survey|\bsurvey\b|suggestion box", fb)
    review("7.05", "Verbal confirmation: instructor reviews learner feedback and adjusts the course.")

    # ---------- Section 8 (accessibility, measurable parts) ----------
    html = [p["stats"] for p in c.pages if p.get("kind") == "html"]
    gen = sum(s.get("generic_link_text", 0) for s in html)
    red = sum(s.get("red_text", 0) for s in html)
    blink = sum(s.get("blink", 0) for s in html)
    office = [p for p in c.pages if p.get("kind") in ("docx", "pptx")]
    o_imgs = sum(p["stats"].get("images", 0) for p in office)
    o_alt = sum(p["stats"].get("images_with_alt", 0) for p in office)
    pdfs = [p for p in c.pages if p.get("kind") == "pdf"]
    badpdf = [p for p in pdfs if not p["stats"].get("tagged") or p["stats"].get("looks_scanned")]
    review("8.01", "External tools/publisher accessibility (e.g. Sherpath, Integrity Advocate): instructor confirms with the publisher.")
    if html:
        put("8.02", "1" if not blink else "0", f"auto: {blink} blinking elements in {len(html)} HTML pages; heading structure needs a manual check")
        put("8.03", "0" if red else "1", f"auto: {red} red-text uses (color-only cue risk); contrast needs a manual check")
        put("8.06", "1" if not gen else "0", f"auto: {gen} 'click here'-style links; keyboard-only use needs a manual check")
    else:
        review("8.02", "No HTML pages in the course to inspect; check headings, animations and layout by hand.")
        review("8.03", "No HTML pages to inspect; check font size/contrast and color-only cues by hand (also inside PowerPoints/Word files).")
        review("8.06", "No HTML pages to inspect; check that links use descriptive text.")
    n_vid = len(c.videos)
    if n_vid or o_imgs:
        bits = []
        if n_vid:
            bits.append(f"{n_vid} uploaded videos: captions/transcripts must be checked (D2L auto-captions need a read-through)")
        if o_imgs:
            bits.append(f"{o_alt} of {o_imgs} images in Word/PowerPoint files have alt text")
        put("8.04", "0" if (n_vid or o_alt < o_imgs) else "1", "auto: " + "; ".join(bits))
        review("8.04", "Confirm captions on every video and alt text on images.")
    else:
        review("8.04", "No images or videos found; check captions/transcripts by hand.")
    if pdfs or office:
        notes = []
        if pdfs:
            notes.append(f"{len(badpdf)} of {len(pdfs)} PDFs untagged or scanned")
        if office:
            notes.append(f"{len(office)} Word/PowerPoint files (accessibility checker not run)")
        put("8.05", "0" if badpdf else "1", "auto: " + "; ".join(notes))
        review("8.05", "Run Word/PowerPoint's accessibility checker on uploaded files, or use the college's ADA tool (Panorama).")
    else:
        review("8.05", "No uploaded files found.")
    review("8.07", "LMS-built components are accessible by default; confirm.")
    kw("8.08", r"accommodation")
    review("8.09", "Extended time / accessible question types: check quiz settings.")

    # ---------- Section 9 ----------
    q = d.get("qwickly") or {}
    rec = q.get("records") or {}
    qdates = [dt.date.fromisoformat(x) for x in rec.get("dates", [])]
    try:  # only dates inside the course's own window count (the page also shows today's date etc.)
        cs = dt.datetime.fromisoformat(d["course"]["StartDate"].replace("Z", "+00:00")).date()
        ce = dt.datetime.fromisoformat(d["course"]["EndDate"].replace("Z", "+00:00")).date()
        qdates = [x for x in qdates if cs - dt.timedelta(days=3) <= x <= ce + dt.timedelta(days=3)]
    except Exception:
        cs = ce = None
    if q.get("found") and len(qdates) >= 2:
        s0, e0 = (cs, ce) if cs and ce else (min(qdates), max(qdates))
        weeks = {x - dt.timedelta(days=x.weekday()) for x in qdates}
        span = ((e0 - dt.timedelta(days=e0.weekday())) - (s0 - dt.timedelta(days=s0.weekday()))).days // 7 + 1
        put("9.01", grade_fraction(min(1.0, len(weeks) / max(1, span)), 0.8, 0.3),
            f"auto: Qwickly Records show {len(qdates)} attendance dates covering {len(weeks)} of {span} course weeks "
            f"({min(qdates):%m/%d}-{max(qdates):%m/%d})")
        review("9.01", "Confirm attendance was taken for every class meeting.")
    elif q.get("found"):
        review("9.01", "Qwickly opened" + (" and its Records tab was read" if rec.get("records_opened") else "") +
               ", but no attendance dates inside this course's dates were found" +
               (" (the course may have ended, or the roster is empty)" if True else "") +
               ". Check the attendance records by hand. Qwickly was not captured because it lists student names.")
    else:
        review("9.01", "Qwickly could not be opened automatically (Course Performance > Attendance Qwickly). Check attendance records by hand.")
    review("9.02", "Participation visible to students: check the student view of Qwickly / gradebook.")
    gi = [g for g in c.grades if isinstance(g, dict)]
    if gi:
        hidden = [g.get("Name") for g in gi if g.get("IsHidden")]
        weighted = (d.get("grade_setup") or {}).get("GradingSystem") == "Weighted"
        cats = [g for g in gi if g.get("GradeType") == "Category"]
        wsum = sum((g.get("Weight") or 0) for g in cats) if weighted else None
        note = f"auto: {len(gi)} grade items" + (f"; weighted, category weights total {wsum:g}%" if weighted and cats else "")
        ok = (not weighted) or not cats or abs((wsum or 0) - 100) < 0.5
        put("9.03", "1" if ok else "0", note + "; verify against the syllabus grading method")
        n_assess = len(c.dropbox) + len(c.quizzes) + len(c.forum_topics)
        put("9.04", grade_fraction(min(1.0, len(gi) / max(1, n_assess)), 0.8, 0.2),
            f"auto: {len(gi)} grade items for {n_assess} dropboxes/quizzes/discussions (plus external work such as Sherpath)")
        put("9.06", "1" if not hidden else "0",
            "auto: no grade items hidden from students" if not hidden else f"auto: {len(hidden)} hidden grade items: " + "; ".join(hidden[:3]))
    else:
        review("9.03", "No grade items could be read (role may not allow it).")
    review("9.05", "Current/accurate grades need a look at the gradebook.")
    review("9.07", "Overall/current grade visibility: check Grades > Settings or the student view.")

    # ---------- Panorama (ADA tool) and the student view ----------
    pan = d.get("panorama") or {}
    if pan.get("found") and (pan.get("metrics") or pan.get("text_excerpt")):
        m = pan.get("metrics") or {}
        review("8.05", f"The college's Panorama (ADA) report was read (percentages {m.get('percent')}, counts {m.get('counts')}). "
                       f"See screenshots/panorama.png and interpret it for Section 8. Excerpt: {pan.get('text_excerpt', '')[:260]}")
        if "8.05" in S:
            S["8.05"]["note"] += f" | Panorama figures: {m.get('percent')} / {m.get('counts')}"
    sv = d.get("student_view") or {}
    if sv.get("switched"):
        REVIEW[:] = [r for r in REVIEW if r["id"] not in ("9.06", "9.07", "9.02")]
        if sv.get("final_grade_shown") is not None:
            put("9.07", "1" if sv["final_grade_shown"] else "X",
                "auto (student view): the final grade " + ("is shown" if sv["final_grade_shown"] else "is NOT shown") + " on the student grades page")
        if sv.get("items_total"):
            f = sv["items_visible"] / sv["items_total"]
            put("9.06", grade_fraction(f, 0.9, 0.01), f"auto (student view): {sv['items_visible']} of {sv['items_total']} grade items are visible to students")
        part = [g for g in c.grade_names if re.search(r"participation|attendance", g, re.I)]
        if sv.get("attendance_link") or part:
            put("9.02", "1", "auto (student view): " + ("students have the Qwickly attendance link" if sv.get("attendance_link") else "") +
                ("; " if sv.get("attendance_link") and part else "") + (f"gradebook has '{part[0]}'" if part else "") +
                " (the tool cannot see students' own attendance records)")
        else:
            review("9.02", "Participation visibility: no attendance link or participation grade item was visible to students.")
        if sv.get("syllabus_link") is False:
            review("1.01", "The Syllabus link was NOT visible in the student view.")
    elif sv.get("attempted"):
        review("9.07", "The student-view check could not run (" + (sv.get("note") or sv.get("error") or "unknown") + "); check Grades > Settings or the student view by hand.")

    # ---------- header ----------
    course = d.get("course") or {}
    staff_name = f"{who.get('LastName', '')}, {who.get('FirstName', '')}".strip(", ")
    header = {"instructor": staff_name, "date": dt.date.today().strftime("%m/%d/%Y"),
              "course_id": course.get("Code", ""), "course_title": course.get("Name", "")}
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
