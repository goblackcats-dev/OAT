"""Collect course data from D2L Brightspace into a JSON file for OAT scoring.

Run on YOUR computer. A browser window opens; log in yourself (including any MFA).
The script never sees or stores your password. It reuses the logged-in browser
session to call D2L's read-only API (GET requests only) and saves screenshots.

    python -m oat.collect https://learn.jalc.edu/d2l/home/105329
    python -m oat.collect 105329 --base https://learn.jalc.edu

Output (in ./out/<course id>/): course.json and screenshots/*.png
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

FETCH_JS = """async (url) => {
  try {
    const r = await fetch(url, {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
    const text = await r.text();
    let body = null;
    try { body = JSON.parse(text); } catch (e) { body = null; }
    return {status: r.status, body: body, text: body === null ? text.slice(0, 500) : null};
  } catch (e) { return {status: 0, body: null, text: String(e)}; }
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

    def load_versions(self):
        for p in self.get("/d2l/api/versions/", "versions") or []:
            self.versions[p["ProductCode"]] = p["LatestVersion"]

    def lp(self, rest):
        return f"/d2l/api/lp/{self.versions.get('lp', '1.50')}{rest}"

    def le(self, rest):
        return f"/d2l/api/le/{self.versions.get('le', '1.80')}{rest}"


def wait_for_login(d2l, minutes=10):
    print("Log in to D2L in the browser window. Waiting up to %d minutes..." % minutes)
    end = time.time() + minutes * 60
    while time.time() < end:
        res = d2l.page.evaluate(FETCH_JS, d2l.base + "/d2l/api/lp/1.0/users/whoami")
        if res["status"] == 200:
            print("Logged in as:", (res["body"] or {}).get("FirstName"), (res["body"] or {}).get("LastName"))
            return res["body"]
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

    m = re.match(r"(https?://[^/]+)/d2l/home/(\d+)", a.course)
    if m:
        base, org = m.group(1), m.group(2)
    elif a.course.isdigit() and a.base:
        base, org = a.base, a.course
    else:
        sys.exit("Give a full course URL like https://learn.jalc.edu/d2l/home/105329")

    out = Path(a.out) / org
    (out / "screenshots").mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(a.profile, headless=a.headless,
                                                   executable_path=a.browser_path,
                                                   viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{base}/d2l/home/{org}")
        d2l = D2L(page, base)
        if not a.no_wait:
            wait_for_login(d2l)
        data = collect(d2l, org)
        if not a.no_shots:
            for label, path in SHOTS:
                try:
                    page.goto(base + path.format(org=org), wait_until="networkidle", timeout=30000)
                    page.screenshot(path=str(out / "screenshots" / f"{label}.png"), full_page=True)
                except Exception as e:  # screenshots are best-effort
                    data.setdefault("screenshot_errors", {})[label] = str(e)
        ctx.close()
    (out / "course.json").write_text(json.dumps(data, indent=2, default=str))
    print(f"Wrote {out / 'course.json'}")
    if data["api_errors"]:
        print("Some API calls failed (see api_errors in course.json):", ", ".join(data["api_errors"]))


if __name__ == "__main__":
    main()
