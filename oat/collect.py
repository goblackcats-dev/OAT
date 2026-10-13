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

    def get(self, path, key=None):
        res = self.page.evaluate(FETCH_JS, self.base + path)
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
        res = self.page.evaluate(BYTES_JS, path if path.startswith("http") else self.base + path)
        return base64.b64decode(res["b64"]) if res["status"] == 200 else None

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


def try_auto_login(d2l, login):
    """Fill the standard D2L login form. Returns True if the session became logged in."""
    page = d2l.page
    try:
        # Works for the Microsoft ADFS page (#userNameInput / #passwordInput) and the plain D2L form.
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
    except Exception:
        return False
    end = time.time() + 25
    while time.time() < end:
        if logged_in(d2l):
            return True
        time.sleep(1.5)
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
        time.sleep(2)
    sys.exit("Timed out waiting for login.")


def flatten_toc(modules, trail=()):
    """Yield (module path, topic) for every topic in the table of contents."""
    for m in modules:
        here = trail + (m.get("Title", ""),)
        yield here, m, None
        for t in m.get("Topics") or []:
            yield here, m, t
        yield from flatten_toc(m.get("Modules") or [], here)


FILE_EXT = (".html", ".htm", ".pdf", ".docx", ".txt")
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
                           "description": (topic.get("Description") or {}).get("Text")})
    data["topics"] = topics
    data["pages"] = fetch_pages(d2l, topics)

    # Module descriptions/overviews live on the module objects themselves.
    data["modules"] = [{"path": list(t), "id": m.get("ModuleId"), "title": m.get("Title"),
                        "hidden": m.get("IsHidden"),
                        "description": (m.get("Description") or {}).get("Text"),
                        "n_topics": len(m.get("Topics") or [])}
                       for t, m, topic in flatten_toc((toc or {}).get("Modules") or []) if topic is None]

    data["announcements"] = d2l.get(d2l.le(f"/{org}/news/"), "announcements")
    data["quizzes"] = d2l.get_paged(d2l.le(f"/{org}/quizzes/"), "quizzes")
    data["dropbox"] = d2l.get(d2l.le(f"/{org}/dropbox/folders/"), "dropbox")
    forums = d2l.get(d2l.le(f"/{org}/discussions/forums/"), "forums") or []
    for f in forums:
        f["Topics"] = d2l.get(d2l.le(f"/{org}/discussions/forums/{f['ForumId']}/topics/"),
                              f"topics:{f['ForumId']}")
    data["forums"] = forums
    data["grade_items"] = d2l.get(d2l.le(f"/{org}/grades/"), "grade_items")
    data["grade_setup"] = d2l.get(d2l.le(f"/{org}/grades/setup/"), "grade_setup")
    data["calendar_events"] = d2l.get(d2l.le(f"/{org}/calendar/events/myEvents/"), "calendar")
    data["classlist_staff"] = d2l.get(d2l.lp(f"/enrollments/orgUnits/{org}/users/?roleId=&pageSize=200"),
                                      "enrollments")
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


def qwickly(page, base, org, shots_dir):
    """Best-effort: find and open Qwickly Attendance, screenshot it, and capture visible text.
    Qwickly is an LTI tool inside an iframe, so the layout can differ; the screenshot is the
    evidence the reviewer should look at."""
    info = {"found": False}
    try:
        page.goto(f"{base}/d2l/home/{org}", wait_until="networkidle", timeout=30000)
        info["nav_links"] = [t.strip() for t in page.locator("a").all_inner_texts() if t.strip()][:200]
        link = page.locator("a", has_text=re.compile(r"qwickly|attendance", re.I)).first
        if link.count() == 0:
            return info
        info["found"] = True
        info["link_text"] = link.inner_text().strip()
        link.click()
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(4)
        page.screenshot(path=str(shots_dir / "qwickly.png"), full_page=True)
        info["url"] = page.url
        texts = []
        for fr in page.frames:
            try:
                texts.append({"frame": fr.url, "text": fr.inner_text("body", timeout=4000)[:6000]})
            except Exception:
                pass
        info["frames"] = texts
    except Exception as e:
        info["error"] = str(e)
    return info


def run_collect(course, base_hint=None, out="out", profile="session", headless=False,
                browser_path=None, shots=True, login=None, channel=None, no_wait=False):
    m = re.match(r"(https?://[^/]+)/d2l/home/(\d+)", course)
    if m:
        base, org = m.group(1), m.group(2)
    elif course.isdigit() and base_hint:
        base, org = base_hint, course
    else:
        sys.exit("Give a full course URL like https://learn.jalc.edu/d2l/home/99316")
    outdir = Path(out) / org
    (outdir / "screenshots").mkdir(parents=True, exist_ok=True)
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
        data = collect(d2l, org)
        data["login_method"] = how
        data["whoami"] = logged_in(d2l)
        data["qwickly"] = qwickly(page, base, org, outdir / "screenshots")
        if shots:
            for label, path in SHOTS:
                try:
                    page.goto(base + path.format(org=org), wait_until="networkidle", timeout=30000)
                    page.screenshot(path=str(outdir / "screenshots" / f"{label}.png"), full_page=True)
                except Exception as e:  # screenshots are best-effort
                    data.setdefault("screenshot_errors", {})[label] = str(e)
        ctx.close()
    path = outdir / "course.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"Wrote {path}")
    if data["api_errors"]:
        print("Some API calls failed (see api_errors in course.json):", ", ".join(data["api_errors"]))
    return path, data, how


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
