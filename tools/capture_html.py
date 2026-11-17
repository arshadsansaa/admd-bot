"""
capture_html.py - helper for collecting HTML samples from AdvancedMD.

Logs in (non-headless), then waits for YOU to navigate in the browser.
Each time you press Enter it snapshots every open window, including all
nested iframes, into html_samples/ (gitignored - may contain PHI).

It NEVER clicks anything. All clicking is done by you.

Run from the project root, in your own terminal (it needs keyboard input):
    .\\venv\\Scripts\\python.exe tools\\capture_html.py

Credentials come from .env: AMD_USERNAME, AMD_PASSWORD, AMD_OFFICE_KEY
(never printed).
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

OUT_DIR = ROOT / "html_samples"
MAX_FRAME_DEPTH = 6
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _safe_prefix(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip()) or "capture"


def _write(path, text):
    Path(path).write_text(text or "", encoding="utf-8", errors="replace")


def _walk_frames(driver, prefix, win_no, out_dir, frames_log, path=(), depth=0):
    """Recursively save every frame/iframe under the current context.
    Leaves the driver in the same frame context it started in."""
    if depth >= MAX_FRAME_DEPTH:
        frames_log.append(f"{'  ' * depth}[max depth {MAX_FRAME_DEPTH} reached, not descending]")
        return
    try:
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
    except WebDriverException:
        return

    for idx in range(len(frames)):
        # Re-find each time: switching contexts can make old references stale.
        try:
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            frame_el = frames[idx]
            fid = frame_el.get_attribute("id") or ""
            fname = frame_el.get_attribute("name") or ""
            fsrc = frame_el.get_attribute("src") or ""
        except (WebDriverException, IndexError):
            continue

        frame_path = path + (idx,)
        label = "_".join(str(p) for p in frame_path)
        frames_log.append(
            f"{'  ' * depth}window {win_no} frame {label}: id={fid!r} name={fname!r} src={fsrc!r}"
        )
        try:
            driver.switch_to.frame(frame_el)
        except WebDriverException as e:
            frames_log.append(f"{'  ' * depth}  (could not enter frame: {type(e).__name__})")
            continue
        try:
            _write(out_dir / f"{prefix}_{win_no}_frame_{label}.html", driver.page_source)
            _walk_frames(driver, prefix, win_no, out_dir, frames_log, frame_path, depth + 1)
        except WebDriverException as e:
            frames_log.append(f"{'  ' * depth}  (error inside frame: {type(e).__name__})")
        finally:
            try:
                driver.switch_to.parent_frame()
            except WebDriverException:
                driver.switch_to.default_content()
                # Can't recover the exact depth; stop walking this level to stay safe.
                return


def _save_raw_response(driver, url, prefix, win_no, out_dir):
    """Fetch the window's URL with the Selenium cookies to see if it is HTML or a PDF."""
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    for c in driver.get_cookies():
        sess.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
    resp = sess.get(url, timeout=60)
    ctype = resp.headers.get("Content-Type", "")
    ext = "pdf" if "pdf" in ctype.lower() else ("html" if "html" in ctype.lower() else "bin")
    body_path = out_dir / f"{prefix}_{win_no}_raw_response.{ext}"
    body_path.write_bytes(resp.content)
    _write(
        out_dir / f"{prefix}_{win_no}_raw_response_info.txt",
        f"url: {url}\nstatus: {resp.status_code}\ncontent-type: {ctype}\n"
        f"bytes: {len(resp.content)}\nsaved-as: {body_path.name}\n"
        f"first-bytes: {resp.content[:8]!r}\n",
    )
    return f"{body_path.name} ({ctype or 'no content-type'}, {len(resp.content)} bytes)"


def capture(driver, prefix, out_dir=OUT_DIR):
    """Snapshot every open window + all nested frames. Restores the active window."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = _safe_prefix(prefix)

    try:
        original = driver.current_window_handle
    except WebDriverException:
        original = None

    handles = list(driver.window_handles)
    windows_log, frames_log, summary = [], [], []

    for win_no, handle in enumerate(handles, start=1):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            title, url = driver.title, driver.current_url
        except WebDriverException as e:
            windows_log.append(f"window {win_no}: handle={handle} (unreadable: {type(e).__name__})")
            continue

        marker = "  <-- was active" if handle == original else ""
        windows_log.append(f"window {win_no}: handle={handle}\n  title={title!r}\n  url={url}{marker}")

        _write(out_dir / f"{prefix}_{win_no}_top.html", driver.page_source)
        _walk_frames(driver, prefix, win_no, out_dir, frames_log)
        driver.switch_to.default_content()

        if "reportviewer" in url.lower():
            try:
                summary.append("raw response: " + _save_raw_response(driver, url, prefix, win_no, out_dir))
            except Exception as e:  # network/auth problems must not kill the capture
                summary.append(f"raw response failed: {type(e).__name__}")

    _write(out_dir / f"{prefix}_windows.txt", "\n".join(windows_log) + "\n")
    _write(out_dir / f"{prefix}_frames.txt", "\n".join(frames_log) + "\n" if frames_log else "(no frames found)\n")

    # Restore the originally active window (fall back to the last one if it closed).
    try:
        if original in driver.window_handles:
            driver.switch_to.window(original)
        else:
            driver.switch_to.window(driver.window_handles[-1])
        driver.switch_to.default_content()
    except WebDriverException:
        pass

    n_files = len(list(out_dir.glob(f"{prefix}_*")))
    print(f"  saved {n_files} file(s) for '{prefix}' in {out_dir.name}/  "
          f"({len(handles)} window(s), {len(frames_log)} frame line(s))")
    for line in summary:
        print("  " + line)
    return n_files


def main():
    load_dotenv(ROOT / ".env")
    user = os.getenv("AMD_USERNAME")
    pw = os.getenv("AMD_PASSWORD")
    office = os.getenv("AMD_OFFICE_KEY")
    if not (user and pw and office):
        sys.exit("Set AMD_USERNAME, AMD_PASSWORD and AMD_OFFICE_KEY in .env first.")

    from accounts.amd_common import (
        setup_driver, perform_login, handle_popups, switch_to_dashboard_window,
    )

    driver = setup_driver(headless=False)
    try:
        if not perform_login(driver, user, pw, office):
            sys.exit("Login failed.")
        handle_popups(driver)
        if not switch_to_dashboard_window(driver):
            sys.exit("Dashboard did not load.")

        print("\nLogged in. You drive the browser; I only take snapshots.")
        while True:
            raw = input(
                "\nNavigate to the next screen, then type a filename prefix "
                "(e.g. 05_patients_search) and press Enter. Type q to quit.\n> "
            )
            if raw.strip().lower() in ("q", "quit", "exit"):
                break
            if not raw.strip():
                continue
            try:
                capture(driver, raw)
            except WebDriverException as e:
                print(f"  capture failed: {type(e).__name__} - is the browser still open?")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
