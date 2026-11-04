#!/usr/bin/env python3
"""
Lucky Number Stats — reads the daily "szczęśliwy numerek" from eduVULCAN
(logging in with your login + password, like a browser) and builds a
statistics dashboard.

Commands
  python lucky.py daily [--show]     fetch today's number + rebuild dashboard (use in scheduler)
  python lucky.py fetch [--show]     fetch today's number only
  python lucky.py backfill --since YYYY-MM-DD   try to download past days
  python lucky.py add YYYY-MM-DD N   add/correct a number by hand
  python lucky.py report             rebuild dashboard.html

--show opens a visible browser window so you can watch the login (use it the first time).

If DASHBOARD_PASSWORD is set, a password-protected copy is also written to site/index.html
(this is what GitHub Pages publishes — see GITHUB_SETUP.md).
"""
import argparse
import asyncio
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "lucky_numbers.csv"      # date,number
ROSTER_FILE = HERE / "roster.csv"           # number,name
CONFIG_FILE = HERE / "config.json"          # {"login": "...", "password": "...", "student": "..."}
TEMPLATE_FILE = HERE / "dashboard_template.html"
OUTPUT_FILE = HERE / "dashboard.html"
DEBUG_DIR = HERE / "debug"
SITE_DIR = HERE / "site"                    # password-protected copy for GitHub Pages
LOCK_TEMPLATE_FILE = HERE / "locked_template.html"

IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"
LAST_FETCH_FAILED = False

LOGIN_URL = "https://eduvulcan.pl/logowanie"
ACCESS_URL = "https://eduvulcan.pl/dostep-do-dziennika/"


# ---------------------------------------------------------------- storage
def load_data() -> dict:
    if not DATA_FILE.exists():
        return {}
    with DATA_FILE.open(newline="", encoding="utf-8") as f:
        return {row["date"]: int(row["number"]) for row in csv.DictReader(f)}


def save_data(data: dict) -> None:
    with DATA_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "number"])
        for d in sorted(data):
            w.writerow([d, data[d]])


def load_roster() -> dict:
    if not ROSTER_FILE.exists():
        return {}
    roster = {}
    with ROSTER_FILE.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            num = (row.get("number") or "").strip()
            name = (row.get("name") or "").strip()
            if num.isdigit() and name:
                roster[int(num)] = name
    return roster


def load_config() -> dict:
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    # environment variables win, so you don't have to keep the password in a file
    cfg["login"] = os.environ.get("EDUVULCAN_LOGIN") or cfg.get("login")
    cfg["password"] = os.environ.get("EDUVULCAN_PASSWORD") or cfg.get("password")
    cfg["student"] = os.environ.get("EDUVULCAN_STUDENT") or cfg.get("student")
    return cfg


# ---------------------------------------------------------------- number extraction
NUMBER_KEY = re.compile(r"(?i)(numer|number|lucky)")
NUMBER_TEXT = re.compile(r"(?i)szcz[eę][sś]liwy\s+numer(?:ek)?\D{0,60}?(\d{1,2})\b")


def number_from_json(data):
    """Find the lucky number in an API response of unknown shape."""
    if isinstance(data, bool):
        return None
    if isinstance(data, int):
        return data or None
    if isinstance(data, str) and data.strip().isdigit():
        return int(data) or None
    if isinstance(data, dict):
        for k, v in data.items():                       # keys like "numer", "szczesliwyNumer"
            if NUMBER_KEY.search(k):
                n = number_from_json(v)
                if n:
                    return n
        for v in data.values():
            if isinstance(v, (dict, list)):
                n = number_from_json(v)
                if n:
                    return n
    if isinstance(data, list):
        for v in data:
            n = number_from_json(v)
            if n:
                return n
    return None


LUCKY_KEY = re.compile(r"(?i)szcz[eę]?[sś]liw|lucky")


def lucky_part(data):
    """Return the piece of a JSON response stored under a 'szczęśliwy…'/'lucky…' key, if any."""
    if isinstance(data, dict):
        for k, v in data.items():
            if LUCKY_KEY.search(k):
                return v
        for v in data.values():
            r = lucky_part(v)
            if r is not None:
                return r
    elif isinstance(data, list):
        for v in data:
            r = lucky_part(v)
            if r is not None:
                return r
    return None


