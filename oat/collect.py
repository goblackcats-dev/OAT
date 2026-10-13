"""Collect course data from D2L Brightspace into a JSON file for OAT scoring.

Run on YOUR computer. A browser window opens; log in yourself (including any MFA).
The script never sees or stores your password. It reuses the logged-in browser
session to call D2L's read-only API (GET requests only) and saves screenshots.

    python -m oat.collect https://learn.jalc.edu/d2l/home/105329
    python -m oat.collect 105329 --base https://learn.jalc.edu

Output (in ./out/<course id>/): course.json and screenshots/*.png
"""
import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import content, creds

FETCH_JS = """async (url) => {
  try {
    const r = await fetch(url, {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
    const text = await r.text();
    let body = null;
    try { body = JSON.parse(text); } catch (e) { body = null; }
    return {status: r.status, body: body, text: body === null ? text.slice(0, 500) : null};
  } catch (e) { return {status: 0, body: null, text: String(e)}; }
}"""


BYTES_JS = """async (url) => {
  try {
    const r = await fetch(url, {credentials: 'same-origin'});
    if (!r.ok) return {status: r.status, b64: null};
    const buf = new Uint8Array(await r.arrayBuffer());
    if (buf.length > 6000000) return {status: 413, b64: null};
    let bin = ''; const CH = 0x8000;
    for (let i = 0; i < buf.length; i += CH) bin += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
    return {status: 200, b64: btoa(bin)};
  } catch (e) { return {status: 0, b64: null}; }
}"""


class D2L:
    def __init__(self, page, base):
        self.page, self.base = page, base.rstrip("/")
        self.errors = {}
        self.versions = {}

    def _eval(self, js, url):
        """page.evaluate that survives mid-navigation errors ("execution context was destroyed")."""
        last = None
        for _ in range(4):
            try:
                return self.page.evaluate(js, url)
            except Exception as e:  # navigation in progress: wait and retry
                last = e
                try:
                    self.page.wait_for_load_state("load", timeout=15000)
                except Exception:
                    pass
                self.page.wait_for_timeout(1500)
        return {"status": 0, "body": None, "b64": None, "text": f"evaluate failed: {last}"}

    def get(self, path, key=None):
        res = self._eval(FETCH_JS, self.base + path)
        if res["status"] != 200:
            self.errors[key or path] = {"status": res["status"], "detail": res["text"]}
            return None
        return res["body"]

    def get_paged(self, path, key=None):
        out, url = [], path
        while url:
            body = self.get(url, key)
            if body is None:
                break
            if isinstance(body, list):
                out += body
                break
            out += body.get("Objects") or body.get("Items") or []
            nxt = body.get("Next")
            url = re.sub(r"^https?://[^/]+", "", nxt) if nxt else None
        return out

    def get_bytes(self, path):
        res = self._eval(BYTES_JS, path if path.startswith("http") else self.base + path)
        return base64.b64decode(res["b64"]) if res.get("status") == 200 and res.get("b64") else None

    def load_versions(self):
        for p in self.get("/d2l/api/versions/", "versions") or []:
            self.versions[p["ProductCode"]] = p["LatestVersion"]

    def lp(self, rest):
        return f"/d2l/api/lp/{self.versions.get('lp', '1.50')}{rest}"

    def le(self, rest):
        return f"/d2l/api/le/{self.versions.get('le', '1.80')}{rest}"


def logged_in(d2l):
    try:
        res = d2l.page.evaluate(FETCH_JS, d2l.base + "/d2l/api/lp/1.0/users/whoami")
    except Exception:
        return None
    return res["body"] if res["status"] == 200 else None


def diagnose(page, base):
    """Print whether this computer can reach the login servers (helps with VPN/campus-only SSO)."""
    import socket
    from urllib.parse import urlparse
    hosts = {urlparse(base).hostname, "adfs.jalc.edu"}
    try:
        hosts.add(urlparse(page.url).hostname)
    except Exception:
        pass
    for h in sorted(x for x in hosts if x):
        try:
            ip = socket.gethostbyname(h)
            s = socket.create_connection((h, 443), timeout=6)
            s.close()
            print(f"  network check: {h} -> {ip}, port 443 reachable")
        except Exception as e:
            print(f"  network check: {h} NOT reachable from this computer ({e})")


