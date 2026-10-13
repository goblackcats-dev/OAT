"""Roll item scores up into the rubric's summary bands (Sections 4, 5 and 6).

Bands are proposals; the reviewer can override them in scores.json ("bands").
"""


def _score(items, iid):
    return str((items.get(iid) or {}).get("score", "")).upper()


def percent_band(items, prefix, n, skip=()):
    ids = [f"{prefix}.{i:02d}" for i in range(1, n + 1) if f"{prefix}.{i:02d}" not in skip]
    n = len(ids)
    scores = [_score(items, i) for i in ids]
    na = sum(s == "NA" for s in scores)
    applicable = n - na
    if applicable <= 0 or not any(scores):
        return None
    pct = 100 * sum(s == "1" for s in scores) / applicable
    if pct >= 80:
        return "Advanced"
    if pct >= 40:
        return "Essential"
    if pct >= 10:
        return "Being Developed"
    return "Not Evident"


def rsi_band(items):
    reg = [_score(items, f"6.{i:02d}") for i in (1, 2, 3)]
    sub = [_score(items, f"6.{i:02d}") for i in (4, 5, 6, 7, 8)]
    com = [_score(items, f"6.{i:02d}") for i in range(9, 17)]
    if not any(reg + sub + com):
        return None
    r, s = reg.count("1"), sub.count("1")
    comm = [c for c in com if c != "NA"]
    if r == 3 and s == 5 and all(c == "1" for c in comm):
        return "Advanced"
    # Essential: 1 regular + 2 substantive + (communication methods in use)
    if r >= 1 and s >= 2 and any(c == "1" for c in comm):
        return "Essential"
    if r or s:
        return "Being Developed"
    return "Not Evident"


def band_for(section, items):
    if section == 4:
        return percent_band(items, "4", 10)
    if section == 5:
        return percent_band(items, "5", 11, skip=("5.04",))
    if section == 6:
        return rsi_band(items)
