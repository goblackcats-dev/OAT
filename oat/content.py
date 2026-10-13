"""Pull text and accessibility stats out of course files (HTML / PDF / DOCX)."""
import io
import re
import zipfile
from html.parser import HTMLParser

GENERIC_LINKS = re.compile(r"^(click here|here|link|read more|this link|more)$", re.I)


class _P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text, self.imgs, self.imgs_no_alt, self.imgs_empty_alt = [], 0, 0, 0
        self.links, self.generic_links, self.headings = 0, 0, 0
        self.red, self.blink, self.fonts, self.tables = 0, 0, set(), 0
        self._a, self._skip = None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "img":
            self.imgs += 1
            if "alt" not in a:
                self.imgs_no_alt += 1
            elif not (a["alt"] or "").strip():
                self.imgs_empty_alt += 1
        if tag == "a" and a.get("href"):
            self.links += 1
            self._a = []
        if re.fullmatch(r"h[1-6]", tag):
            self.headings += 1
        if tag in ("blink", "marquee"):
            self.blink += 1
        if tag == "table":
            self.tables += 1
        style = (a.get("style") or "") + " " + (a.get("color") or "")
        if re.search(r"color\s*:\s*(red|#f00\b|#ff0000|rgb\(\s*255\s*,\s*0\s*,\s*0)", style, re.I):
            self.red += 1
        for f in re.findall(r"font-family\s*:\s*([^;\"']+)", style, re.I):
            self.fonts.add(f.strip().lower())

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "a" and self._a is not None:
            label = " ".join(self._a).strip()
            if GENERIC_LINKS.match(label) or re.match(r"^https?://", label):
                self.generic_links += 1
            self._a = None

    def handle_data(self, d):
        if self._skip:
            return
        self.text.append(d)
        if self._a is not None:
            self._a.append(d)


def html_info(html):
    p = _P()
    try:
        p.feed(html or "")
    except Exception:
        pass
    text = re.sub(r"\s+", " ", " ".join(p.text)).strip()
    return text, {"images": p.imgs, "images_missing_alt": p.imgs_no_alt,
                  "images_empty_alt": p.imgs_empty_alt, "links": p.links,
                  "generic_link_text": p.generic_links, "headings": p.headings,
                  "red_text": p.red, "blink": p.blink, "tables": p.tables,
                  "fonts": sorted(p.fonts)}


def pdf_info(data):
    try:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        text = " ".join((pg.extract_text() or "") for pg in r.pages[:40])
        root = r.trailer["/Root"]
        tagged = bool(root.get("/MarkInfo", {}).get("/Marked")) if "/MarkInfo" in root else False
        has_lang = "/Lang" in root
        return re.sub(r"\s+", " ", text).strip(), {"pages": len(r.pages), "text_chars": len(text),
                                                   "tagged": tagged, "has_language": has_lang,
                                                   "looks_scanned": len(text.strip()) < 50 * max(1, len(r.pages))}
    except Exception as e:
        return "", {"error": str(e)}


def docx_info(data):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        xml = z.read("word/document.xml").decode("utf8", "ignore")
        text = re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n"))
        return re.sub(r"\s+", " ", text).strip(), {"images": len(re.findall(r"<w:drawing", xml)),
                                                   "images_with_alt": len(re.findall(r'descr="[^"]+"', xml)),
                                                   "headings": len(re.findall(r'w:pStyle w:val="Heading', xml))}
    except Exception as e:
        return "", {"error": str(e)}


def pptx_info(data):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        slides = sorted(n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
        text, pics, alt = [], 0, 0
        for n in slides:
            xml = z.read(n).decode("utf8", "ignore")
            text += re.findall(r"<a:t>([^<]*)</a:t>", xml)
            pics += len(re.findall(r"<p:pic>", xml))
            alt += len(re.findall(r'<p:cNvPr[^>]*\bdescr="[^"]+"', xml))
        return " ".join(text), {"slides": len(slides), "images": pics, "images_with_alt": alt}
    except Exception as e:
        return "", {"error": str(e)}


def extract(name, data):
    n = name.lower().split("?")[0]
    if n.endswith((".html", ".htm")):
        t, s = html_info(data.decode("utf8", "ignore"))
        return "html", t, s
    if n.endswith(".pdf"):
        t, s = pdf_info(data)
        return "pdf", t, s
    if n.endswith(".docx"):
        t, s = docx_info(data)
        return "docx", t, s
    if n.endswith(".pptx"):
        t, st = pptx_info(data)
        return "pptx", t, st
    if n.endswith(".txt"):
        return "txt", data.decode("utf8", "ignore"), {}
    return None, "", {}