def number_from_text(text: str):
    m = NUMBER_TEXT.search(text)
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


# ---------------------------------------------------------------- browser
PRIVACY_TEXT = re.compile(r"Szanujemy Twoją prywatność", re.I)
# The browser profile is thrown away after every run, so accepting stores nothing on your
# computer. eduVULCAN won't let you continue to the register if the box is only closed.
PRIVACY_BUTTONS = [r"^\s*Zgadzam się", r"^\s*Akceptuj", r"^\s*Zamknij"]


async def dismiss_privacy(page) -> bool:
    """Answer VULCAN's 'Szanujemy Twoją prywatność' pop-up if it is showing (also inside iframes)."""
    async def attempt():
        for frame in page.frames:
            try:
                if not await frame.get_by_text(PRIVACY_TEXT).first.is_visible():
                    continue
            except Exception:
                continue
            for pattern in PRIVACY_BUTTONS:
                btn = frame.get_by_role("button", name=re.compile(pattern, re.I))
                try:
                    if await btn.count() and await btn.first.is_visible():
                        await btn.first.click(timeout=3000)
                        step("closed the privacy pop-up")
                        await page.wait_for_timeout(1500)
                        return True
                except Exception:
                    pass
        return False
    try:
        return await asyncio.wait_for(attempt(), timeout=15)
    except Exception:
        return False


async def settle(page, timeout=20000) -> None:
    """Wait until the page stops loading, but never get stuck on it."""
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass


