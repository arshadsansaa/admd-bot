"""
chart_download.py - bulk-download patient chart PDFs from AdvancedMD EHR.

Flow per chart number: Patients search (exact match, else SKIPPED) -> open chart
-> verify banner -> "..." menu -> Chart Print (defaults untouched) -> Print ->
Report Viewer window -> save PDF -> verify -> close Report Viewer -> close the
patient tab.  --until search / open stop earlier (for testing).

Built for long runs: it re-logs-in (new Chrome) when the session expires or Chrome
dies and carries on with the current chart (max 3 re-logins in a row, then stops);
shows "[acpc] [23/500] 1667 DOWNLOADED 28s (avg 31s/chart), ETA 3h 50m" per chart;
keeps logs/<client>/failed_or_skipped.txt (re-run it with --charts-file); --limit N does N charts
per run (already-downloaded charts do not count); --headless runs without a window
and is the RECOMMENDED mode for bulk runs (no window to flicker or be clicked into).

Standalone (not wired into Celery). Chrome runs NON-headless.

Usage (from project root):
    .\\venv\\Scripts\\python.exe -m accounts.chart_download --client acpc --charts 1667 --until pdf
    .\\venv\\Scripts\\python.exe -m accounts.chart_download --client pure --charts-file pure.xlsx --headless

Multi-client: --client NAME (letters/digits/underscore) is required. Everything is
kept per client (chart numbers repeat across clients):
    downloads/<client>/charts/            verified PDFs (EXISTS/resume looks only here)
    downloads/<client>/tmp/run_<pid>/     Chrome download folder for this run
    logs/<client>/                        log CSV, failed_or_skipped.txt, screenshots, run.lock
Credentials from .env: AMD_<CLIENT>_USERNAME, AMD_<CLIENT>_PASSWORD,
AMD_<CLIENT>_OFFICE_KEY (client name upper-cased). Optional AMD_<CLIENT>_PDF_MARKER:
text that page 1 of every NEW PDF must contain (e.g. the practice's city line).
One run per client at a time (logs/<client>/run.lock); different clients can run
in parallel - each gets its own Chrome profile and download folder.
Practice check: the EHR window title must show this client's office key
("AdvancedMD - EHR | <office key>"), checked after login and before every chart.

Input: .txt (one chart number per line) or .xlsx (a "chart_number" column, or
the first column).

PHI: console output is limited to chart number + status. Screenshots and the log
CSV go to logs/<client>/, PDFs to downloads/<client>/charts/ - both gitignored.
"""
import argparse
import atexit
import contextlib
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv
from selenium.common.exceptions import (
    StaleElementReferenceException, TimeoutException, WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from accounts.amd_common import setup_driver, perform_login

ROOT = Path(__file__).resolve().parent.parent
LOG_HEADER = ["chart_number", "status", "file_path", "error", "timestamp", "seconds"]
# Per-client paths: all None until configure_client() runs (nothing may write
# to a shared, client-less folder).
CLIENT = None
LOG_DIR = CHART_DIR = LOG_CSV = TMP_ROOT = TMP_DIR = FAILED_LIST = LOCK_FILE = None
CHROME_PROFILE_DIR = None
PDF_MARKER = None                    # optional per-client text required on PDF page 1
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# --- Selectors (from html_samples/ captures) --------------------------------
# PM window (top document)
SEL_EHR_BUTTON = "amds-pm-ehr-redirect .ehr-redirect-button"
# EHR window (top document)
SEL_SEARCH_BUTTON = "button.amds-ps-search-button"          # labelled "Patients"
SEL_SEARCH_INPUT = 'input.amds-ps-input[name="query"]'
SEL_SEARCH_STATUS = ".amds-ps-results .amds-ps-status"      # "Displaying N of M"
SEL_RESULT_CARD = "amds-patient-card"
SEL_CARD_CODES = ".amds-ps-codes"                           # "1687- TRENT"
SEL_CARD_CODE = ".amds-ps-codes > span:first-child"          # "1687"
SEL_CARD_NAME = ".amds-ps-name"                              # "LAST, FIRST M"
SEL_CARD_CLICK = ".amds-patient-card-ui"
SEL_PLANS_DIALOG = "div.ui-dialog"                           # jQuery UI dialog
SEL_PLANS_IFRAME = 'iframe[src*="healthwatcher/plans.aspx"]'
SEL_DIALOG_CLOSE = "a.ui-dialog-titlebar-close"
SEL_CHART_IFRAME = 'iframe[src*="amds-patient-chart"]'
SEL_PATIENT_TABS = (                                         # never Dashboard
    "ul.amds-tab-list li.amds-tab:not(.amds-tab-permanent)"
    ":not(.amds-tab-permanent-active)"
)
PROTECTED_TAB_TITLES = {"patients", "dashboard"}
# Patient chart iframe
SEL_BANNER_NUMBERS = ".amds-internal-numbers > span"         # [patientId, chart#]
SEL_BANNER_NAME = ".amds-patient-name"                       # top-left name bar

# Stage 2 selectors (patient-chart iframe -> ChartPrint iframe -> Report Viewer window)
SEL_TOOLS_TOGGLE = "li.amds-tools-toggle"                    # the "..." button
SEL_TOOLS_LIST = "ol.amds-collapsed-tools"                   # gets .amds-tools-active when open
SEL_CHART_PRINT_ICON = (
    'ol.amds-collapsed-tools li[title="Open Chart Print"], '
    "ol.amds-collapsed-tools li.amds-svg-print-2d"
)
SEL_CHARTPRINT_IFRAME = 'iframe[src*="ChartPrint.aspx"]'
SEL_BTN_PRINT = "#btnPrint"
SEL_CHK_CONFID = "#chkConfid"                                # must stay unchecked
SEL_CHK_DOCOPEN = "#chkDocOpen"                              # must stay unchecked
SEL_REPORT_FRAME = "iframe#frameReportViewer"                # holds the real PDF URL

RESULT_STATUS_RE = re.compile(r"Displaying\s+(\d+)\s+of\s+(\d+)", re.I)
CODE_RE = re.compile(r"^\s*([^\s-]+)\s*-")                    # "1687- TRENT" -> "1687"
PLANS_TITLE = "HealthWatcher Plan Manager"


class Skip(Exception):
    """Patient deliberately skipped (zero / multiple / ambiguous matches)."""


class PracticeMismatch(Exception):
    """The browser session is not (provably) logged into this client's practice."""


class CredentialsError(Exception):
    pass


class LockError(Exception):
    pass


# --- Client configuration ----------------------------------------------------

CLIENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10))}


def configure_client(name, pid=None):
    """Point every output path at this client's folders. Folder names are
    lower-cased (Windows paths are case-insensitive anyway); the .env variable
    names use the upper-cased client name."""
    global CLIENT, LOG_DIR, CHART_DIR, LOG_CSV, TMP_ROOT, TMP_DIR, FAILED_LIST, LOCK_FILE
    global CHROME_PROFILE_DIR
    if not name or not CLIENT_RE.match(name):
        raise ValueError("client name must be letters, digits or underscore only")
    if name.lower() in WINDOWS_RESERVED:
        raise ValueError(f"'{name}' is a reserved Windows name; pick another client name")
    pid = pid or os.getpid()
    CLIENT = name.lower()
    CHART_DIR = ROOT / "downloads" / CLIENT / "charts"
    TMP_ROOT = ROOT / "downloads" / CLIENT / "tmp"
    TMP_DIR = TMP_ROOT / f"run_{pid}"           # Chrome downloads land here until verified
    LOG_DIR = ROOT / "logs" / CLIENT
    LOG_CSV = LOG_DIR / "chart_download_log.csv"
    FAILED_LIST = LOG_DIR / "failed_or_skipped.txt"
    LOCK_FILE = LOG_DIR / "run.lock"
    CHROME_PROFILE_DIR = Path(tempfile.gettempdir()) / f"amd_chart_{CLIENT}_{pid}"
    return CLIENT


def env_prefix(client):
    return f"AMD_{client.upper()}_"


def load_credentials(client, env=None):
    """(username, password, office_key) from AMD_<CLIENT>_* - never the generic
    AMD_* ones. The error names missing VARIABLES only, never any value."""
    env = os.environ if env is None else env
    p = env_prefix(client)
    keys = [p + "USERNAME", p + "PASSWORD", p + "OFFICE_KEY"]
    vals = [(env.get(k) or "").strip() for k in keys]
    missing = [k for k, v in zip(keys, vals) if not v]
    if missing:
        raise CredentialsError(f"missing in .env for client '{client}': {', '.join(missing)}")
    return tuple(vals)


# --- Run lock (one run per client) --------------------------------------------