def fill_login_form(page, login):
    """Fill and submit a username/password form on ANY page (Microsoft ADFS, plain D2L, Simple Syllabus SSO).
    Returns True if a form was found and submitted."""
    try:
        user = page.locator("#userNameInput, input[name='UserName'], input[name='userName'], "
                            "input#userName, input[type='email'], input[name='loginfmt']").first
        pwd = page.locator("#passwordInput, input[type='password']").first
        user.wait_for(timeout=15000)
        user.fill(login["u"])
        pwd.wait_for(timeout=5000)
        pwd.fill(login["p"])
        submit = page.locator("#submitButton, input[type='submit'], button[type='submit']").first
        if submit.count():
            submit.click()
        else:
            pwd.press("Enter")
        return True
    except Exception:
        return False


def try_auto_login(d2l, login):
    """Fill the standard login form. Returns True if the session became logged in."""
    if not fill_login_form(d2l.page, login):
        return False
    end = time.time() + 25
    while time.time() < end:
        if logged_in(d2l):
            return True
        d2l.page.wait_for_timeout(1500)
    return False


def ensure_login(d2l, login=None, minutes=10):
    """Return (whoami, how) where how is 'session', 'auto', or 'manual'."""
    who = logged_in(d2l)
    if who:
        return who, "session"
    how = "manual"
    if login:
        print("Logging in with the saved login...")
        if try_auto_login(d2l, login):
            return logged_in(d2l), "auto"
        print("Automatic login did not complete (changed password, MFA, or a login page I don't recognize).")
        print("  current page:", d2l.page.url[:120])
        diagnose(d2l.page, d2l.base)
    print("Please finish logging in in the browser window (waiting up to %d minutes)..." % minutes)
    end = time.time() + minutes * 60
    while time.time() < end:
        who = logged_in(d2l)
        if who:
            return who, "manual_after_auto_failed" if login else "manual"
        d2l.page.wait_for_timeout(2000)
    sys.exit("Timed out waiting for login.")


def rich(x):
    """D2L rich text -> plain string (handles nested {'Text': {'Text','Html'}})."""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return rich(x.get("Text") or x.get("Html") or "")
    return ""


def flatten_toc(modules, trail=()):
    """Yield (module path, topic) for every topic in the table of contents."""
    for m in modules:
        here = trail + (m.get("Title", ""),)
        yield here, m, None
        for t in m.get("Topics") or []:
            yield here, m, t
        yield from flatten_toc(m.get("Modules") or [], here)


CHECK_LINKS = True
FILE_EXT = (".html", ".htm", ".pdf", ".docx", ".pptx", ".txt")
MAX_PAGES = 150


def fetch_pages(d2l, topics):
    """Download course files (syllabus, pages, PDFs) and extract text + accessibility stats."""
    out = []
    for t in topics:
        url = t.get("url") or ""
        if len(out) >= MAX_PAGES or not url or url.startswith("http") and "/content/" not in url:
            continue
        if not url.lower().split("?")[0].endswith(FILE_EXT):
            continue
        blob = d2l.get_bytes(url)
        if blob is None:
            out.append({"topic_id": t["id"], "title": t["title"], "url": url, "error": "download failed"})
            continue
        kind, text, stats = content.extract(url, blob)
        out.append({"topic_id": t["id"], "title": t["title"], "url": url, "kind": kind,
                    "module_path": t["module_path"], "bytes": len(blob),
                    "text": text[:30000], "stats": stats})
    return out


def gather_links(data):
    """Every outside web link found in announcements, descriptions and uploaded files (deduped)."""
    found = {}

    def add(u, where):
        u = u.rstrip(".,;)")
        if u.startswith("http") and "/d2l/" not in u and "jalc.edu" not in u.split("/")[2]:
            found.setdefault(u, where)
    for n in data.get("announcements") or []:
        for u in re.findall(r"https?://[^\s\"'<>)\\]+", json.dumps(n.get("Body"))):
            add(u, "announcement: " + (n.get("Title") or "")[:40])
    for m in data.get("modules") or []:
        for u in re.findall(r"https?://[^\s\"'<>)]+", m.get("description") or ""):
            add(u, "module: " + (m.get("title") or "")[:40])
    for t in data.get("topics") or []:
        add(t.get("url") or "", "content link: " + (t.get("title") or "")[:40])
        for u in re.findall(r"https?://[^\s\"'<>)]+", t.get("description") or ""):
            add(u, "topic: " + (t.get("title") or "")[:40])
    for p in data.get("pages") or []:
        for u in (p.get("stats") or {}).get("hyperlinks", []):
            add(u, "file: " + (p.get("title") or "")[:40])
    return found


