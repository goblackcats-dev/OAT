"""Read the OAT Assessment Schedule spreadsheet to fill the rubric's page-1 header and list my sessions."""
import re
from datetime import datetime

COLS = {"discipline": r"discipline|disipline", "mode": r"^mode", "instructor": r"^instructor", "priority": r"^priority",
        "facilitator": r"facilitator", "when": r"date", "rep1": r"returning faculty 1", "rep2": r"returning faculty 2",
        "new": r"new faculty", "lrc": r"lrc|tlc", "admin": r"admin"}


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def load(path):
    """Return a list of dicts (one per instructor row) from the sign-up sheet."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = next((w for w in wb.worksheets if re.search(r"sign", w.title, re.I)), wb.worksheets[0])
    rows = list(ws.iter_rows(values_only=True))
    head = [_norm(h).lower() for h in rows[0]]
    idx = {}
    for key, pat in COLS.items():
        for i, h in enumerate(head):
            if re.search(pat, h) and i not in idx.values():
                idx[key] = i
                break
    out = []
    for r in rows[1:]:
        d = {k: _norm(r[i]) if i < len(r) else "" for k, i in idx.items()}
        if d.get("instructor"):
            out.append(d)
    return out


def _parse_when(s):
    s = _norm(s)
    for fmt in ("%m/%d/%Y %I:%M%p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def find_instructor(rows, last, first=""):
    last, first = last.lower(), first.lower()
    best = [r for r in rows if r["instructor"].lower().startswith(last + ",")]
    exact = [r for r in best if first and first in r["instructor"].lower()]
    return (exact or best or [None])[0]


def header_for(row):
    """Page-1 header fields from a schedule row (blank where the sheet has nothing yet)."""
    if not row:
        return {}
    when = _parse_when(row.get("when"))
    h = {"facilitator": row.get("facilitator", ""), "faculty_rep_1": row.get("rep1", ""),
         "faculty_rep_2": row.get("rep2", ""), "tlc_rep": row.get("lrc", ""), "admin_rep": row.get("admin", "")}
    extra = []
    if row.get("new"):
        extra.append(("New Faculty (observer)", row["new"]))
    if extra:
        h["additional_attendees"] = extra
    if when:
        h["date"] = when.strftime("%m/%d/%Y") + (" " + when.strftime("%I:%M%p").lstrip("0").lower() if "%" not in row.get("when", "") and ":" in row["when"] else "")
    return {k: v for k, v in h.items() if v}


def my_sessions(rows, my_name):
    """Sessions where I am listed in any committee role (name matched as 'First Last' or 'Last, First')."""
    parts = [p for p in re.split(r"[ ,]+", my_name.strip()) if p]
    if len(parts) < 2:
        return []
    first, last = (parts[1], parts[0]) if "," in my_name else (parts[0], parts[-1])
    out = []
    for r in rows:
        for role, key in (("Facilitator", "facilitator"), ("Faculty rep", "rep1"), ("Faculty rep", "rep2"),
                          ("New member (observer)", "new"), ("LRC rep", "lrc"), ("Admin rep", "admin")):
            v = r.get(key, "").lower()
            if v and last.lower() in v and first.lower() in v:
                out.append({"instructor": r["instructor"], "discipline": r.get("discipline", ""), "role": role,
                            "when": r.get("when", "") or "(date not set yet)"})
    return out