def step(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def public(url: str) -> str:
    """GitHub Actions logs can be public, so there we only show the website, not the full address."""
    url = url.split("?")[0]
    if IN_CI:
        m = re.match(r"https?://[^/]+", url)
        return (m.group(0) + "/…") if m else "…"
    return url


async def _click_if_present(page, selectors, timeout=1500):
    for sel in selectors:
        try:
            await page.locator(sel).first.click(timeout=timeout)
            return True
        except Exception:
            pass
    return False


async def fetch_today(show: bool = False, after_panel=None):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        sys.exit("Playwright is missing. Run:\n  pip install -r requirements.txt\n  python -m playwright install chromium")

    cfg = load_config()
    if not (cfg.get("login") and cfg.get("password")):
        sys.exit("No login/password. Put them in config.json or set EDUVULCAN_LOGIN / EDUVULCAN_PASSWORD.")

    found = {}
    api_paths = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not show, slow_mo=150 if show else 0)
        ctx = await browser.new_context(locale="pl-PL")
        page = await ctx.new_page()

        async def on_response(resp):
            url = resp.url
            if "vulcan" not in url:
                return
            kind = resp.request.resource_type
            if kind not in ("document", "xhr", "fetch"):
                return
            path = url.split("?")[0]
            api_paths.append(f"{kind:8} {resp.status} {path}")
            if kind == "document" or "api" in found:
                return
            try:
                data = await resp.json()
            except Exception:
                return
            # either the address mentions the lucky number, or the JSON has a key that does
            if re.search(r"(?i)szcz|lucky|numer", path):
                n = number_from_json(data)
            else:
                n = number_from_json(lucky_part(data))
            if n:
                found["api"], found["source"] = n, path
                found["url"], found["req"] = url, resp.request

        ctx.on("response", on_response)         # context-wide, so new tabs are covered too

        try:
            # 1. log in
            step("opening the login page")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            await dismiss_privacy(page)
            user = page.locator('input[name="Alias"], input[name="UserName"], input#Alias, '
                                'input[type="email"], input[autocomplete="username"]').first
            await user.fill(cfg["login"], timeout=20000)
            pwd = page.locator('input[type="password"]').first
            if not await pwd.is_visible():          # login is a two-step form: login → Dalej → password
                await user.press("Enter")
                await pwd.wait_for(state="visible", timeout=20000)
            await pwd.fill(cfg["password"])
            await pwd.press("Enter")
            step("login sent, waiting…")
            try:
                await page.wait_for_function("() => !location.pathname.toLowerCase().includes('logowanie')",
                                             timeout=60000)
            except Exception:
                raise RuntimeError("Login didn't go through: still on the login page after 60 s. "
                                   "Either the login/password is wrong, or eduVULCAN asked for an extra "
                                   "check (e.g. a captcha) — see debug/error.png.") from None
            await settle(page)
            step(f"logged in, now on {public(page.url)}")
            for _ in range(3):                      # the pop-up can appear a moment later
                if await dismiss_privacy(page):
                    await settle(page)
                    break
                await page.wait_for_timeout(1000)

            # 2. open the register: "Dostęp do Dziennika" → pick the student
            if cfg.get("panel_url"):
                await page.goto(cfg["panel_url"], wait_until="domcontentloaded")
            else:
                for attempt in range(2):
                    step("opening 'Dostęp do Dziennika'")
                    await page.goto(ACCESS_URL, wait_until="domcontentloaded")
                    await settle(page)
                    await page.wait_for_timeout(2000)   # the list is built with JavaScript
                    await dismiss_privacy(page)
                    if "dostep-do-dziennika" in page.url:
                        break
                    step(f"ended up on {public(page.url)}, trying again")
                DEBUG_DIR.mkdir(exist_ok=True)
                await page.screenshot(path=str(DEBUG_DIR / "access_page.png"), full_page=True)
                hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href.split('?')[0])")
                (DEBUG_DIR / "access_links.txt").write_text("\n".join(dict.fromkeys(hrefs)), encoding="utf-8")

                # the register lives on another host (uczen.eduvulcan.pl / *.vulcan.net.pl)
                target = page.locator('a[href*="uczen.eduvulcan.pl"], a[href*="vulcan.net.pl"], '
                                      'a[href*="dziennik-uczen"]')
                if cfg.get("student"):          # a name given in config wins
                    named = target.filter(has_text=re.compile(re.escape(cfg["student"]), re.I))
                    if not await named.count():
                        named = page.get_by_text(re.compile(re.escape(cfg["student"]), re.I))
                    target = named
                if not await target.count() and not cfg.get("student"):
                    target = page.locator('main a[href*="dziennik"]:not([href*="dostep-do-dziennika"]), '
                                          'a[href*="/api/ap"]')
                if not await target.count():
                    raise RuntimeError("Couldn't find your name on the 'Dostęp do Dziennika' page. "
                                       "Put your name in \"student\" in config.json.")
                name = (await target.first.inner_text()).strip().splitlines()[0][:60]
                print("Opening:", "your register" if IN_CI else name)
                before = len(ctx.pages)
                await target.first.click()
                await page.wait_for_timeout(3000)
                if len(ctx.pages) > before:         # opened in a new tab → follow it
                    page = ctx.pages[-1]
                await page.wait_for_load_state("domcontentloaded")

            step("waiting for the register to load")
            await settle(page, 45000)
            await page.wait_for_timeout(2000)
            await dismiss_privacy(page)
            await page.wait_for_timeout(3000)       # let the dashboard tiles finish loading
            print("Ended on page:", public(page.url))
            DEBUG_DIR.mkdir(exist_ok=True)
            await page.screenshot(path=str(DEBUG_DIR / "last_page.png"), full_page=True)

            if after_panel:                     # e.g. the backfill probe
                await after_panel(ctx, found)

            # 3. fallback: read it off the page text
            if "api" not in found:
                n = number_from_text(await page.inner_text("body"))
                if n:
                    found["api"], found["source"] = n, "page text"
            if show:
                print("Browser stays open for 10 s so you can look…")
                await page.wait_for_timeout(10000)
        except Exception as e:
            DEBUG_DIR.mkdir(exist_ok=True)
            await page.screenshot(path=str(DEBUG_DIR / "error.png"), full_page=True)
            msg = str(e).strip().splitlines()[0] if IN_CI else str(e)
            found["error"] = f"{type(e).__name__}: {msg}"
        finally:
            DEBUG_DIR.mkdir(exist_ok=True)
            (DEBUG_DIR / "api_calls.txt").write_text("\n".join(dict.fromkeys(api_paths)), encoding="utf-8")
            await browser.close()

    global LAST_FETCH_FAILED
    LAST_FETCH_FAILED = "error" in found
    if "error" in found:
        print("Login/fetch failed:", found["error"])
        print(f"Screenshot saved to {DEBUG_DIR / 'error.png'}. Try again with --show to watch what happens.")
        return None
    if "api" not in found:
        print("Logged in, but couldn't find a lucky number.")
        print(f"Look at {DEBUG_DIR / 'last_page.png'} — is it the student panel, and does it show the number?")
        print(f"Then send me the list in {DEBUG_DIR / 'api_calls.txt'} (addresses only, no grades).")
        return None
    src = found["source"] if found["source"] == "page text" else public(found["source"])
    print(f"Today's lucky number: {found['api']}  (from {src})")
    return found["api"]