def check_links(found, limit=120):
    """HEAD/GET each link from this computer. 404/410/DNS failures are 'broken'; blocked or slow ones are
    reported separately and are NOT counted as broken."""
    import socket
    import urllib.error
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    ua = {"User-Agent": "Mozilla/5.0 (OAT link check)"}

    def one(item):
        url, where = item
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(url, method=method, headers=ua)
                with urllib.request.urlopen(req, timeout=12) as r:
                    return {"url": url, "where": where, "status": r.status}
            except urllib.error.HTTPError as e:
                if method == "HEAD" and e.code in (400, 403, 405, 501):
                    continue
                return {"url": url, "where": where, "status": e.code}
            except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
                reason = str(getattr(e, "reason", e))
                kind = "dns" if "Name or service not known" in reason or "getaddrinfo" in reason or "nodename" in reason else "unreachable"
                if method == "HEAD" and kind == "unreachable":
                    continue
                return {"url": url, "where": where, "status": kind}
        return {"url": url, "where": where, "status": "unreachable"}
    items = list(found.items())[:limit]
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(one, items))


def collect(d2l, org):
    data = {"orgUnitId": org, "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    d2l.load_versions()
    data["versions"] = d2l.versions
    data["course"] = d2l.get(d2l.lp(f"/courses/{org}"), "course")

    toc = d2l.get(d2l.le(f"/{org}/content/toc"), "toc")
    data["toc"] = toc
    topics = []
    for trail, mod, topic in flatten_toc((toc or {}).get("Modules") or []):
        if topic:
            topics.append({"module_path": list(trail), "module_id": mod.get("ModuleId"),
                           "id": topic.get("TopicId"), "title": topic.get("Title"),
                           "type": topic.get("TypeIdentifier"), "url": topic.get("Url"),
                           "hidden": topic.get("IsHidden"), "due": topic.get("DueDate"),
                           "start": topic.get("StartDate"), "end": topic.get("EndDate"),
                           "activity": topic.get("ActivityType"),
                           "description": rich(topic.get("Description"))})
    data["topics"] = topics
    try:
        data["pages"] = fetch_pages(d2l, topics)
    except Exception as e:
        data["pages"] = []
        d2l.errors["pages"] = {"status": 0, "detail": f"{type(e).__name__}: {e}"}

    # Module descriptions/overviews live on the module objects themselves.
    data["modules"] = [{"path": list(t), "id": m.get("ModuleId"), "title": m.get("Title"),
                        "hidden": m.get("IsHidden"),
                        "description": rich(m.get("Description")),
                        "n_topics": len(m.get("Topics") or [])}
                       for t, m, topic in flatten_toc((toc or {}).get("Modules") or []) if topic is None]

    data["announcements"] = d2l.get(d2l.le(f"/{org}/news/"), "announcements")
    data["quizzes"] = d2l.get_paged(d2l.le(f"/{org}/quizzes/"), "quizzes")
    data["dropbox"] = d2l.get(d2l.le(f"/{org}/dropbox/folders/"), "dropbox")
    forums = d2l.get(d2l.le(f"/{org}/discussions/forums/"), "forums") or []
    for f in forums:
        f["Topics"] = d2l.get(d2l.le(f"/{org}/discussions/forums/{f['ForumId']}/topics/"),
                              f"topics:{f['ForumId']}")
    for f in forums:  # how many rubrics are attached to each discussion topic (a count only)
        for t in f.get("Topics") or []:
            r = d2l.get(d2l.le(f"/{org}/discussions/forums/{f['ForumId']}/topics/{t['TopicId']}/rubrics"),
                        f"rubrics:{t['TopicId']}")
            t["_rubric_count"] = len(r) if isinstance(r, list) else None
    # Instructor activity in discussions: COUNTS ONLY. No post text, no student ids and no names are kept.
    me = (d2l.get("/d2l/api/lp/1.0/users/whoami", "whoami") or {}).get("Identifier")
    for f in forums:
        for t in f.get("Topics") or []:
            posts = d2l.get_paged(d2l.le(f"/{org}/discussions/forums/{f['ForumId']}/topics/{t['TopicId']}/posts/"),
                                  f"posts:{t['TopicId']}")
            mine = [p for p in posts if str(p.get("PostingUserId")) == str(me)]
            t["_activity"] = {
                "posts": len(posts), "instructor_posts": len(mine),
                "instructor_replies": sum(1 for p in mine if p.get("ParentPostId")),
                "students_posting": len({p.get("PostingUserId") for p in posts if str(p.get("PostingUserId")) != str(me)}),
                "instructor_dates": sorted({str(p.get("DatePosted", ""))[:10] for p in mine if p.get("DatePosted")})}
    data["forums"] = forums
    data["grade_items"] = d2l.get(d2l.le(f"/{org}/grades/"), "grade_items")
    data["grade_setup"] = d2l.get(d2l.le(f"/{org}/grades/setup/"), "grade_setup")
    data["calendar_events"] = d2l.get(d2l.le(f"/{org}/calendar/events/myEvents/"), "calendar")
    # Only staff are kept: names/roles of non-students. No student names or emails are stored.
    enr = d2l.get(d2l.lp(f"/enrollments/orgUnits/{org}/users/?roleId=&pageSize=200"), "enrollments") or {}
    data["classlist_staff"] = {"Items": [
        {"User": {"DisplayName": (i.get("User") or {}).get("DisplayName")},
         "Role": {"Name": (i.get("Role") or {}).get("Name")}}
        for i in (enr.get("Items") or []) if (i.get("Role") or {}).get("Name") not in (None, "Student")]}
    try:
        links = gather_links(data)
        print(f"Checking {len(links)} outside links...")
        data["link_check"] = check_links(links) if links and CHECK_LINKS else []
    except Exception as e:
        data["link_check"] = []
        d2l.errors["link_check"] = {"status": 0, "detail": str(e)[:200]}
    data["api_errors"] = d2l.errors
    return data


SHOTS = [  # label, path template (org substituted)
    ("home", "/d2l/home/{org}"),
    ("content", "/d2l/le/content/{org}/Home"),
    ("grades", "/d2l/lms/grades/my_grades/main.d2l?ou={org}"),
    ("discussions", "/d2l/le/{org}/discussions/List"),
    ("quizzes", "/d2l/lms/quizzing/user/quizzes_list.d2l?ou={org}"),
    ("dropbox", "/d2l/lms/dropbox/user/folders_list.d2l?ou={org}"),
    ("news", "/d2l/lms/news/main.d2l?ou={org}"),
]


DEEP_TEXT_JS = """() => {
  const out = [];
  const walk = (n) => {
    if (n.nodeType === 3) { const t = n.textContent.trim(); if (t) out.push(t); return; }
    if (n.nodeType !== 1 && n.nodeType !== 11) return;
    if (n.nodeType === 1 && ['SCRIPT','STYLE','NOSCRIPT'].includes(n.tagName)) return;
    if (n.shadowRoot) walk(n.shadowRoot);
    for (const ch of n.childNodes) walk(ch);
  };
  walk(document.body);
  return out.join(' ');
}"""
LINKS_JS = "els => els.map(e => ({text: (e.innerText || e.textContent || '').trim().slice(0, 80), href: e.href || ''}))"


def settle(page, seconds=4):
    """D2L pages never go 'network idle' (widgets keep polling), so wait for load plus a short pause."""
    try:
        page.wait_for_load_state("load", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(int(seconds * 1000))


def _host(url):
    from urllib.parse import urlparse
    try:
        return urlparse(url).hostname
    except Exception:
        return None


def deep_text(page, base=None):
    """Visible text of the page and its iframes, including web-component (shadow DOM) content.
    Each part is flagged `external` when it comes from a different website than D2L itself
    (LTI tools such as an external syllabus or attendance tool load that way)."""
    parts = []
    host = _host(base or page.url)
    for fr in page.frames:
        try:
            t = fr.evaluate(DEEP_TEXT_JS)
            if t and len(t) > 20:
                parts.append({"frame": fr.url, "external": bool(_host(fr.url) and _host(fr.url) != host),
                              "text": t[:30000]})
        except Exception:
            pass
    return parts


def wait_external(page, base, timeout=40):
    """LTI tools load slowly in a frame from another website. Wait until one has real content."""
    host, start = _host(base), time.time()
    end = start + timeout
    while time.time() < end:
        if time.time() - start > 12 and len(page.frames) <= 1:
            return False  # no embedded frame ever appeared: this is a plain page
        for fr in page.frames:
            h = _host(fr.url)
            if fr.url.startswith("http") and h and h != host:
                try:
                    t = fr.evaluate(DEEP_TEXT_JS)
                    if t and len(t) > 300:
                        page.wait_for_timeout(2000)
                        return True
                except Exception:
                    pass
        page.wait_for_timeout(2000)
    return False


MENU_JS = """els => els.map(e => ({
  text: (e.getAttribute('text') || e.getAttribute('aria-label') || e.innerText || e.textContent || '').trim().slice(0, 80),
  href: (() => { const h = e.getAttribute('href') || e.href || '';
                 try { return h ? new URL(h, document.baseURI).href : ''; } catch (x) { return h; } })()}))"""
# Brightspace dropdown items are web components (d2l-menu-item-link), not <a> tags.
MENU_SEL = "d2l-menu-item-link, d2l-menu-item, d2l-link, [role='menuitem'], [role='link']"


def page_links(page):
    out = []
    try:
        out += page.locator("a").evaluate_all(LINKS_JS)
    except Exception:
        pass
    try:
        out += page.locator(MENU_SEL).evaluate_all(MENU_JS)
    except Exception:
        pass
    seen, uniq = set(), []
    for l in out:
        k = (l["text"], l["href"])
        if k not in seen:
            seen.add(k)
            uniq.append(l)
    return uniq


def nav_scan(page, base, org):
    """Open each navbar dropdown and record the links inside (Qwickly is often under Tools/More)."""
    info = {"links": [], "menus": {}}
    try:
        page.goto(f"{base}/d2l/home/{org}", wait_until="domcontentloaded", timeout=30000)
        settle(page)
        info["links"] = page_links(page)
        seen = {(l["text"], l["href"]) for l in info["links"]}
        for label in ["Course Performance", "Communication", "Assessments", "Tools", "Help", "More"]:
            try:
                page.get_by_text(label, exact=True).first.click(timeout=3000)
                page.wait_for_timeout(1000)
                now = page_links(page)
                new = [l for l in now if (l["text"], l["href"]) not in seen and l["text"]]
                info["menus"][label] = new
                seen |= {(l["text"], l["href"]) for l in new}
                page.keyboard.press("Escape")
            except Exception:
                info["menus"][label] = None
    except Exception as e:
        info["error"] = str(e)
    return info


def find_link(nav, pattern):
    allv = list(nav.get("links", []))
    for v in (nav.get("menus") or {}).values():
        allv += v or []
    for l in allv:
        if re.search(pattern, l["text"] or "", re.I) or re.search(pattern, l["href"] or "", re.I):
            return l
    return None


def open_and_capture(page, link, shot_path, base):
    from urllib.parse import urljoin
    link = dict(link, href=urljoin(base + "/", link["href"]))
    out = {"found": True, "link_text": link["text"], "link_href": link["href"]}
    try:
        page.goto(link["href"], wait_until="domcontentloaded", timeout=40000)
        settle(page)
        out["external_loaded"] = wait_external(page, base)
        page.screenshot(path=str(shot_path), full_page=True)
        out["url"] = page.url
        out["frames"] = deep_text(page, base)
    except Exception as e:
        out["error"] = str(e)
    return out


def capture_by_click(page, base, org, name_pattern, shot_path):
    """Fallback: click the visible link/button by its label and capture whatever opens."""
    out = {"found": False}
    try:
        page.goto(f"{base}/d2l/home/{org}", wait_until="domcontentloaded", timeout=30000)
        settle(page)
        loc = page.get_by_role("link", name=re.compile(name_pattern, re.I)).first
        if loc.count() == 0:
            return out
        out.update(found=True, link_text=loc.inner_text().strip())
        loc.click(timeout=8000)
        settle(page)
        out["external_loaded"] = wait_external(page, base)
        page.screenshot(path=str(shot_path), full_page=True)
        out["url"] = page.url
        out["frames"] = deep_text(page, base)
    except Exception as e:
        out["error"] = str(e)
    return out


def qwickly_records(page, base):
    """Qwickly's default page lists students by name. So: open the Records tab and keep ONLY the calendar
    dates found on it. No page text and no screenshot of Qwickly is ever stored."""
    from .analyze import attendance_dates
    out = {"records_opened": False, "dates": []}
    try:
        for loc in (page.get_by_role("link", name=re.compile(r"^\s*records\s*$", re.I)),
                    page.get_by_role("button", name=re.compile(r"^\s*records\s*$", re.I)),
                    page.get_by_text(re.compile(r"^\s*Records\s*$"))):
            if loc.count() > 0:
                loc.first.click(timeout=6000)
                out["records_opened"] = True
                break
        settle(page, 5)
        text = " ".join(f["text"] for f in deep_text(page, base))
        out["dates"] = sorted({d.isoformat() for d in attendance_dates(text)})
        out["page_chars_read"] = len(text)
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def capture_menu_item(page, base, org, item_pattern, shot_path, privacy=False,
                      menus=("Course Performance", "Tools", "More", "Communication", "Assessments")):
    """Open a navbar dropdown and CLICK an item that has no web address (it opens through script).
    Handles the item loading in the same tab or in a new tab/window."""
    out = {"found": False}
    pat = re.compile(item_pattern, re.I)
    for menu in menus:
        try:
            page.goto(f"{base}/d2l/home/{org}", wait_until="domcontentloaded", timeout=30000)
            settle(page, 2)
            page.get_by_text(menu, exact=True).first.click(timeout=4000)
            page.wait_for_timeout(1000)
            item = None
            for loc in (page.get_by_role("menuitem", name=pat), page.get_by_role("link", name=pat),
                        page.get_by_role("button", name=pat), page.get_by_text(pat)):
                if loc.count() > 0:
                    item = loc.first
                    break
            if item is None:
                page.keyboard.press("Escape")
                continue
            out.update(found=True, menu=menu, link_text=item.inner_text().strip()[:80] if item.inner_text() else item_pattern)
            before, start_url = set(page.context.pages), page.url
            item.click(timeout=8000)
            target, end = page, time.time() + 20
            while time.time() < end:
                new = [p for p in page.context.pages if p not in before]
                if new:
                    target = new[0]
                    break
                if page.url != start_url:
                    break
                page.wait_for_timeout(500)
            settle(target)
            out["external_loaded"] = wait_external(target, base)
            out["url"] = target.url.split("?")[0]
            out["new_tab"] = target is not page
            if privacy:   # attendance tools show student names: keep dates only
                out["records"] = qwickly_records(target, base)
            else:
                target.screenshot(path=str(shot_path), full_page=True)
                out["frames"] = deep_text(target, base)
            if target is not page:
                target.close()
            return out
        except Exception as e:
            out["error"] = f"{menu}: {e}"
    return out


SS_BUTTON = re.compile(r"log ?in to simple (higher ed|syllabus) directly|click here to log ?in", re.I)


def follow_simple_syllabus(page, base, org, shot_path, login):
    """The Syllabus tool shows 'could not locate a matching account' with a button that logs in to
    Simple Higher Ed directly. Click it, sign in if asked, and capture what opens."""
    out = {"found": False}
    try:
        btn = None
        for fr in page.frames:
            if _host(fr.url) and _host(fr.url) != _host(base):
                for loc in (fr.get_by_role("button", name=SS_BUTTON), fr.get_by_role("link", name=SS_BUTTON),
                            fr.get_by_text(SS_BUTTON)):
                    if loc.count() > 0:
                        btn = loc.first
                        break
            if btn is not None:
                break
        if btn is None:
            return out
        out["found"] = True
        before, start_url = set(page.context.pages), page.url
        btn.click(timeout=8000)
        target, end = page, time.time() + 20
        while time.time() < end:
            new = [p for p in page.context.pages if p not in before]
            if new:
                target = new[0]
                break
            page.wait_for_timeout(500)
        settle(target, 3)
        if login and target.locator("input[type='password']").count() > 0:
            out["signed_in_with_saved_login"] = fill_login_form(target, login)
            settle(target, 4)
        end = time.time() + 40  # the Simple Syllabus app is a slow single-page app
        while time.time() < end:
            if sum(len(f["text"]) for f in deep_text(target, base)) > 500:
                break
            page.wait_for_timeout(2000)
        target.screenshot(path=str(shot_path), full_page=True)
        out["url"] = target.url
        out["new_tab"] = target is not page
        out["frames"] = deep_text(target, base)
        if target is not page:
            target.close()
    except Exception as e:
        out["error"] = str(e)
    return out


def syllabus_and_qwickly(page, base, org, shots_dir, login=None, follow_direct=True):
    print("Scanning the course menus...")
    nav = nav_scan(page, base, org)
    res = {"nav": nav, "syllabus_tool": {"found": False}, "qwickly": {"found": False}}
    syl = find_link(nav, r"^syllabus$|/syllabus")
    print("Reading the Syllabus tool (it can take up to 40 seconds to load)...")
    if syl and syl.get("href"):
        res["syllabus_tool"] = open_and_capture(page, syl, shots_dir / "syllabus.png", base)
    if not any(f.get("external") for f in res["syllabus_tool"].get("frames", [])):
        res["syllabus_tool"] = capture_by_click(page, base, org, r"^syllabus$", shots_dir / "syllabus.png")
    if follow_direct and any(re.search(r"could not locate a matching account|error has occurred", f.get("text", ""), re.I)
                             for f in res["syllabus_tool"].get("frames", []) if f.get("external")):
        print("The Syllabus tool shows an account error; clicking its direct-login button...")
        res["syllabus_direct"] = follow_simple_syllabus(page, base, org, shots_dir / "syllabus_direct.png", login)
    qw = find_link(nav, r"qwickly") or find_link(nav, r"attendance")
    print("Opening Qwickly attendance..." if qw else "No Qwickly link found in the menus.")
    if qw and qw.get("href") and not qw["href"].startswith("javascript"):
        res["qwickly"] = {"found": True, "link_text": qw["text"]}
        try:
            page.goto(__import__("urllib.parse", fromlist=["urljoin"]).urljoin(base + "/", qw["href"]), wait_until="domcontentloaded", timeout=40000)
            settle(page)
            wait_external(page, base)
            res["qwickly"]["records"] = qwickly_records(page, base)
        except Exception as e:
            res["qwickly"]["error"] = str(e)[:200]
    if qw and not res["qwickly"].get("records"):
        print("Qwickly has no web address, so clicking it from the menu...")
        res["qwickly"] = capture_menu_item(page, base, org, r"qwickly", None, privacy=True)
    return res


def term_name(code):
    """'ADN_207_H1_FL2025' -> 'Fall 2025' (best effort)."""
    m = re.search(r"(FL|FA|SP|SU|WI|SM)(20\d{2})", code or "", re.I)
    if not m:
        return ""
    return {"FL": "Fall", "FA": "Fall", "SP": "Spring", "SU": "Summer", "SM": "Summer", "WI": "Winter"}[m.group(1).upper()] + " " + m.group(2)


def mode_guess(code):
    """Guess online / hybrid / HyFlex from the section token (V=online, H=hybrid, HF=HyFlex). Only a suggestion."""
    for tok in re.split(r"[_\-\s]", code or ""):
        if re.fullmatch(r"(HF|HYF)\d*", tok, re.I):
            return "HyFlex"
        if re.fullmatch(r"H\d+", tok, re.I):
            return "Hybrid"
        if re.fullmatch(r"(V|O|W|OL)\d+", tok, re.I):
            return "Online"
    return ""


def list_my_courses(d2l):
    """Courses where I am staff (not a student), newest first. Names/ids/dates only."""
    out, url = [], d2l.lp("/enrollments/myenrollments/?orgUnitTypeId=3")
    for _ in range(10):
        body = d2l.get(url, "myenrollments")
        if not isinstance(body, dict):
            break
        for it in body.get("Items") or []:
            ou, ac = it.get("OrgUnit") or {}, it.get("Access") or {}
            role = ac.get("ClasslistRoleName") or ""
            if re.search(r"instructor|professor|faculty|teacher|lead", role, re.I) and not re.search(r"student", role, re.I):
                end = str(ac.get("EndDate") or "")[:10]
                out.append({"id": str(ou.get("Id")), "code": ou.get("Code") or "", "name": ou.get("Name") or "",
                            "role": role, "active": bool(ac.get("IsActive")), "end": end,
                            "term": term_name(ou.get("Code") or ou.get("Name") or ""),
                            "mode": mode_guess(ou.get("Code") or ou.get("Name") or "")})
        pi = body.get("PagingInfo") or {}
        if pi.get("HasMoreItems") and pi.get("Bookmark"):
            url = d2l.lp("/enrollments/myenrollments/?orgUnitTypeId=3&bookmark=" + str(pi["Bookmark"]))
        else:
            break
    return sorted(out, key=lambda x: x["end"], reverse=True)


def collect_one(d2l, page, base, org, outdir, how, login=None, shots=True, full=True):
    """Collect one course. `full=False` skips the slow extras (screenshots, direct Simple Syllabus login)."""
    import traceback
    (outdir / "screenshots").mkdir(parents=True, exist_ok=True)
    try:
        page.goto(f"{base}/d2l/home/{org}", wait_until="domcontentloaded", timeout=30000)
        settle(page)
    except Exception:
        pass
    d2l.errors = {}
    print(f"Reading course {org} (modules, quizzes, discussions, grades, files)...")
    try:
        data = collect(d2l, org)
    except Exception:
        data = {"orgUnitId": org, "fatal": traceback.format_exc(), "api_errors": dict(d2l.errors)}
        print("Collection hit an error (partial data will still be saved):\n" + data["fatal"])
    data["login_method"] = how
    data["whoami"] = logged_in(d2l)
    try:
        extra = syllabus_and_qwickly(page, base, org, outdir / "screenshots", login, follow_direct=full)
        data["nav"], data["syllabus_tool"], data["qwickly"] = extra["nav"], extra["syllabus_tool"], extra["qwickly"]
        if extra.get("syllabus_direct"):
            data["syllabus_direct"] = extra["syllabus_direct"]
    except Exception as e:
        data["qwickly"] = {"found": False, "error": str(e)}
    if shots and full:
        print("Taking screenshots...")
        for label, path in SHOTS:
            try:
                page.goto(base + path.format(org=org), wait_until="domcontentloaded", timeout=30000)
                settle(page)
                page.screenshot(path=str(outdir / "screenshots" / f"{label}.png"), full_page=True)
            except Exception as e:  # screenshots are best-effort
                data.setdefault("screenshot_errors", {})[label] = str(e)
    path = outdir / "course.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"Wrote {path}")
    if data["api_errors"]:
        print("Some API calls failed (see api_errors in course.json):", ", ".join(data["api_errors"]))
    return path, data


def run_collect(course, base_hint=None, out="out", profile="session", headless=False,
                browser_path=None, shots=True, login=None, channel=None, no_wait=False,
                extra_orgs=(), pick=None):
    """Log in once, collect the main course in full, then (lighter) each extra course.
    `pick(courses) -> {"include": [ids], "meets": {id: n}}` lets the caller choose which courses to include."""
    m = re.match(r"(https?://[^/]+)/d2l/home/(\d+)", course)
    if m:
        base, org = m.group(1), m.group(2)
    elif course.isdigit() and base_hint:
        base, org = base_hint, course
    else:
        sys.exit("Give a full course URL like https://learn.jalc.edu/d2l/home/99316")
    extras, my_courses, choice = [], [], {}
    with sync_playwright() as p:
        kw = dict(headless=headless, viewport={"width": 1280, "height": 900})
        if browser_path:
            kw["executable_path"] = browser_path
        elif channel:
            kw["channel"] = channel
        ctx = p.chromium.launch_persistent_context(profile, **kw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{base}/d2l/home/{org}")
        d2l = D2L(page, base)
        how = "skipped"
        if not no_wait:
            who, how = ensure_login(d2l, login)
            print("Logged in as:", (who or {}).get("FirstName"), (who or {}).get("LastName"))
            try:  # let any post-login redirects finish before reading data
                settle(page)
            except Exception:
                pass
        if pick is not None or extra_orgs:
            try:
                my_courses = list_my_courses(d2l)
            except Exception as e:
                print("Could not list your courses:", e)
            if pick is not None and my_courses:
                choice = pick(my_courses) or {}
                extra_orgs = [i for i in choice.get("include", []) if i != org]
        path, data = collect_one(d2l, page, base, org, Path(out) / org, how, login, shots, full=True)
        for xo in extra_orgs:
            try:
                xp, xd = collect_one(d2l, page, base, xo, Path(out) / xo, how, login, shots=False, full=False)
                extras.append((xo, xd))
            except Exception as e:
                print(f"Skipping course {xo}: {e}")
        try:
            ctx.close()
        except Exception:
            pass
    data["_my_courses"] = my_courses
    data["_course_choice"] = choice
    path.write_text(json.dumps(data, indent=2, default=str))   # keep the course list with the saved data
    return path, data, how, extras


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("course", help="course URL (https://.../d2l/home/ID) or numeric org unit id")
    ap.add_argument("--base", help="D2L base URL when passing a numeric id")
    ap.add_argument("--out", default="out")
    ap.add_argument("--profile", default="session", help="browser profile dir (keeps you logged in)")
    ap.add_argument("--no-shots", action="store_true")
    ap.add_argument("--headless", action="store_true", help="no browser window (testing only)")
    ap.add_argument("--browser-path", help="use this Chromium/Chrome executable instead of the Playwright one")
    ap.add_argument("--no-wait", action="store_true", help="skip login wait (testing only)")
    a = ap.parse_args()
    run_collect(a.course, a.base, a.out, a.profile, a.headless, a.browser_path,
                not a.no_shots, None, None, a.no_wait)


if __name__ == "__main__":
    main()
