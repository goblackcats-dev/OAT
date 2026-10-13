"""Overlay a scores file onto the flat OAT rubric PDF.

    python -m oat.pdf_fill scores.json rubric.pdf filled.pdf

scores.json:
{
  "header": {"instructor": "...", "date": "...", "course_id": "...", "course_title": "...",
             "in_person_meets": "...", "facilitator": "...", "faculty_rep_1": "...",
             "faculty_rep_2": "...", "tlc_rep": "...", "admin_rep": "...",
             "attendee": "...", "additional_attendee": "..."},
  "items": {"1.01": {"score": "1", "note": "Syllabus in Content > Course Info"}, ...},
  "section_notes": {"section1": "...", ...},
  "strengths": "...", "improvements": "...", "changes": "...",
  "bands": {"4": "Essential", "5": "Advanced", "6": "Essential"}   # optional override
}
Section 5 items may also carry "obj" and "rubric" marks ("1"/"0"/"X"/"NA").
"""
import io
import json
import sys

import pdfplumber
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

from . import rubric_spec as spec
from .scoring import band_for

PAGE_H = 792
INK = (0.05, 0.15, 0.6)


def _wrap(para, width, size):
    out, cur = [], ""
    for word in para.split():
        trial = (cur + " " + word).strip()
        if stringWidth(trial, "Helvetica", size) <= width:
            cur = trial
        else:
            if cur:
                out.append(cur)
            cur = word
    out.append(cur)
    return out


def _lines(pg):
    return pg.extract_text_lines()


def _rows(pg):
    out = []
    for t in pg.find_tables():
        for r in t.rows:
            b = r.bbox
            if b[3] - b[1] > 4:
                out.append(b)
    return out


def _row_for(rows, y):
    hit = [b for b in rows if b[1] - 0.5 <= y <= b[3] + 0.5 and (b[2] - b[0]) > 300]
    if not hit:
        hit = [b for b in rows if b[1] - 0.5 <= y <= b[3] + 0.5]
    return min(hit, key=lambda b: b[3] - b[1]) if hit else None


def locate(pdf):
    """Return {item_id: (page, row_top, row_bottom)} and band / note-box geometry."""
    pos, bands, boxes = {}, {}, {}
    cursors = {}
    page_cache = {}

    def page(n):
        if n not in page_cache:
            pg = pdf.pages[n - 1]
            page_cache[n] = (pg, _lines(pg), _rows(pg), pg.find_tables())
        return page_cache[n]

    def find(n, anchor, any_x=False):
        pg, lines, rows, _ = page(n)
        start = cursors.get(n, 0)
        for l in lines:
            if l["top"] <= start:
                continue
            if (any_x or l["x0"] < 40) and l["text"].startswith(anchor):
                cursors[n] = l["top"]
                row = _row_for(rows, l["top"] + 3)
                return l, row
        raise LookupError(f"anchor not found: page {n} {anchor!r}")

    for iid, n, anchor in spec.ITEMS:
        l, row = find(n, anchor)
        top, bot = (row[1], row[3]) if row else (l["top"], l["bottom"] + 2)
        pos[iid] = (n, top, bot)
    for sec, entries in spec.BANDS.items():
        cursors_save = dict(cursors)
        for name, n, anchor in entries:
            # band rows sit below the item rows; search whole page below the last item
            l, row = find(n, anchor, any_x=True)
            top, bot = (row[1], row[3]) if row else (l["top"], l["bottom"] + 2)
            bands[(sec, name)] = (n, top, bot)
    for key, (n, anchor) in spec.NOTE_BOXES.items():
        pg, lines, rows, tables = page(n)
        for l in lines:
            if l["text"].startswith(anchor):
                for t in tables:
                    if t.bbox[1] <= l["top"] <= t.bbox[3] and len(t.rows) == 2:
                        b = t.rows[1].bbox
                        boxes[key] = (n, b[0], b[1], b[2], b[3])
                break
        if key not in boxes:
            raise LookupError(f"note box not found: {key}")
    return pos, bands, boxes