# ---------------------------------------------------------------- backfill
DATE_PARAMS = [("data", "{d}"), ("dzien", "{d}"), ("data", "{d}T00:00:00"), ("dataOd", "{d}"),
               ("day", "{d}"), ("date", "{d}"), ("dataOd", "{d}T00:00:00.000Z")]


def previous_school_days(before: date, n: int) -> list:
    out, d = [], before
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def make_backfill(since: date, until: date, results: dict, report: list):
    async def run(ctx, found):
        if "url" not in found:
            report.append("The number wasn't loaded from the panel's data, so there's nothing to try dates on.")
            return
        skip = ("cookie", "host", "content-length", "user-agent", "accept-encoding", "referer",
                "connection", "origin")
        headers = {k: v for k, v in (await found["req"].all_headers()).items()
                   if not k.startswith((":", "sec-")) and k.lower() not in skip}
        base = found["url"]
        sep = "&" if "?" in base else "?"
        page = ctx.pages[-1]

        async def get(url):        # ask from inside the panel page, exactly like the panel does
            status, body = await page.evaluate(
                """async ([u, h]) => {
                     const r = await fetch(u, {headers: h, credentials: 'include'});
                     const t = await r.text();
                     try { return [r.status, JSON.parse(t)]; } catch (e) { return [r.status, t.slice(0, 120)]; }
                   }""", [url, headers])
            return status, body

        _, today_json = await get(base)
        if IN_CI:
            report.append(f"today (no date): number {number_from_json(today_json)}")
        else:
            report.append(f"today (no date): {json.dumps(today_json, ensure_ascii=False)[:200]}")
        d1, d2, d3 = previous_school_days(date.today(), 3)

        working = None
        for name, fmt in DATE_PARAMS:
            answers = {}
            for d in (d1, d2, d3):
                status, js = await get(f"{base}{sep}{name}={fmt.format(d=d.isoformat())}")
                answers[d] = (status, js)
                await asyncio.sleep(0.3)
            nums = [number_from_json(js) if st == 200 else None for st, js in answers.values()]
            echoes = any(d.isoformat() in json.dumps(js) for d, (st, js) in answers.items()
                         if st == 200 and json.dumps(js) != json.dumps(today_json))
            differs = any(js != today_json for st, js in answers.values() if st == 200)
            report.append(f"{name}={fmt}: numbers {nums}  {'(answer changes with the date)' if differs else '(same as today)'}")
            if differs and (echoes or len(set(nums)) > 1):
                working = (name, fmt)
                break

        if not working:
            report.append("NO WORKING DATE PARAMETER: this address only gives today's number.")
            return
        name, fmt = working
        report.append(f"Dates work with '{name}' — downloading…")
        d = since
        while d <= until:
            if d.weekday() < 5:
                status, js = await get(f"{base}{sep}{name}={fmt.format(d=d.isoformat())}")
                n = number_from_json(js) if status == 200 else None
                if n:
                    results[d.isoformat()] = n
                print(f"  {d}: {n or '-'}")
                await asyncio.sleep(0.4)        # be gentle with the server
            d += timedelta(days=1)
    return run


