"""Combine per-course results into ONE rubric score using the rubric's own scale:
1 = present in ALL my courses, 0 = present in SOME (or still developing), X = in none, NA = not applicable."""


def _combine_scores(vals):
    raw = [v for v in vals if v not in (None, "")]
    vals = [v for v in raw if v != "NA"]
    if not vals:
        return "NA" if raw else None
    if all(v == "1" for v in vals):
        return "1"
    if all(v == "X" for v in vals):
        return "X"
    return "0"


def combine(results, primary=0):
    """results: list of (label, analyze()-result). Returns a result shaped like analyze()'s, scored across all courses."""
    base = results[0][1] if primary == 0 else results[primary][1]
    out = {k: v for k, v in base.items() if k != "items"}
    out["items"] = {}
    ids = sorted({i for _, r in results for i in r["items"]})
    for iid in ids:
        per = [(lab, r["items"].get(iid)) for lab, r in results]
        have = [(lab, v) for lab, v in per if v]
        score = _combine_scores([v.get("score") for _, v in have])
        if score is None:
            continue
        item = {"score": score}
        if len(have) > 1:
            parts = [f"{lab}: {v.get('score')}" for lab, v in have]
            primary_note = (results[primary][1]["items"].get(iid) or {}).get("note", "")
            item["note"] = ((primary_note + " | ") if primary_note else "") + "all courses: " + ", ".join(parts)
        else:
            item["note"] = have[0][1].get("note", "")
        for col in ("obj", "rubric"):
            cv = _combine_scores([v.get(col) for _, v in have])
            if cv is not None:
                item[col] = cv
        out["items"][iid] = item
    # keep every course's review reasons, once per id
    seen, merged = set(), []
    for lab, r in results:
        for x in r.get("review", []):
            if x["id"] not in seen:
                seen.add(x["id"])
                merged.append(x)
    out["review"] = merged
    out["courses_scored"] = [lab for lab, _ in results]
    return out