class Overlay:
    def __init__(self, n_pages):
        self.bufs = {}
        self.cv = {}
        self.n = n_pages

    def c(self, page):
        if page not in self.cv:
            buf = io.BytesIO()
            self.bufs[page] = buf
            self.cv[page] = canvas.Canvas(buf, pagesize=(612, 792))
        return self.cv[page]

    def text(self, page, x, y_top, s, size=8, bold=False):
        c = self.c(page)
        c.setFillColorRGB(*INK)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, PAGE_H - y_top - size * 0.8, s)

    def centered(self, page, x0, x1, row_top, row_bot, s, size=11):
        c = self.c(page)
        c.setFillColorRGB(*INK)
        c.setFont("Helvetica-Bold", size)
        mid = (row_top + row_bot) / 2
        c.drawCentredString((x0 + x1) / 2, PAGE_H - mid - size * 0.35, s)

    def check(self, page, x0, x1, row_top, row_bot):
        c = self.c(page)
        c.setStrokeColorRGB(*INK)
        c.setLineWidth(1.6)
        cx, cy = (x0 + x1) / 2, PAGE_H - (row_top + row_bot) / 2
        p = c.beginPath()
        p.moveTo(cx - 6, cy)
        p.lineTo(cx - 2, cy - 5)
        p.lineTo(cx + 7, cy + 6)
        c.drawPath(p, stroke=1, fill=0)

    def wrapped(self, page, x0, x1, y0, y1, s, size=6.5, leading=None):
        """Draw wrapped text inside the box. Returns the text that did not fit."""
        leading = leading or size * 1.15
        c = self.c(page)
        c.setFillColorRGB(*INK)
        c.setFont("Helvetica", size)
        width = x1 - x0 - 4
        lines = []
        for para in str(s).split("\n"):
            lines += _wrap(para, width, size)
        room = int((y1 - y0 - 2) // leading)
        for i, ln in enumerate(lines[:room]):
            c.drawString(x0 + 2, PAGE_H - y0 - 2 - size - i * leading + size * 0.2, ln)
        return " ".join(lines[room:])

    def merged_page(self, page, base):
        if page in self.cv:
            self.cv[page].save()
            self.bufs[page].seek(0)
            base.merge_page(PdfReader(self.bufs[page]).pages[0])
        return base


def fill_header(ov, pdf, header):
    pg = pdf.pages[0]
    lines = _lines(pg)

    def row_y(label, x_max=60):
        for l in lines:
            if l["x0"] < x_max and l["text"].startswith(label):
                return l["top"]
        raise LookupError(label)

    left = {  # label -> key, value column x0
        "Instructor": "instructor", "Date": "date", "Course ID": "course_id",
        "Course Title": "course_title", "# of In": "in_person_meets",
    }
    for label, key in left.items():
        if header.get(key):
            ov.wrapped(1, 87, 201, row_y(label) - 2, row_y(label) + 24, header[key], size=8)
    right = [  # (label, key) for the ATTENDEE column (x 293-383)
        ("Instructor", "facilitator"), ("Faculty", "faculty_rep_1"),
        ("Date", "faculty_rep_2"), ("Course ID", "tlc_rep"), ("# of In", "admin_rep"),
    ]
    ys = {"facilitator": 201, "faculty_rep_1": 214, "faculty_rep_2": 240,
          "tlc_rep": 266, "admin_rep": 291}
    for _, key in right:
        if header.get(key):
            ov.text(1, 296, ys[key], header[key], size=7.5)
    if header.get("attendee"):
        ov.text(1, 391, 201, header["attendee"], size=7.5)


def build(scores, rubric_path, out_path):
    pos, bands, boxes = locate(pdfplumber.open(rubric_path))
    pdf = pdfplumber.open(rubric_path)
    ov = Overlay(len(pdf.pages))
    fill_header(ov, pdf, scores.get("header", {}))
    overflow = {}
    for iid, v in scores.get("items", {}).items():
        if iid not in pos:
            raise KeyError(f"unknown item id {iid}")
        n, top, bot = pos[iid]
        cols = spec.COLUMNS[n]
        for col, key in (("ident", "score"), ("obj", "obj"), ("rubric", "rubric")):
            val = v.get(key)
            if val is None or col not in cols:
                continue
            val = str(val).upper()
            if val not in spec.VALID_SCORES:
                raise ValueError(f"{iid}: bad score {val!r}")
            ov.centered(n, *cols[col], top, bot, val)
        note = v.get("note")
        if note:
            x0, x1 = cols["notes"]
            rest = ov.wrapped(n, x0, x1, top, bot, note, size=5.5)
            if rest:
                overflow.setdefault("section" + iid.split(".")[0], []).append(f"{iid}: {note}")
    # score bands
    for sec in (4, 5, 6):
        chosen = scores.get("bands", {}).get(str(sec)) or band_for(sec, scores.get("items", {}))
        if chosen:
            n, top, bot = bands[(sec, chosen)]
            ov.check(n, *spec.COLUMNS[n]["ident"], top, bot)
    # notes boxes
    texts = {k: v for k, v in scores.get("section_notes", {}).items()}
    for k, v in scores.items():
        if k in ("strengths", "improvements", "changes"):
            texts[k] = v
    for k, items in overflow.items():
        texts[k] = (texts.get(k, "") + "\n" if texts.get(k) else "") + "\n".join(items)
    for key, text in texts.items():
        n, x0, y0, x1, y1 = boxes[key]
        ov.wrapped(n, x0, x1, y0, y1, text, size=7.5)
    reader = PdfReader(rubric_path)
    w = PdfWriter()
    for i, p in enumerate(reader.pages, start=1):
        w.add_page(ov.merged_page(i, p))
    with open(out_path, "wb") as f:
        w.write(f)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    build(json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3])