def _windows_process(pid):
    """(alive, image path or '') for a PID on Windows, via kernel32 (no psutil)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.get_last_error() == 5, ""  # access denied => it exists
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
            return False, ""
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        image = buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else ""
        return True, image
    finally:
        k32.CloseHandle(h)


def pid_running(pid):
    """True if `pid` is a live process that could be one of our runs. A live PID
    whose program is clearly not Python (Windows recycles PIDs) counts as dead."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        alive, image = _windows_process(pid)
        if alive and image and "python" not in Path(image).name.lower():
            return False
        return alive
    try:
        os.kill(pid, 0)   # (never on Windows: there os.kill terminates the process)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock():
    try:
        text = LOCK_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    info = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    try:
        info["pid"] = int(info.get("pid", ""))
    except ValueError:
        info.pop("pid", None)
    return info


def acquire_lock():
    """Create logs/<client>/run.lock atomically. Refuse if another live run holds
    it; replace it if its PID is no longer running (crash / closed window)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            info = read_lock()
            pid = info.get("pid")
            if pid is None:
                try:  # being written by a run that is starting right now?
                    if time.time() - LOCK_FILE.stat().st_mtime < 10:
                        raise LockError(f"another run for client '{CLIENT}' is starting ({LOCK_FILE})")
                except FileNotFoundError:
                    continue
            elif pid != os.getpid() and pid_running(pid):
                raise LockError(
                    f"another run for client '{CLIENT}' is already running "
                    f"(PID {pid}, started {info.get('started', '?')}). "
                    f"If you are sure it is not, delete {LOCK_FILE}")
            say(f"Removing stale lock (PID {pid if pid is not None else '?'} is not running).")
            with contextlib.suppress(FileNotFoundError):
                LOCK_FILE.unlink()
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()}\nstarted={datetime.now().isoformat(timespec='seconds')}\n")
        return
    raise LockError(f"could not create {LOCK_FILE}")


def release_lock():
    """Remove the lock - only if it is ours."""
    if LOCK_FILE is not None and read_lock().get("pid") == os.getpid():
        with contextlib.suppress(OSError):
            LOCK_FILE.unlink()


def rmtree_quiet(path, tries=5):
    """Delete a folder; Chrome may hold files for a moment after quitting."""
    for i in range(tries):
        if not Path(path).exists():
            return True
        shutil.rmtree(path, ignore_errors=True)
        if not Path(path).exists():
            return True
        time.sleep(0.5 * (i + 1))
    return False


def remove_stale_run_dirs():
    """Leftovers of crashed runs of THIS client (call only while holding its lock):
    downloads/<client>/tmp/run_<pid> and %TEMP%/amd_chart_<client>_<pid>."""
    candidates = []
    if TMP_ROOT.exists():
        candidates += [(d, re.fullmatch(r"run_(\d+)", d.name)) for d in TMP_ROOT.iterdir()]
    prof_re = re.compile(r"amd_chart_" + re.escape(CLIENT) + r"_(\d+)")
    with contextlib.suppress(OSError):
        candidates += [(d, prof_re.fullmatch(d.name)) for d in CHROME_PROFILE_DIR.parent.iterdir()]
    for d, m in candidates:
        if m and d.is_dir() and int(m.group(1)) != os.getpid() and not pid_running(m.group(1)):
            rmtree_quiet(d, tries=1)


def cleanup_run():
    """Exit cleanup (normal end, Ctrl+C, atexit): this run's temp folders + lock."""
    if CLIENT is None:
        return
    rmtree_quiet(TMP_DIR)
    rmtree_quiet(CHROME_PROFILE_DIR)
    with contextlib.suppress(OSError):
        if TMP_ROOT.exists() and not any(TMP_ROOT.iterdir()):
            TMP_ROOT.rmdir()
    release_lock()


# --- Practice check -----------------------------------------------------------

EHR_TITLE_RE = re.compile(r"^AdvancedMD - EHR\s*\|\s*(\S+)")


def check_practice(title, office_key):
    """The EHR window title reads 'AdvancedMD - EHR | <office key>'. Raise
    PracticeMismatch unless it shows exactly this client's office key.
    Messages never contain either key."""
    m = EHR_TITLE_RE.match((title or "").strip())
    if not m:
        raise PracticeMismatch("cannot confirm the practice: EHR window title is not "
                               "'AdvancedMD - EHR | <office key>'")
    if m.group(1).strip() != str(office_key or "").strip():
        raise PracticeMismatch(f"EHR is logged into a different office key than "
                               f"{env_prefix(CLIENT or 'client')}OFFICE_KEY")


def verify_practice(driver):
    """Check the CURRENT window (must be the EHR) against the expected office key."""
    expected = getattr(driver, "_expected_office", None)
    if not expected:
        raise PracticeMismatch("no expected office key set for this browser")
    check_practice(driver.title, expected)


# --- Small utilities ---------------------------------------------------------

def say(msg):
    prefix = f"[{CLIENT}] " if CLIENT else ""
    for line in str(msg).split("\n"):
        print(prefix + line, flush=True)


POLL = 0.4  # seconds between polls (fewer round-trips, calmer UI)


def wait_until(fn, timeout, poll=POLL, desc="condition"):
    """Poll fn() until it returns truthy. WebDriver errors count as 'not yet'."""
    end = time.time() + timeout
    last_exc = None
    while time.time() < end:
        try:
            val = fn()
            if val:
                return val
        except (WebDriverException, StaleElementReferenceException) as e:
            last_exc = e
        time.sleep(poll)
    raise TimeoutException(f"Timed out after {timeout}s waiting for {desc}"
                           + (f" (last error: {type(last_exc).__name__})" if last_exc else ""))


def visible(driver, css, root=None):
    root = root or driver
    out = []
    for el in root.find_elements(By.CSS_SELECTOR, css):
        try:
            if el.is_displayed():
                out.append(el)
        except StaleElementReferenceException:
            pass
    return out


JS_IN_VIEW = """
var e = arguments[0], r = e.getBoundingClientRect();
if (!(r.width > 0 && r.height > 0)) return false;
var x = r.left + r.width / 2, y = r.top + r.height / 2;
var w = window.innerWidth || document.documentElement.clientWidth;
var h = window.innerHeight || document.documentElement.clientHeight;
if (x < 0 || y < 0 || x >= w || y >= h) return false;
var t = document.elementFromPoint(x, y);
return !!t && (t === e || e.contains(t));
"""


def click(driver, el):
    """Click without making the page jump. A native click is used only when the
    element is already in view and nothing covers it (otherwise Selenium would
    scroll it into view first); every other case gets a JS click, which never
    scrolls. A failed native click also falls back to JS."""
    try:
        in_view = bool(driver.execute_script(JS_IN_VIEW, el))
    except WebDriverException:
        in_view = False
    if in_view:
        try:
            el.click()
            return
        except WebDriverException:
            pass
    driver.execute_script("arguments[0].click();", el)


def short_error(exc):
    """One-line error without Selenium stacktraces (which can be long/noisy)."""
    text = str(exc).split("Stacktrace:")[0].strip().replace("\n", " ")
    return f"{type(exc).__name__}: {text[:300]}"


# --- Frame / window helpers -------------------------------------------------

def find_in_frames(driver, by, sel, max_depth=4, _depth=0):
    """Search the current context and all nested iframes for a visible element.
    On success the driver is LEFT INSIDE the frame that holds it."""
    for el in driver.find_elements(by, sel):
        try:
            if el.is_displayed():
                return el
        except StaleElementReferenceException:
            pass
    if _depth >= max_depth:
        return None
    count = len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
    for i in range(count):
        try:
            frame = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")[i]
            driver.switch_to.frame(frame)
        except (WebDriverException, IndexError):
            continue
        found = find_in_frames(driver, by, sel, max_depth, _depth + 1)
        if found is not None:
            return found
        driver.switch_to.parent_frame()
    return None


def wait_in_frames(driver, by, sel, timeout, desc):
    def probe():
        driver.switch_to.default_content()
        return find_in_frames(driver, by, sel)
    return wait_until(probe, timeout, desc=desc)


def page_targets(driver):
    """{window handle: (title, url)} for every window, read through Chrome DevTools
    WITHOUT switching windows (each switch brings a window to the front, which
    is what made the visible browser flicker). None if unavailable."""
    try:
        infos = driver.execute_cdp_cmd("Target.getTargets", {})["targetInfos"]
    except Exception:
        return None
    return {t["targetId"]: (t.get("title") or "", t.get("url") or "")
            for t in infos if t.get("type") == "page"}