# ---------------------------------------------------------------- report
def build_report() -> None:
    data = load_data()
    roster = load_roster()
    counts = Counter(data.values())

    numbers = set(roster) | set(counts)
    if not roster and counts:
        numbers |= set(range(1, max(counts) + 1))

    people = [{
        "number": n,
        "name": roster.get(n, f"No. {n}"),
        "inRoster": n in roster,
        "count": counts.get(n, 0),
        "dates": sorted(d for d, v in data.items() if v == n),
    } for n in sorted(numbers)]

    payload = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "draws": [{"date": d, "number": data[d]} for d in sorted(data)],
        "people": people,
        "hasRoster": bool(roster),
    }
    html = TEMPLATE_FILE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Dashboard written to {OUTPUT_FILE}  ({len(data)} draws)")

    password = os.environ.get("DASHBOARD_PASSWORD")
    if password:
        write_locked_site(html, password)


# ---------------------------------------------------------------- password-protected site
PBKDF2_ITERATIONS = 310_000


def write_locked_site(html: str, password: str) -> None:
    """Encrypt the dashboard (AES-256-GCM, key from the password via PBKDF2-SHA256) into
    site/index.html. The page asks for the password and decrypts in the browser, so the
    class list never appears in readable form on the public website."""
    import base64
    import hashlib
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        sys.exit("The 'cryptography' package is missing. Run:  pip install -r requirements.txt")

    # a fixed salt per repository, so "remember me" keeps working after each daily update
    salt = hashlib.sha256(("lucky-stats|" + os.environ.get("GITHUB_REPOSITORY", "local")).encode()).digest()[:16]
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=PBKDF2_ITERATIONS).derive(password.encode("utf-8"))
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, html.encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    blob = {"salt": b64(salt), "iv": b64(iv), "ct": b64(ct), "iter": PBKDF2_ITERATIONS}

    SITE_DIR.mkdir(exist_ok=True)
    page = LOCK_TEMPLATE_FILE.read_text(encoding="utf-8").replace("/*__BLOB__*/null", json.dumps(blob))
    (SITE_DIR / "index.html").write_text(page, encoding="utf-8")
    (SITE_DIR / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    print(f"Password-protected copy written to {SITE_DIR / 'index.html'}")


# ---------------------------------------------------------------- cli
def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "daily"):
        sp = sub.add_parser(name)
        sp.add_argument("--show", action="store_true", help="show the browser window")
        sp.add_argument("--skip-if-done", action="store_true",
                        help="don't log in if today's number is already saved")
    b = sub.add_parser("backfill", help="try to download past days")
    b.add_argument("--since", type=parse_date, required=True)
    b.add_argument("--show", action="store_true")
    a = sub.add_parser("add"); a.add_argument("date", type=parse_date); a.add_argument("number", type=int)
    sub.add_parser("report")
    args = p.parse_args()

    if IN_CI and not os.environ.get("DASHBOARD_PASSWORD"):
        sys.exit("The DASHBOARD_PASSWORD secret is missing — add it in Settings → Secrets and variables → Actions.")

    if args.cmd in ("fetch", "daily"):
        today = date.today().isoformat()
        if args.skip_if_done and today in load_data():
            print(f"Already have today's number ({load_data()[today]}), not logging in again.")
            n = True
        else:
            n = asyncio.run(fetch_today(show=args.show))
            if n:
                data = load_data()
                data[today] = n
                save_data(data)
        if args.cmd == "daily":
            build_report()
        if n is None and LAST_FETCH_FAILED:
            sys.exit(1)   # a real error (login, page changed) → GitHub marks the run as failed
    elif args.cmd == "backfill":
        results, report = {}, []
        until = date.today() - timedelta(days=1)
        n = asyncio.run(fetch_today(show=args.show, after_panel=make_backfill(args.since, until, results, report)))
        print("\n".join(["", "Date test:"] + ["  " + r for r in report]))
        data = load_data()
        if n:
            data[date.today().isoformat()] = n
        added = {d: v for d, v in results.items() if d not in data}
        data.update(results)
        save_data(data)
        print(f"\nSaved {len(results)} past days ({len(added)} new).")
        build_report()
    elif args.cmd == "add":
        data = load_data()
        data[args.date.isoformat()] = args.number
        save_data(data)
        print(f"Saved {args.date}: {args.number}")
        build_report()
    elif args.cmd == "report":
        build_report()


if __name__ == "__main__":
    main()