def switch_to_window(driver, predicate, timeout, desc):
    """Switch to the first window whose (title, url) satisfies predicate.
    Looks windows up via DevTools and switches at most once; only falls back to
    visiting each window if DevTools is unavailable."""
    def probe():
        handles = list(driver.window_handles)
        targets = page_targets(driver)
        if targets is not None and set(handles) <= set(targets):
            for h in handles:
                if predicate(*targets[h]):
                    try:
                        current = driver.current_window_handle
                    except WebDriverException:
                        current = None
                    if current != h:
                        driver.switch_to.window(h)
                    driver.switch_to.default_content()
                    return h
            return None
        for h in handles:  # fallback: inspect each window by visiting it
            driver.switch_to.window(h)
            if predicate(driver.title or "", driver.current_url or ""):
                driver.switch_to.default_content()
                return h
        return None
    return wait_until(probe, timeout, poll=0.5, desc=desc)


def is_pm(title, url):
    return title.startswith("AdvancedMD PM") or "/amds/pm/app/" in url


def is_ehr(title, url):
    return title.startswith("AdvancedMD - EHR") or "/WebClinical/TopPage.aspx" in url


def to_ehr(driver, timeout=10):
    """Make the EHR window current (top document). Remembers the EHR handle, so the
    usual case - already on it - costs no window switch at all."""
    cached = getattr(driver, "_ehr_handle", None)
    if cached:
        try:
            try:
                current = driver.current_window_handle
            except WebDriverException:
                current = None  # e.g. the Report Viewer we were on was just closed
            if current == cached:
                driver.switch_to.default_content()
                return cached
            if cached in driver.window_handles:
                driver.switch_to.window(cached)
                if is_ehr(driver.title or "", driver.current_url or ""):
                    driver.switch_to.default_content()
                    return cached
        except WebDriverException:
            pass
    handle = switch_to_window(driver, is_ehr, timeout, "EHR window")
    try:
        driver._ehr_handle = handle
    except Exception:
        pass
    return handle


# --- Input / log -------------------------------------------------------------

def _norm_chart(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def read_chart_numbers(path):
    path = Path(path)
    values = []
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        ws = load_workbook(path, read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        header = [_norm_chart(c).lower() for c in rows[0]]
        if "chart_number" in header:
            col, data = header.index("chart_number"), rows[1:]
        else:
            col, data = 0, rows
        values = [_norm_chart(r[col]) for r in data if r and col < len(r)]
    else:
        values = [_norm_chart(line) for line in path.read_text(encoding="utf-8-sig").splitlines()]
        if values and values[0].lower() == "chart_number":
            values = values[1:]
    seen, out = set(), []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def log_row(chart, status, file_path="", error="", seconds=""):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if LOG_CSV.exists():  # an older log with a different layout is archived, not mixed
        with open(LOG_CSV, encoding="utf-8", newline="") as f:
            first = f.readline().strip()
        if first != ",".join(LOG_HEADER):
            LOG_CSV.rename(LOG_DIR / f"chart_download_log_{datetime.now():%Y%m%d_%H%M%S}.csv")
    new = not LOG_CSV.exists()
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow([chart, status, file_path, error,
                    datetime.now().isoformat(timespec="seconds"), seconds])


def screenshot(driver, chart):
    """On failure: logs/<chart>.png plus logs/<chart>_ehr.html (top doc of the
    EHR window). Both may contain PHI; logs/ is gitignored."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", chart)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        to_ehr(driver, timeout=3)
    except Exception:
        pass  # screenshot whatever window is active
    try:
        driver.save_screenshot(str(LOG_DIR / f"{safe}.png"))
    except Exception:
        pass
    try:
        (LOG_DIR / f"{safe}_ehr.html").write_text(driver.page_source, encoding="utf-8", errors="replace")
    except Exception:
        pass


# --- Flow steps --------------------------------------------------------------

LOGIN_TIMEOUT = 90          # login submitted -> PM window (incl. interstitials)
EHR_OPEN_TIMEOUT = 60       # EHR icon clicked -> EHR window (incl. interstitials)


def login(driver, user, pw, office):
    # The shared helper prints window titles (which contain the username);
    # swallow its output so credentials never reach the console.
    with contextlib.redirect_stdout(io.StringIO()):
        ok = perform_login(driver, user, pw, office)
    if not ok:
        raise RuntimeError("Login failed (login form could not be filled/submitted).")
    # Notifications / confirm-email can appear right after login, before the PM opens.
    clear_interstitials(driver, lambda: find_window(driver, is_pm), LOGIN_TIMEOUT,
                        "PM window after login", scan_login_frames=True)
    switch_to_window(driver, is_pm, 15, "PM window")
    say("Logged in.")


def open_ehr(driver):
    switch_to_window(driver, is_pm, 15, "PM window")
    btn = wait_in_frames(driver, By.CSS_SELECTOR, SEL_EHR_BUTTON, 30, "EHR toolbar icon")
    click(driver, btn)
    driver.switch_to.default_content()
    say("Clicked EHR icon.")

    # The EHR opens in a NEW window, possibly via one or more identity pages
    # (notifications, confirm-email, ...) that must be cleared first.
    clear_interstitials(driver, lambda: find_window(driver, is_ehr), EHR_OPEN_TIMEOUT,
                        "EHR window")
    to_ehr(driver, timeout=15)
    wait_in_frames(driver, By.CSS_SELECTOR,
                   f"{SEL_SEARCH_BUTTON}, {SEL_SEARCH_INPUT}", 60, "EHR patient search")
    driver.switch_to.default_content()
    verify_practice(driver)
    say("EHR ready (office key verified).")


# --- AdvancedMD identity interstitials (/apps/identity/#/<route>) ------------

IDENTITY_MARK = "/apps/identity/"
INTERSTITIAL_GRACE = 6.0    # seconds an unknown page / a page with nothing to click may stay


class InterstitialError(RuntimeError):
    """An identity page we do not know how to get past."""


def identity_route(url):
    """'https://x/apps/identity/#/notifications?a=1' -> 'notifications'.
    None if the URL is not an identity page."""
    if not url or IDENTITY_MARK not in url.lower():
        return None
    return urlparse(url).fragment.split("?")[0].strip("/").lower()


def classify_route(route):
    """confirm-email / notifications (handled), wait (loading or the login form
    itself - not an error by itself), other (unknown: stop), None (not identity)."""
    if route is None:
        return None
    if route.startswith("confirm-email"):
        return "confirm-email"
    if route.startswith("notifications"):
        return "notifications"
    if route == "" or route.startswith("login"):
        return "wait"
    return "other"


def find_window(driver, predicate):
    """Handle of a window whose (title, url) matches - via DevTools, no switching."""
    targets = page_targets(driver)
    handles = list(driver.window_handles)
    if targets is not None and set(handles) <= set(targets):
        return next((h for h in handles if predicate(*targets[h])), None)
    for h in handles:  # fallback
        try:
            driver.switch_to.window(h)
            if predicate(driver.title or "", driver.current_url or ""):
                return h
        except WebDriverException:
            pass
    return None


# Click visible buttons/links whose whole text equals one of the labels
# (case-insensitive). Text on a <span> inside a button clicks the button.
JS_CLICK_TEXT = """
var labels = arguments[0].map(function (s) { return s.toLowerCase(); });
var all = arguments[1];
function vis(e) {
  var st = window.getComputedStyle(e);
  if (st.display === 'none' || st.visibility === 'hidden') return false;
  return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
}
var targets = [];
document.querySelectorAll('button, a, [role=button], span').forEach(function (el) {
  var t = (el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  if (labels.indexOf(t) < 0 || !vis(el)) return;
  var target = el.closest('button, a, [role=button]') || el;
  if (targets.indexOf(target) < 0 && !target.disabled) targets.push(target);
});
if (!all) targets = targets.slice(0, 1);
targets.forEach(function (el) { el.click(); });
return targets.length;
"""


def click_by_text(driver, labels, click_all=False):
    """Click in the CURRENT document; returns how many elements were clicked."""
    return int(driver.execute_script(JS_CLICK_TEXT, list(labels), bool(click_all)) or 0)


def enter_identity_context(driver, scan_frames):
    """In the current window, find the identity app: the top document, or (login
    window only) one of its iframes. Leaves the driver there; returns its URL."""
    driver.switch_to.default_content()
    url = driver.current_url or ""
    if identity_route(url) is not None or not scan_frames:
        return url if identity_route(url) is not None else None
    for i in range(len(driver.find_elements(By.CSS_SELECTOR, "iframe"))):
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(driver.find_elements(By.CSS_SELECTOR, "iframe")[i])
            href = driver.execute_script("return location.href;") or ""
            if identity_route(href) is not None:
                return href
        except (WebDriverException, IndexError):
            continue
    driver.switch_to.default_content()
    return None


def save_interstitial(driver, route):
    """logs/<client>/identity_<route>.png/.html (username/office key masked)."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", route or "root")[:60]
    secrets = getattr(driver, "_mask", ())
    with contextlib.suppress(Exception):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(str(LOG_DIR / f"identity_{safe}.png"))
        (LOG_DIR / f"identity_{safe}.html").write_text(
            mask_secrets(driver.page_source, *secrets), encoding="utf-8", errors="replace")
    return f"logs/{CLIENT}/identity_{safe}.png"


def handle_notifications(driver, key, nothing_since):
    """'Snooze all', else 'Snooze' on each item. 'Dismiss' only as a last resort,
    when the page has shown no Snooze option for INTERSTITIAL_GRACE seconds."""
    if click_by_text(driver, ["Snooze all"]):
        say("Notifications: clicked 'Snooze all'.")
        return True
    n = click_by_text(driver, ["Snooze"], click_all=True)
    if n:
        say(f"Notifications: clicked 'Snooze' on {n} item(s).")
        return True
    if time.time() - nothing_since.setdefault(key, time.time()) >= INTERSTITIAL_GRACE:
        n = click_by_text(driver, ["Dismiss"], click_all=True)
        if n:
            say(f"Notifications: no Snooze option; clicked 'Dismiss' on {n} item(s).")
            return True
    return False


def clear_interstitials(driver, done, timeout, what, scan_login_frames=False, sleep=time.sleep):
    """Until done() returns truthy (the PM / EHR window exists): clear every
    AdvancedMD identity page in any window - also chained ones (notifications,
    then confirm-email, ...). Unknown identity pages are saved to logs/<client>/
    and stop the run. Returns done()'s value."""
    end = time.time() + timeout
    first_seen, nothing_since, last_route = {}, {}, None
    while True:
        try:
            result = done()
        except WebDriverException:
            result = None
        if result:
            return result
        if time.time() >= end:
            hint = f" (last identity page: {IDENTITY_MARK}#/{last_route})" if last_route is not None else ""
            raise TimeoutException(f"Timed out after {timeout}s waiting for {what}{hint}")
        acted = False
        for h in list(driver.window_handles):
            try:
                driver.switch_to.window(h)
                top = (driver.current_url or "").lower()
                is_login_window = "login.advancedmd.com" in top
                if identity_route(top) is None and not (scan_login_frames and is_login_window):
                    continue
                url = enter_identity_context(driver, scan_frames=scan_login_frames and is_login_window)
                if url is None:
                    continue
                route = identity_route(url)
                kind = classify_route(route)
                last_route = route
                if kind == "confirm-email":
                    if click_by_text(driver, ["Confirm later"]):
                        say("Clicked 'Confirm later'.")
                        acted = True
                elif kind == "notifications":
                    acted = handle_notifications(driver, (h, route), nothing_since) or acted
                elif kind == "other":
                    if time.time() - first_seen.setdefault((h, route), time.time()) >= INTERSTITIAL_GRACE:
                        shot = save_interstitial(driver, route)
                        raise InterstitialError(
                            f"unhandled AdvancedMD page {IDENTITY_MARK}#/{route} while waiting for "
                            f"{what}; saved {shot} - handle it manually or extend the bot")
            except WebDriverException:
                continue
        with contextlib.suppress(WebDriverException):
            driver.switch_to.default_content()
        sleep(2.0 if acted else 1.0)


def ensure_search_open(driver):
    """Return a FRESHLY located, visible search input (never a cached element).
    A modal (e.g. the Plan Manager) is dismissed first; if the input is
    collapsed, the Patients button is clicked to open it."""
    ensure_no_modal(driver)
    inputs = visible(driver, SEL_SEARCH_INPUT)
    if not inputs:
        btn = wait_until(lambda: visible(driver, SEL_SEARCH_BUTTON), 15, desc="Patients button")[0]
        click(driver, btn)
        inputs = wait_until(lambda: visible(driver, SEL_SEARCH_INPUT), 15, desc="search input")
    return inputs[0]


def reset_search(driver):
    """Focus the search box and empty it with REAL key events (Ctrl+A, Backspace).

    Probed on the live site: the app keeps showing the previous results even
    when the box is emptied, closed or reopened. So we do NOT wait for old
    results to disappear; search_chart() proves freshness another way."""
    box = ensure_search_open(driver)
    click(driver, box)
    if box.get_attribute("value"):
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.BACKSPACE)
        wait_until(lambda: not box.get_attribute("value"), 5, desc="search box to empty")
    return box


def _results_snapshot(driver):
    """(shown, total, card chart numbers) of what is on screen right now."""
    shown = total = None
    for st in visible(driver, SEL_SEARCH_STATUS):
        m = RESULT_STATUS_RE.search(st.text or "")
        if m:
            shown, total = int(m.group(1)), int(m.group(2))
    codes = tuple(card_chart_number(c) for c in visible(driver, SEL_RESULT_CARD))
    return shown, total, codes


def _is_stale(el):
    try:
        el.is_enabled()
        return False
    except StaleElementReferenceException:
        return True


def save_no_results_sample(driver, chart):
    """Save the EHR page for the no-results screen so selectors can be written for it."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)   # per client (may contain PHI)
        to_ehr(driver)
        (LOG_DIR / "search_no_results.html").write_text(driver.page_source, encoding="utf-8", errors="replace")
        say(f"  (saved logs/{CLIENT}/search_no_results.html for chart {chart})")
    except Exception:
        pass


def search_chart(driver, chart):
    """Type the chart number and return the ONE exactly-matching card, else raise Skip.

    The app keeps the previous results on screen, so results are only trusted
    once they show evidence of belonging to the NEW query:
      - the old result elements went stale, or
      - the results changed from what was on screen before typing, or
      - a row with exactly this chart number appeared, or
      - results stayed unchanged for FALLBACK_AFTER seconds (same results / no results)
    and then only after they stopped changing for STABLE_FOR seconds."""
    STABLE_FOR, FALLBACK_AFTER, TIMEOUT = 1.5, 5.0, 30.0

    box = reset_search(driver)
    old_cards = visible(driver, SEL_RESULT_CARD)
    old_snap = _results_snapshot(driver)
    for attempt in (1, 2):
        if attempt == 2:  # typing didn't take: re-locate, clear, retype once
            box = reset_search(driver)
        box.send_keys(chart)
        typed_at = time.time()
        try:
            wait_until(lambda: box.get_attribute("value") == chart, 4, desc="chart number typed")
            break
        except TimeoutException:
            if attempt == 2:
                raise

    last, since, settled = None, time.time(), None
    while time.time() - typed_at < TIMEOUT:
        try:
            snap = _results_snapshot(driver)
        except StaleElementReferenceException:
            snap = None
        if snap is None or snap != last:
            last, since = snap, time.time()
        elif time.time() - since >= STABLE_FOR:
            fresh = (
                (old_cards and any(_is_stale(c) for c in old_cards))
                or snap != old_snap
                or chart in snap[2]
                or time.time() - typed_at >= FALLBACK_AFTER
            )
            if fresh:
                settled = snap
                break
        time.sleep(0.3)
    if settled is None:
        raise TimeoutException(f"search results did not settle within {TIMEOUT:.0f}s")

    shown, total, codes = settled
    if not codes:
        save_no_results_sample(driver, chart)
        raise Skip("no results")
    if shown is None or len(codes) < shown:
        raise RuntimeError("search results incomplete (status/cards mismatch)")

    cards = visible(driver, SEL_RESULT_CARD)
    exact = [card for card in cards if card_chart_number(card) == chart]

    if len(exact) == 1:
        return exact[0]
    if not exact:
        # Likely the app's "no results" screen (it may keep stale cards on show);
        # save it so the real no-results markup can be inspected.
        save_no_results_sample(driver, chart)
        if total is not None and shown is not None and total > shown:
            raise Skip(f"no exact match among first {shown} of {total} results")
        raise Skip("no results / no exact match")
    raise Skip(f"{len(exact)} results with identical chart number")


def card_chart_number(card):
    """Chart number of a result row, compared EXACTLY (1687 != 16870)."""
    spans = card.find_elements(By.CSS_SELECTOR, SEL_CARD_CODE)
    if spans and spans[0].text.strip():
        return spans[0].text.strip()
    codes = card.find_elements(By.CSS_SELECTOR, SEL_CARD_CODES)
    m = CODE_RE.match(codes[0].text) if codes else None
    return m.group(1) if m else None


def name_key(text):
    """'LAST, FIRST M' / 'LAST,FIRST' -> ('LAST', 'FIRST') for comparison."""
    last, _, rest = (text or "").upper().partition(",")
    words = rest.split()
    return re.sub(r"[^A-Z]", "", last), re.sub(r"[^A-Z]", "", words[0] if words else "")


def plans_dialogs(driver):
    """Visible 'HealthWatcher Plan Manager' dialogs (EHR top document)."""
    out = []
    for dlg in visible(driver, SEL_PLANS_DIALOG):
        titles = dlg.find_elements(By.CSS_SELECTOR, ".ui-dialog-title")
        title = titles[0].text.strip() if titles else ""
        if title.startswith(PLANS_TITLE) or dlg.find_elements(By.CSS_SELECTOR, SEL_PLANS_IFRAME):
            out.append(dlg)
    return out


# One round-trip per poll: count visible Plan Manager dialogs, optionally click
# their title-bar X (NEVER Assign/Finish), and report any visible modal overlay.
JS_MODAL = """
var closePlans = arguments[0];
function vis(e) {
  if (!e) return false;
  var st = window.getComputedStyle(e);
  if (st.display === 'none' || st.visibility === 'hidden') return false;
  return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
}
var plans = 0, closed = 0, overlay = false;
document.querySelectorAll('div.ui-dialog').forEach(function (d) {
  if (!vis(d)) return;
  var t = d.querySelector('.ui-dialog-title');
  var title = t ? (t.textContent || '').trim() : '';
  if (title.indexOf('HealthWatcher Plan Manager') !== 0 &&
      !d.querySelector('iframe[src*="healthwatcher/plans.aspx"]')) return;
  plans++;
  if (closePlans) {
    var x = d.querySelector('.ui-dialog-titlebar a.ui-dialog-titlebar-close');
    if (x) { x.click(); closed++; }
  }
});
document.querySelectorAll('.ui-widget-overlay').forEach(function (o) { if (vis(o)) overlay = true; });
return {plans: plans, closed: closed, overlay: overlay};
"""


def modal_state(driver, close_plans=False):
    """(plans dialogs visible, how many X's were clicked, overlay visible) - one JS call."""
    st = driver.execute_script(JS_MODAL, bool(close_plans)) or {}
    return int(st.get("plans", 0)), int(st.get("closed", 0)), bool(st.get("overlay"))


def close_plans_dialog(driver, wait_for=5):
    """Close the 'HealthWatcher Plan Manager' dialog if it appears within wait_for s.
    ONLY via the X in its title bar - never Assign / Finish (they change the chart)."""
    to_ehr(driver)
    end = time.time() + wait_for
    while True:
        _plans, closed, _overlay = modal_state(driver, close_plans=True)
        if closed:
            wait_until(lambda: modal_state(driver)[0] == 0, 10, desc="plans dialog to close")
            return True
        if time.time() >= end:
            return False
        time.sleep(POLL)  # it can pop up a moment after the chart opens


def ensure_no_modal(driver, settle=9.0):
    """Make sure nothing modal covers the EHR before interacting with it.

    The Plan Manager dialog can pop up LATE (even after the patient's tab was
    closed) and its overlay blocks the search bar - so this runs before every
    interaction. Plan Manager is closed via its title-bar X only. Any other
    modal is not touched blindly: we raise so the failure dump shows it."""
    to_ehr(driver)
    end = time.time() + settle
    while True:
        plans, _closed, overlay = modal_state(driver, close_plans=True)
        if not plans and not overlay:
            return
        if time.time() >= end:
            raise RuntimeError("an unexpected dialog/overlay is blocking the EHR")
        time.sleep(POLL)


def open_chart(driver, chart, card):
    """Click the result, wait for the chart, verify banner chart# == requested.
    Returns the internal patientId (used later to verify the PDF URL)."""
    names = card.find_elements(By.CSS_SELECTOR, SEL_CARD_NAME)
    expected_name = name_key(names[0].text if names else "")
    tabs_before = len(patient_tabs(driver))
    target = card.find_elements(By.CSS_SELECTOR, SEL_CARD_CLICK) or [card]
    click(driver, target[0])

    def chart_frame():
        driver.switch_to.default_content()
        return [f for f in driver.find_elements(By.CSS_SELECTOR, SEL_CHART_IFRAME)
                if f.is_displayed()]
    wait_until(chart_frame, 30, desc="patient chart to open")
    close_plans_dialog(driver, wait_for=8)  # can appear several seconds after opening

    wait_until(lambda: len(patient_tabs(driver)) > tabs_before, 15, desc="new patient tab")

    def banner():
        to_ehr(driver)
        frames = chart_frame()
        if len(frames) != 1:
            return None  # exactly one visible chart = the active patient tab
        src = frames[0].get_attribute("src") or ""
        driver.switch_to.frame(frames[0])
        nums = [s.text.strip() for s in driver.find_elements(By.CSS_SELECTOR, SEL_BANNER_NUMBERS)]
        name_el = visible(driver, SEL_BANNER_NAME)
        name = name_el[0].text if name_el else ""
        if len(nums) >= 2 and all(nums[:2]) and name.strip():
            return nums[0], nums[1], name, src
        return None

    patient_id, banner_chart, banner_name, src = wait_until(banner, 30, desc="chart banner")
    driver.switch_to.default_content()
    # Three independent checks that this is the patient we searched for:
    if banner_chart != chart:
        raise RuntimeError("banner chart number does not match the requested chart number")
    if not expected_name[0] or name_key(banner_name) != expected_name:
        raise RuntimeError("banner patient name does not match the selected search result")
    if f"patientId={patient_id}" not in src:
        raise RuntimeError("chart frame patientId does not match the banner")
    return patient_id


def patient_tabs(driver):
    """Patient tabs in the EHR top strip - never 'Patients' or 'Dashboard'."""
    to_ehr(driver)
    tabs = []
    for li in visible(driver, SEL_PATIENT_TABS):
        title = (li.get_attribute("title") or li.text or "").strip().lower()
        if title not in PROTECTED_TAB_TITLES:
            tabs.append(li)
    return tabs


def close_tab(driver, li):
    ensure_no_modal(driver)  # an overlay would swallow the click on the tab's x
    before = len(patient_tabs(driver))
    xs = li.find_elements(By.CSS_SELECTOR, "i.amds-tab-exit")
    if not xs:
        raise RuntimeError("patient tab has no close (x) button")
    click(driver, xs[0])
    wait_until(lambda: len(patient_tabs(driver)) < before, 15, desc="patient tab to close")


def settle_after_close(driver):
    """After a tab closes: chart gone, no modal, search bar usable again."""
    wait_until(lambda: not visible(driver, SEL_CHART_IFRAME), 15, desc="chart to disappear")
    ensure_no_modal(driver)
    wait_until(lambda: visible(driver, f"{SEL_SEARCH_INPUT}, {SEL_SEARCH_BUTTON}"), 15,
               desc="search bar after tab close")


def close_current_patient(driver):
    """Close ONLY the active patient's tab (the one we just worked on).
    Returns how many patient tabs remain (should be 0)."""
    active = [li for li in patient_tabs(driver)
              if "amds-tab-active" in (li.get_attribute("class") or "")]
    if active:
        close_tab(driver, active[0])
    settle_after_close(driver)
    return len(patient_tabs(driver))


def close_all_patients(driver):
    """Recovery only: clear leftover patient tabs so they don't pile up."""
    for _ in range(20):
        tabs = patient_tabs(driver)
        if not tabs:
            return
        close_tab(driver, tabs[0])


def recover(driver):
    """Best effort: back to a clean EHR Patients search."""
    keep = set()
    for h in list(driver.window_handles):
        try:
            driver.switch_to.window(h)
            t, u = driver.title or "", driver.current_url or ""
            if is_pm(t, u) or is_ehr(t, u) or "login.advancedmd.com" in u:
                keep.add(h)
            else:
                driver.close()
        except WebDriverException:
            pass
    try:
        to_ehr(driver)
        close_plans_dialog(driver, wait_for=1)
        close_all_patients(driver)
        ensure_search_open(driver)
    except Exception:
        pass


# --- Main --------------------------------------------------------------------

# --- Stage 2: Chart Print -> Report Viewer -> verified PDF -------------------

def enter_chart_frame(driver):
    """Switch into the single visible patient-chart iframe of the EHR window."""
    to_ehr(driver)
    frames = [f for f in driver.find_elements(By.CSS_SELECTOR, SEL_CHART_IFRAME) if f.is_displayed()]
    if len(frames) != 1:
        return None
    driver.switch_to.frame(frames[0])
    return frames[0]


def open_chart_print_form(driver):
    """'...' menu -> printer icon -> Chart Print form. Leaves the driver INSIDE the
    ChartPrint iframe. Changes no checkbox/date: it only verifies that the two
    risky options are unchecked and refuses to continue otherwise."""
    ensure_no_modal(driver)

    def toggle():
        if not enter_chart_frame(driver):
            return None
        found = visible(driver, SEL_TOOLS_TOGGLE)
        return found[0] if found else None

    toggle_el = wait_until(toggle, 30, desc="chart '...' menu")  # now inside the chart frame

    def tools_open():
        lists = driver.find_elements(By.CSS_SELECTOR, SEL_TOOLS_LIST)
        return bool(lists) and "amds-tools-active" in (lists[0].get_attribute("class") or "")

    if not tools_open():
        click(driver, toggle_el)
        wait_until(tools_open, 10, desc="chart tools to expand")
    icon = wait_until(lambda: driver.find_elements(By.CSS_SELECTOR, SEL_CHART_PRINT_ICON), 10,
                      desc="Chart Print (printer) icon")[0]
    if (icon.get_attribute("title") or "").strip() != "Open Chart Print":
        raise RuntimeError("printer icon lookup returned a different tool; refusing to click")
    # JS click on this exact element: a native coordinate click landed on the
    # neighbouring 'Patient Education' icon in the live run (tight vertical list).
    driver.execute_script("arguments[0].click();", icon)

    def print_form():
        if not enter_chart_frame(driver):
            return None
        frames = [f for f in driver.find_elements(By.CSS_SELECTOR, SEL_CHARTPRINT_IFRAME) if f.is_displayed()]
        if len(frames) != 1:
            return None
        driver.switch_to.frame(frames[0])
        return visible(driver, SEL_BTN_PRINT) or None

    try:
        wait_until(print_form, 30, desc="Chart Print form")
    except TimeoutException:
        tabs = []  # tool-tab names (e.g. 'Patient Education'), useful to spot a wrong click
        try:
            if enter_chart_frame(driver):
                tabs = [(t.get_attribute("title") or "").strip()
                        for t in driver.find_elements(By.CSS_SELECTOR, "ul.amds-tab-list li.amds-tab")]
        except WebDriverException:
            pass
        raise RuntimeError(f"Chart Print form did not open (chart tabs open: {tabs or 'none'})")

    for sel, label in ((SEL_CHK_CONFID, "Include Confid. Items"), (SEL_CHK_DOCOPEN, "Attempt Indiv. Open")):
        boxes = driver.find_elements(By.CSS_SELECTOR, sel)
        if not boxes:
            raise RuntimeError(f"Chart Print option '{label}' not found")
        if boxes[0].is_selected():
            raise RuntimeError(f"Chart Print option '{label}' is checked; refusing to print")


def wait_for_report_window(driver, handles_before, timeout):
    """Find the new 'Report Viewer' window by URL (never by handle position) and
    switch to it ONCE. Its URL is watched through DevTools, without switching."""
    def probe():
        new = [h for h in driver.window_handles if h not in handles_before]
        if not new:
            return None
        targets = page_targets(driver)
        for h in new:
            if targets is not None and h in targets:
                if "reportviewer" in targets[h][1].lower():
                    driver.switch_to.window(h)
                    driver.switch_to.default_content()
                    return h
                continue
            try:  # no DevTools info for this window: inspect it directly
                driver.switch_to.window(h)
                if "reportviewer" in (driver.current_url or "").lower():
                    return h
            except WebDriverException:
                pass
        return None
    return wait_until(probe, timeout, poll=0.5, desc="Report Viewer window")


def clean_tmp():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for f in TMP_DIR.iterdir():
        try:
            f.unlink()
        except OSError:
            pass


def wait_for_download(timeout):
    """Wait for Chrome to finish downloading a .pdf into TMP_DIR (ignores .crdownload)."""
    end = time.time() + timeout
    while time.time() < end:
        if not list(TMP_DIR.glob("*.crdownload")):
            pdfs = [f for f in TMP_DIR.glob("*.pdf") if f.stat().st_size > 0]
            if pdfs:
                f = max(pdfs, key=lambda x: x.stat().st_mtime)
                size = f.stat().st_size
                time.sleep(1)  # size must hold still, i.e. the download really finished
                if f.exists() and f.stat().st_size == size and not list(TMP_DIR.glob("*.crdownload")):
                    return f
        time.sleep(0.5)
    return None


def download_with_requests(driver, dest, read_timeout):
    """Fetch the PDF URL from the Report Viewer's frame with the browser's cookies.
    Must be called while the Report Viewer is the current window (no switching)."""
    driver.switch_to.default_content()
    frames = driver.find_elements(By.CSS_SELECTOR, SEL_REPORT_FRAME)
    src = frames[0].get_attribute("src") if frames else ""
    if not src:
        raise RuntimeError("Report Viewer has no PDF frame URL")
    sess = requests.Session()
    sess.headers["User-Agent"] = USER_AGENT
    for c in driver.get_cookies():
        sess.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
    with sess.get(src, timeout=(10, read_timeout), stream=True) as r:
        ctype = r.headers.get("Content-Type", "")
        if r.status_code != 200 or "pdf" not in ctype.lower():
            raise RuntimeError(
                f"fallback download did not return a PDF (HTTP {r.status_code}, {ctype or 'no content-type'})")
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)


def check_pdf_file(path, chart, marker=None):
    """Raise RuntimeError unless `path` is a real PDF with >=1 page whose page 1
    shows 'Acct#: <chart>' (and `marker`, if given - the client's practice text).
    Returns the page count. Never echoes PDF text."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("PDF missing or empty")
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":
            raise RuntimeError("file is not a PDF (bad header)")
    import logging
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # AMD's xref quirks are recovered from; no console noise
    try:
        reader = PdfReader(str(path))
        pages = len(reader.pages)
        text = (reader.pages[0].extract_text() or "") if pages else ""
    except Exception as e:
        raise RuntimeError(f"PDF unreadable ({type(e).__name__})")
    if pages < 1:
        raise RuntimeError("PDF has no pages")
    if not re.search(r"Acct\s*#\s*:?\s*" + re.escape(chart) + r"(?!\d)", text, re.I):
        raise RuntimeError("page 1 does not show 'Acct#: <chart number>' (wrong patient or layout?)")
    if marker and " ".join(marker.split()).lower() not in " ".join(text.split()).lower():
        raise RuntimeError(f"page 1 does not show this client's {env_prefix(CLIENT or 'client')}"
                           "PDF_MARKER text (wrong practice?)")
    return pages


def report_id_from_url(url):
    return (parse_qs(urlparse(url).query).get("id") or [""])[0]


def save_chart_pdf(driver, chart, patient_id, dest, pdf_timeout):
    """Chart Print -> Print -> Report Viewer -> verified PDF at `dest`.
    A file only reaches `dest` after every check passes; a bad file is deleted.
    Returns (pages, seconds, method)."""
    t0 = time.time()
    clean_tmp()
    open_chart_print_form(driver)           # leaves the driver inside the ChartPrint frame
    handles_before = set(driver.window_handles)
    click(driver, visible(driver, SEL_BTN_PRINT)[0])

    candidate = None
    try:
        wait_for_report_window(driver, handles_before, 120)   # the one switch into the viewer
        # The internal id in the viewer URL must be the one in the chart banner.
        if report_id_from_url(driver.current_url) != patient_id:
            raise RuntimeError("Report Viewer id does not match the chart banner's internal ID")

        # Live finding: Chrome never auto-downloads this PDF (it renders inline), and
        # waiting for that cost 60s per chart. Fetching the viewer's PDF URL with the
        # session cookies takes ~10s, so it goes first; the browser download is the backup.
        method = "http"
        candidate = TMP_DIR / "fetched.pdf"
        try:
            download_with_requests(driver, candidate, pdf_timeout)
        except (RuntimeError, requests.RequestException) as e:
            say(f"    http fetch failed ({type(e).__name__}); waiting for browser download")
            method = "browser download"
            Path(candidate).unlink(missing_ok=True)
            candidate = wait_for_download(pdf_timeout)
            if candidate is None:
                raise RuntimeError("no PDF obtained (http fetch failed and Chrome did not download one)")

        pages = check_pdf_file(candidate, chart, PDF_MARKER)
        CHART_DIR.mkdir(parents=True, exist_ok=True)
        os.replace(candidate, dest)
        candidate = None
        return pages, time.time() - t0, method
    finally:
        if candidate is not None:  # failed verification: never keep the file
            try:
                Path(candidate).unlink()
            except OSError:
                pass
        for h in [x for x in driver.window_handles if x not in handles_before]:  # Report Viewer (+ strays)
            try:
                current = driver.current_window_handle
            except WebDriverException:
                current = None
            try:
                if current != h:   # normally we are already on the viewer: no extra switch
                    driver.switch_to.window(h)
                driver.close()
            except WebDriverException:
                pass
        try:
            to_ehr(driver)          # the one switch back
        except Exception:
            pass  # main loop's recover() deals with it


def process(driver, chart, until, pdf_timeout):
    pdf_path = CHART_DIR / f"{chart}.pdf"
    try:
        rel = str(pdf_path.relative_to(ROOT))
    except ValueError:  # CHART_DIR customised outside the project
        rel = str(pdf_path)
    if pdf_path.exists():  # resume: skip only a file that still passes verification
        try:
            check_pdf_file(pdf_path, chart)
            return "EXISTS", rel, ""
        except RuntimeError as e:
            say(f"    existing file for {chart} failed verification ({e}); re-downloading")
            pdf_path.unlink()

    to_ehr(driver)
    verify_practice(driver)   # before every chart: still this client's office key
    card = search_chart(driver, chart)
    if until == "search":
        return "FOUND", "", ""

    patient_id = open_chart(driver, chart, card)
    pdf_info = None
    if until == "pdf":
        pages, secs, method = save_chart_pdf(driver, chart, patient_id, pdf_path, pdf_timeout)
        say(f"    PDF verified: {pages} page(s), {method}, {secs:.0f}s")
        pdf_info = rel

    remaining = close_current_patient(driver)
    say(f"    tab closed; patient tabs remaining: {remaining}")
    if remaining:
        raise RuntimeError(f"{remaining} patient tab(s) still open after closing")
    return ("DOWNLOADED", pdf_info, "") if pdf_info else ("OPENED", "", "")


# --- Long-run robustness: session health, restart, progress, outstanding list --

MAX_RELOGINS = 3                      # re-login attempts in a row before the run stops
MAX_CONSECUTIVE_FAILS = 3             # FAILED charts in a row => refresh the session once
PROVEN_STATUSES = {"DOWNLOADED", "EXISTS", "SKIPPED", "FOUND", "OPENED"}   # prove the session works
LOGIN_URL_PARTS = ("login.advancedmd.com", "/apps/identity")
DIALOG_CSS = ".ui-dialog, [role=dialog], .modal, .mat-dialog-container"
EXPIRED_RE = re.compile(
    r"session\s+(has\s+)?(expired|timed\s*out|timeout)|(logged|signed)\s+out|"
    r"(log|sign)\s*in\s+again|inactivity", re.I)   # not 'inactiv': would match an 'Inactive' patient

JS_SESSION_FLAGS = """
var re = new RegExp(arguments[0], 'i');
function vis(e) {
  if (!e) return false;
  var st = window.getComputedStyle(e);
  if (st.display === 'none' || st.visibility === 'hidden') return false;
  return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
}
var expired = false;
document.querySelectorAll('.ui-dialog, [role=dialog], .modal, .mat-dialog-container').forEach(function (d) {
  if (vis(d) && re.test(d.innerText || '')) expired = true;
});
return {login: vis(document.querySelector('#loginName')), expired: expired};
"""


def session_problem(driver, login_handle):
    """None if the session looks usable, else a short reason. Detects: browser dead,
    EHR window gone, a window redirected to the login page, a login form, or a
    session-expired dialog. (The very first window legitimately stays on the login
    page, so it is exempt.) Window titles/URLs come from DevTools and the EHR page
    is checked with one JS call - no window is brought to the front. Leaves the
    driver on the EHR window when healthy."""
    if driver is None:
        return "no browser"
    try:
        handles = list(driver.window_handles)
        if not handles:
            return "all browser windows are gone"
        targets = page_targets(driver)
        if targets is None or not set(handles) <= set(targets):
            return _session_problem_by_switching(driver, login_handle)
        ehr = None
        for h in handles:
            title, url = targets[h]
            low = url.lower()
            if h != login_handle and "confirm-email" not in low and (
                    any(part in low for part in LOGIN_URL_PARTS) or title.startswith("Log in to AdvancedMD")):
                return "redirected to the login page"
            if is_ehr(title, url):
                ehr = h
        if ehr is None:
            return "EHR window is gone"
        driver._ehr_handle = ehr
        to_ehr(driver)  # no-op when already on it
        flags = driver.execute_script(JS_SESSION_FLAGS, EXPIRED_RE.pattern) or {}
        if flags.get("login"):
            return "login form is showing"
        if flags.get("expired"):
            return "session-expired dialog"
        return None
    except Exception:  # WebDriverException, urllib3 connection errors, ...
        return "browser not responding"


def _session_problem_by_switching(driver, login_handle):
    """Fallback when DevTools is unavailable: visit each window to inspect it."""
    if driver is None:
        return "no browser"
    try:
        handles = list(driver.window_handles)
        if not handles:
            return "all browser windows are gone"
        ehr = None
        for h in handles:
            driver.switch_to.window(h)
            driver.switch_to.default_content()
            title, url = driver.title or "", (driver.current_url or "")
            low = url.lower()
            if h != login_handle:
                if "confirm-email" not in low and (
                        any(part in low for part in LOGIN_URL_PARTS) or title.startswith("Log in to AdvancedMD")):
                    return "redirected to the login page"
                if visible(driver, "#loginName"):
                    return "login form is showing"
                for dlg in visible(driver, DIALOG_CSS):
                    if EXPIRED_RE.search(dlg.text or ""):
                        return "session-expired dialog"
            if is_ehr(title, url):
                ehr = h
        if ehr is None:
            return "EHR window is gone"
        driver.switch_to.window(ehr)
        driver.switch_to.default_content()
        return None
    except Exception:  # WebDriverException, urllib3 connection errors, ...
        return "browser not responding"


def mask_secrets(text, *secrets):
    for s in secrets:
        if s:
            text = re.sub(re.escape(s), "<hidden>", text, flags=re.I)
    return text


def dump_startup(driver, user, office):
    """Start-up failed (login / EHR did not open): list every window (title + URL,
    username and office key masked) on the console and in
    logs/<client>/startup_windows.txt, plus a screenshot + HTML per window.
    Nothing patient-specific is open yet at this stage."""
    if driver is None:
        return
    lines = []
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        for i, h in enumerate(list(driver.window_handles), 1):
            try:
                driver.switch_to.window(h)
                driver.switch_to.default_content()
                title = mask_secrets(driver.title or "", user, office)
                url = mask_secrets(driver.current_url or "", user, office)
                lines.append(f"window {i}: title='{title}' url={url}")
                driver.save_screenshot(str(LOG_DIR / f"startup_{i}.png"))
                (LOG_DIR / f"startup_{i}.html").write_text(
                    mask_secrets(driver.page_source, user, office), encoding="utf-8", errors="replace")
            except Exception as e:
                lines.append(f"window {i}: unreadable ({type(e).__name__})")
    except Exception as e:
        lines.append(f"could not list windows ({type(e).__name__})")
    say("Start-up failed. Browser windows at that moment:")
    for ln in lines:
        say("  " + ln)
    with contextlib.suppress(OSError):
        (LOG_DIR / "startup_windows.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        say(f"  (screenshots/HTML: {LOG_DIR.relative_to(ROOT)}\\startup_*.png/.html)")


class Browser:
    """Owns the Chrome session: start (login + EHR), health check, full restart."""

    def __init__(self, user, pw, office, until, headless=False):
        self.user, self.pw, self.office = user, pw, office
        self.until, self.headless = until, headless
        self.driver = None
        self.login_handle = None

    def start(self):
        # Fresh Chrome profile per start, unique per client + PID (parallel runs
        # never share one); removed again in stop().
        rmtree_quiet(CHROME_PROFILE_DIR, tries=2)
        profile = str(CHROME_PROFILE_DIR)
        if self.until == "pdf":
            # Files are only moved to downloads/<client>/charts/ after verification.
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            self.driver = setup_driver(
                download_dir=str(TMP_DIR.resolve()),
                extra_prefs={"plugins.always_open_pdf_externally": True,
                             "download.prompt_for_download": False},
                headless=self.headless, maximized=False,   # fixed 1920x1080 window
                user_data_dir=profile,
            )
        else:
            self.driver = setup_driver(download_dir=None, headless=self.headless,
                                       maximized=False, user_data_dir=profile)
        self.driver._expected_office = self.office
        self.driver._mask = (self.user, self.office)   # masked in saved HTML dumps
        try:
            self.login_handle = self.driver.current_window_handle
            login(self.driver, self.user, self.pw, self.office)
            open_ehr(self.driver)
        except Exception:
            dump_startup(self.driver, self.user, self.office)
            self.stop()
            raise

    def stop(self):
        drv, self.driver = self.driver, None
        if drv is None:
            return
        proc = getattr(getattr(drv, "service", None), "process", None)
        try:
            drv.quit()
        except Exception:
            pass
        try:  # make sure no chromedriver/Chrome is left behind after a crash
            if proc is not None and proc.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                else:
                    proc.kill()
        except Exception:
            pass
        rmtree_quiet(CHROME_PROFILE_DIR)

    def restart(self):
        self.stop()
        self.start()

    def problem(self):
        return session_problem(self.driver, self.login_handle)


def fmt_eta(seconds):
    if seconds is None:
        return "?"
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m" if minutes else "<1m"


def read_outstanding():
    if not FAILED_LIST.exists():
        return []
    return [ln.strip() for ln in FAILED_LIST.read_text(encoding="utf-8").splitlines() if ln.strip()]


def update_outstanding(results, charts, unreached_from=None):
    """Keep logs/failed_or_skipped.txt = chart numbers still NOT downloaded, one per
    line (ready for --charts-file). Cumulative across runs/batches: charts that are
    now DOWNLOADED/EXISTS are removed, FAILED/SKIPPED added, and - if the run was
    aborted - every chart it never reached is added too."""
    state = dict.fromkeys(read_outstanding())
    for chart, status, _err in results:
        if status in ("DOWNLOADED", "EXISTS"):
            state.pop(chart, None)
        elif status in ("FAILED", "SKIPPED"):
            state[chart] = None
    if unreached_from is not None:
        for chart in charts[unreached_from:]:
            state[chart] = None
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FAILED_LIST.with_suffix(".tmp")
    tmp.write_text("".join(f"{c}\n" for c in state), encoding="utf-8")
    os.replace(tmp, FAILED_LIST)
    return list(state)


def run(charts, browser, until, pdf_timeout, limit=None, process_fn=None, sleep=time.sleep):
    """The long-run loop. Returns (results, aborted, limited).

    results: [(chart, status, error)] in order. Session loss (logout, dead Chrome)
    is handled here: re-login, then carry on with the SAME chart."""
    process_fn = process_fn or process
    total = len(charts)
    todo = sum(1 for c in charts if not (CHART_DIR / f"{c}.pdf").exists()) if until == "pdf" else total
    if limit:
        todo = min(todo, limit)
    results, worked, work_secs = [], 0, 0.0
    relogins = consecutive_fails = 0
    aborted = limited = False
    unreached_from = None

    def relogin():
        nonlocal relogins
        while relogins < MAX_RELOGINS:
            relogins += 1
            say(f"  re-login attempt {relogins}/{MAX_RELOGINS} ...")
            sleep(5 * relogins)
            try:
                browser.restart()
                return True
            except Exception as e:
                say(f"  re-login failed: {short_error(e)}")
        return False

    for idx, chart in enumerate(charts, 1):
        if limit and worked >= limit:
            limited = True
            break
        started = time.time()
        lost = 0
        status = path = err = None
        while True:
            reason = browser.problem()
            if reason is None:
                try:
                    status, path, err = process_fn(browser.driver, chart, until, pdf_timeout)
                    break
                except Skip as sk:
                    status, path, err = "SKIPPED", "", str(sk)
                    break
                except PracticeMismatch as pm:   # wrong practice: never continue
                    aborted, unreached_from = True, idx
                    status, path, err = "FAILED", "", f"run stopped: {pm}"
                    break
                except Exception as e:
                    failure = short_error(e)
                    reason = browser.problem()   # an error + a dead session = session loss, not a bad chart
                    if reason is None:
                        status, path, err = "FAILED", "", failure
                        screenshot(browser.driver, chart)
                        recover(browser.driver)
                        break
            lost += 1
            say(f"  session problem ({reason}) at chart {chart}")
            if not relogin():
                aborted, unreached_from = True, idx
                status, path, err = "FAILED", "", f"run stopped: could not restore the session ({reason})"
                break
            if lost >= 2:  # this chart keeps killing the session: give up on it, move on
                status, path, err = "FAILED", "", f"session lost twice on this chart ({reason})"
                break

        secs = time.time() - started
        results.append((chart, status, err))
        log_row(chart, status, path, err, f"{secs:.1f}")
        if status != "EXISTS":
            worked += 1
            work_secs += secs
        avg = work_secs / worked if worked else None
        eta = avg * max(todo - worked, 0) if worked else None
        say(f"[{idx}/{total}] {chart} {status} {secs:.0f}s"
            + (f" (avg {avg:.0f}s/chart)" if avg is not None else "")
            + f", ETA {fmt_eta(eta)}" + (f" - {err}" if err else ""))

        if status in PROVEN_STATUSES:
            relogins = 0           # the session demonstrably works again
            consecutive_fails = 0
        elif status == "FAILED" and not aborted:
            consecutive_fails += 1
            if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                # A silent logout can look like ordinary failures: refresh the session.
                say(f"  {consecutive_fails} charts failed in a row; refreshing the session")
                consecutive_fails = 0
                if not relogin():
                    aborted, unreached_from = True, idx   # charts[idx:] = every chart not yet reached
        if until == "pdf":
            update_outstanding(results, charts, unreached_from)
        if aborted:
            break
    return results, aborted, limited


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", required=True,
                    help="client name (letters/digits/underscore), e.g. acpc. Selects AMD_<CLIENT>_* "
                         "credentials and the downloads/<client>/, logs/<client>/ folders")
    ap.add_argument("input", nargs="?", help=".txt or .xlsx with chart numbers (same as --charts-file)")
    ap.add_argument("--charts-file", dest="charts_file",
                    help=".txt (one chart number per line) or .xlsx (a 'chart_number' column, else first column)")
    ap.add_argument("--charts", nargs="+", help="chart numbers given directly")
    ap.add_argument("--until", choices=["search", "open", "pdf"], default="pdf",
                    help="search = stop after the exact-match search; open = also open the chart and "
                         "close it; pdf = full flow, save verified PDFs (default)")
    ap.add_argument("--pdf-timeout", type=int, default=120,
                    help="seconds to wait for the PDF (default 120)")
    ap.add_argument("--limit", type=int,
                    help="process at most N charts this run. Charts whose PDF already exists do not "
                         "count, so re-running the same command continues with the next N")
    ap.add_argument("--headless", action="store_true",
                    help="run Chrome without a window - recommended for bulk runs (default: visible)")
    ap.add_argument("--keep-open", action="store_true", help="wait for Enter before closing Chrome")
    args = ap.parse_args(argv)
    try:
        configure_client(args.client)
    except ValueError as e:
        ap.error(f"--client: {e}")

    charts = list(args.charts or [])
    for f in (args.input, args.charts_file):
        if f:
            if not Path(f).exists():
                ap.error(f"file not found: {f}")
            charts += read_chart_numbers(f)
    charts = [c.strip() for c in charts if c.strip()]
    if not charts:
        ap.error("no chart numbers given (input file or --charts)")
    if args.limit is not None and args.limit < 1:
        ap.error("--limit must be at least 1")

    global PDF_MARKER
    load_dotenv(ROOT / ".env")
    try:
        user, pw, office = load_credentials(CLIENT)
    except CredentialsError as e:
        say(f"ERROR: {e}")
        sys.exit(2)
    PDF_MARKER = (os.getenv(env_prefix(CLIENT) + "PDF_MARKER") or "").strip() or None

    try:
        acquire_lock()
    except LockError as e:
        say(f"ERROR: {e}")
        sys.exit(3)
    atexit.register(cleanup_run)   # backstop; the finally below normally does it
    browser = Browser(user, pw, office, args.until, headless=args.headless)
    results, aborted, limited, fatal = [], False, False, None
    try:
        remove_stale_run_dirs()
        say(f"{len(charts)} chart number(s). Mode: --until {args.until}"
            + (f", limit {args.limit}" if args.limit else "") + (", headless" if args.headless else "")
            + (", PDF marker on" if PDF_MARKER else ""))
        say(f"Output: {CHART_DIR.relative_to(ROOT)}  Logs: {LOG_DIR.relative_to(ROOT)}  (PID {os.getpid()})")
        if not args.headless and len(charts) > 20:
            say("Tip: for bulk runs use --headless (no window to flicker or to click into by accident).")
        browser.start()
        results, aborted, limited = run(charts, browser, args.until, args.pdf_timeout, args.limit)
        if args.keep_open and sys.stdin.isatty() and not args.headless and browser.driver:
            input("\nDone. Press Enter to close Chrome...")
    except KeyboardInterrupt:
        say("\nInterrupted. Finished charts are kept; re-run the same command to resume.")
    except Exception as e:   # e.g. login failed, wrong practice at start-up
        fatal = short_error(e)
        say(f"\nERROR: {fatal}")
    finally:
        try:
            browser.stop()
        finally:
            cleanup_run()

    say("\nSummary")
    for st in ("DOWNLOADED", "FOUND", "OPENED", "EXISTS", "SKIPPED", "FAILED"):
        group = [r for r in results if r[1] == st]
        if group:
            say(f"  {st}: {len(group)}")
            for chart, _, err in group:
                if err:
                    say(f"    {chart}: {err}")
    if aborted:
        say("  RUN STOPPED: the session could not be restored. Fix the cause, then re-run to resume.")
    if limited:
        say(f"  Limit of {args.limit} reached; re-run the same command to continue with the next charts.")
    say(f"Log: {LOG_CSV.relative_to(ROOT)}")
    if args.until == "pdf":
        say(f"Not downloaded (re-run with --charts-file): {FAILED_LIST.relative_to(ROOT)} "
            f"({len(read_outstanding())} chart(s))")
    if fatal:
        sys.exit(1)


if __name__ == "__main__":
    main()
