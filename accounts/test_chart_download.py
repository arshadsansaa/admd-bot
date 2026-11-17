"""Offline tests for accounts/chart_download.py multi-client support.

No browser, no network. Every test points chart_download.ROOT (and the Chrome
profile temp dir) at a throw-away folder, so the real downloads/ and logs/ are
never read or written.

    .\\venv\\Scripts\\python.exe -m unittest accounts.test_chart_download -v
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from accounts import chart_download as cd


def make_pdf(path, text):
    """A minimal one-page PDF whose page text is `text` (pypdf can extract it)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(bytes(out))


class FakeDriver:
    def __init__(self, title, office):
        self.title = title
        self._expected_office = office


class FakeBrowser:
    def __init__(self, driver=None):
        self.driver = driver

    def problem(self):
        return None

    def restart(self):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.systemp = self.root / "systemp"
        self.systemp.mkdir()
        patches = [
            mock.patch.object(cd, "ROOT", self.root),
            mock.patch.object(cd.tempfile, "gettempdir", lambda: str(self.systemp)),
            mock.patch.object(cd, "PDF_MARKER", None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._reset_client)
        self.addCleanup(self._tmp.cleanup)

    def _reset_client(self):
        cd.CLIENT = None

    def quiet(self):
        return contextlib.redirect_stdout(io.StringIO())


class TestPaths(Base):
    def test_per_client_paths(self):
        cd.configure_client("ACPC", pid=111)
        self.assertEqual(cd.CHART_DIR, self.root / "downloads" / "acpc" / "charts")
        self.assertEqual(cd.TMP_DIR, self.root / "downloads" / "acpc" / "tmp" / "run_111")
        self.assertEqual(cd.LOG_CSV, self.root / "logs" / "acpc" / "chart_download_log.csv")
        self.assertEqual(cd.FAILED_LIST, self.root / "logs" / "acpc" / "failed_or_skipped.txt")
        self.assertEqual(cd.LOCK_FILE, self.root / "logs" / "acpc" / "run.lock")
        self.assertEqual(cd.CHROME_PROFILE_DIR, self.systemp / "amd_chart_acpc_111")

    def test_profile_and_tmp_unique_per_client_and_pid(self):
        seen = set()
        for client, pid in (("acpc", 1), ("pure", 1), ("acpc", 2)):
            cd.configure_client(client, pid=pid)
            seen.add((cd.TMP_DIR, cd.CHROME_PROFILE_DIR))
        self.assertEqual(len({t for t, _ in seen}), 3)
        self.assertEqual(len({p for _, p in seen}), 3)

    def test_bad_client_names(self):
        for bad in ("", "a-b", "a b", "../x", "pure/acpc", "con", "Nul"):
            with self.assertRaises(ValueError, msg=bad):
                cd.configure_client(bad)

    def test_cli_requires_client(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cd.main(["--charts", "1"])

    def test_console_prefix(self):
        cd.configure_client("hometown")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cd.say("\nSummary")
        self.assertEqual(buf.getvalue(), "[hometown] \n[hometown] Summary\n")

    def test_setup_driver_gets_own_profile(self):
        from accounts import amd_common
        with mock.patch.object(amd_common.webdriver, "Chrome") as chrome:
            amd_common.setup_driver(download_dir=str(self.root / "dl"), headless=True,
                                    user_data_dir=str(self.root / "prof"))
        args = chrome.call_args.kwargs["options"].arguments
        self.assertIn(f"--user-data-dir={self.root / 'prof'}", args)
        prefs = chrome.call_args.kwargs["options"].experimental_options["prefs"]
        self.assertEqual(prefs["download.default_directory"], str(self.root / "dl"))


class TestSameChartTwoClients(Base):
    def test_exists_is_per_client(self):
        cd.configure_client("acpc")
        make_pdf(cd.CHART_DIR / "1667.pdf", "Acct#: 1667")
        with self.quiet():
            self.assertEqual(cd.process(None, "1667", "pdf", 5)[0], "EXISTS")

        # Client B, same chart number: must NOT see A's file; goes to search.
        cd.configure_client("pure")
        searched = []

        def fake_search(driver, chart):
            searched.append(chart)
            raise cd.Skip("no results")

        drv = FakeDriver("AdvancedMD - EHR | 222", "222")
        with mock.patch.object(cd, "search_chart", fake_search), \
                mock.patch.object(cd, "to_ehr", lambda d, timeout=10: None), self.quiet():
            with self.assertRaises(cd.Skip):
                cd.process(drv, "1667", "pdf", 5)
        self.assertEqual(searched, ["1667"])
        self.assertFalse((cd.CHART_DIR / "1667.pdf").exists())
        self.assertTrue((self.root / "downloads" / "acpc" / "charts" / "1667.pdf").exists())

    def test_runs_log_and_outstanding_separately(self):
        def fake_process(status):
            return lambda driver, chart, until, t: (status, "", "")

        cd.configure_client("acpc")
        make_pdf(cd.CHART_DIR / "1667.pdf", "Acct#: 1667")
        with self.quiet():
            cd.run(["1667"], FakeBrowser(), "pdf", 5, process_fn=fake_process("EXISTS"))
        cd.configure_client("pure")
        with self.quiet():
            cd.run(["1667"], FakeBrowser(), "pdf", 5,
                   process_fn=lambda d, c, u, t: (_ for _ in ()).throw(cd.Skip("no results")))

        a_log = (self.root / "logs" / "acpc" / "chart_download_log.csv").read_text()
        b_log = (self.root / "logs" / "pure" / "chart_download_log.csv").read_text()
        self.assertIn("1667,EXISTS", a_log)
        self.assertNotIn("SKIPPED", a_log)
        self.assertIn("1667,SKIPPED", b_log)
        self.assertNotIn("EXISTS", b_log)
        self.assertEqual((self.root / "logs" / "acpc" / "failed_or_skipped.txt").read_text(), "")
        self.assertEqual((self.root / "logs" / "pure" / "failed_or_skipped.txt").read_text(), "1667\n")
        self.assertFalse((self.root / "logs" / "chart_download_log.csv").exists())


class TestCredentials(Base):
    def test_missing_lists_names_only(self):
        env = {"AMD_PURE_USERNAME": "secret-user-xyz", "AMD_USERNAME": "x",
               "AMD_PASSWORD": "y", "AMD_OFFICE_KEY": "z"}   # generic ones are NOT used
        with self.assertRaises(cd.CredentialsError) as ctx:
            cd.load_credentials("pure", env)
        msg = str(ctx.exception)
        self.assertIn("AMD_PURE_PASSWORD", msg)
        self.assertIn("AMD_PURE_OFFICE_KEY", msg)
        self.assertNotIn("AMD_PURE_USERNAME", msg)
        self.assertNotIn("secret-user-xyz", msg)

    def test_all_present(self):
        env = {"AMD_GOODDROP_USERNAME": "u", "AMD_GOODDROP_PASSWORD": "p",
               "AMD_GOODDROP_OFFICE_KEY": "k"}
        self.assertEqual(cd.load_credentials("gooddrop", env), ("u", "p", "k"))

    def test_main_exits_without_lock_or_secrets(self):
        env = {"AMD_ZZTEST_USERNAME": "secret-user-xyz"}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(cd, "load_dotenv"), \
                contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            cd.main(["--client", "zztest", "--charts", "1"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("AMD_ZZTEST_PASSWORD", out.getvalue())
        self.assertNotIn("secret-user-xyz", out.getvalue())
        self.assertFalse((self.root / "logs" / "zztest" / "run.lock").exists())


def _python_sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class TestLock(Base):
    def setUp(self):
        super().setUp()
        cd.configure_client("acpc")

    def write_lock(self, pid):
        cd.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        cd.LOCK_FILE.write_text(f"pid={pid}\nstarted=2026-11-13T06:00:00\n", encoding="utf-8")

    def test_acquire_and_release(self):
        cd.acquire_lock()
        self.assertEqual(cd.read_lock()["pid"], os.getpid())
        cd.release_lock()
        self.assertFalse(cd.LOCK_FILE.exists())

    def test_refuses_when_running(self):
        proc = _python_sleeper()
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.write_lock(proc.pid)
        with self.assertRaises(cd.LockError) as ctx, self.quiet():
            cd.acquire_lock()
        self.assertIn(str(proc.pid), str(ctx.exception))
        self.assertEqual(cd.read_lock()["pid"], proc.pid)   # untouched

    def test_other_client_not_blocked(self):
        proc = _python_sleeper()
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.write_lock(proc.pid)          # acpc is locked ...
        cd.configure_client("pure")        # ... pure can still start
        cd.acquire_lock()
        self.assertEqual(cd.read_lock()["pid"], os.getpid())

    def test_stale_lock_is_replaced(self):
        dead = _dead_pid()
        self.assertFalse(cd.pid_running(dead))
        self.write_lock(dead)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cd.acquire_lock()
        self.assertIn("stale lock", out.getvalue())
        self.assertEqual(cd.read_lock()["pid"], os.getpid())

    def test_garbage_lock_old_is_stale_new_refuses(self):
        cd.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        cd.LOCK_FILE.write_text("", encoding="utf-8")
        with self.assertRaises(cd.LockError), self.quiet():
            cd.acquire_lock()                       # just created: maybe starting
        old = time.time() - 60
        os.utime(cd.LOCK_FILE, (old, old))
        with self.quiet():
            cd.acquire_lock()                       # old and empty: stale
        self.assertEqual(cd.read_lock()["pid"], os.getpid())

    def test_release_leaves_foreign_lock(self):
        self.write_lock(424242)
        cd.release_lock()
        self.assertTrue(cd.LOCK_FILE.exists())

    def test_pid_running(self):
        self.assertTrue(cd.pid_running(os.getpid()))
        self.assertFalse(cd.pid_running(_dead_pid()))
        self.assertFalse(cd.pid_running(None))
        self.assertFalse(cd.pid_running("x"))


class TestMainLifecycle(Base):
    """main() end-to-end with a fake Browser: lock + temp dirs cleaned on every exit."""
    ENV = {"AMD_HOMETOWN_USERNAME": "u", "AMD_HOMETOWN_PASSWORD": "p",
           "AMD_HOMETOWN_OFFICE_KEY": "k"}

    def run_main(self, start_effect):
        made = {}

        class B:
            def __init__(s, user, pw, office, until, headless=False):
                s.driver = None

            def start(s):
                made["tmp"], made["prof"] = cd.TMP_DIR, cd.CHROME_PROFILE_DIR
                cd.TMP_DIR.mkdir(parents=True)
                cd.CHROME_PROFILE_DIR.mkdir(parents=True)
                (cd.CHROME_PROFILE_DIR / "Cookies").write_text("x")
                made["lock_during_run"] = cd.LOCK_FILE.exists()
                start_effect()

            def stop(s):
                pass

        out = io.StringIO()
        with mock.patch.dict(os.environ, self.ENV), mock.patch.object(cd, "load_dotenv"), \
                mock.patch.object(cd, "Browser", B), \
                mock.patch.object(cd, "run", lambda *a, **k: ([], False, False)), \
                mock.patch.object(cd.atexit, "register"), contextlib.redirect_stdout(out):
            try:
                cd.main(["--client", "hometown", "--charts", "1", "--headless"])
            except SystemExit:
                pass
        self.assertTrue(made["lock_during_run"])
        self.assertFalse((self.root / "logs" / "hometown" / "run.lock").exists())
        self.assertFalse(made["tmp"].exists())
        self.assertFalse(made["prof"].exists())
        self.assertFalse((self.root / "downloads" / "hometown" / "tmp").exists())
        for line in out.getvalue().splitlines():
            self.assertTrue(line.startswith("[hometown] "), line)
        return out.getvalue()

    def test_normal_exit(self):
        self.run_main(lambda: None)

    def test_ctrl_c(self):
        out = self.run_main(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertIn("Interrupted", out)

    def test_login_failure(self):
        out = self.run_main(lambda: (_ for _ in ()).throw(RuntimeError("Login failed")))
        self.assertIn("ERROR: RuntimeError: Login failed", out)

    def test_stale_run_dirs_removed_but_not_other_clients(self):
        cd.configure_client("hometown")
        dead = _dead_pid()
        stale_tmp = cd.TMP_ROOT / f"run_{dead}"
        stale_prof = self.systemp / f"amd_chart_hometown_{dead}"
        other_prof = self.systemp / f"amd_chart_hometown_x_{dead}"   # client 'hometown_x'
        for d in (stale_tmp, stale_prof, other_prof):
            d.mkdir(parents=True)
        self.run_main(lambda: None)
        self.assertFalse(stale_tmp.exists())
        self.assertFalse(stale_prof.exists())
        self.assertTrue(other_prof.exists())


class TestPractice(Base):
    def test_title_check(self):
        cd.configure_client("acpc")
        cd.check_practice("AdvancedMD - EHR | 123456", "123456")
        with self.assertRaises(cd.PracticeMismatch) as ctx:
            cd.check_practice("AdvancedMD - EHR | 999999", "123456")
        self.assertNotIn("999999", str(ctx.exception))
        self.assertNotIn("123456", str(ctx.exception))
        self.assertIn("AMD_ACPC_OFFICE_KEY", str(ctx.exception))
        for bad in ("AdvancedMD - EHR | 1234567", "Report Viewer", "", None):
            with self.assertRaises(cd.PracticeMismatch):
                cd.check_practice(bad, "123456")

    def test_mismatch_stops_the_run(self):
        cd.configure_client("acpc")
        calls = []

        def proc(driver, chart, until, t):
            calls.append(chart)
            raise cd.PracticeMismatch("different office key")

        with self.quiet():
            results, aborted, _ = cd.run(["1", "2", "3"], FakeBrowser(), "pdf", 5, process_fn=proc)
        self.assertTrue(aborted)
        self.assertEqual(calls, ["1"])
        self.assertEqual(cd.read_outstanding(), ["1", "2", "3"])

    def test_pdf_marker(self):
        cd.configure_client("acpc")
        p = self.root / "x.pdf"
        make_pdf(p, "Acct#: 1667 ROSWELL NM  88201")
        self.assertEqual(cd.check_pdf_file(p, "1667"), 1)
        self.assertEqual(cd.check_pdf_file(p, "1667", "roswell nm 88201"), 1)
        with self.assertRaises(RuntimeError):
            cd.check_pdf_file(p, "1667", "SOMEWHERE ELSE")
        with self.assertRaises(RuntimeError):
            cd.check_pdf_file(p, "166")


# --- Identity interstitials ---------------------------------------------------

class TestIdentityRoutes(unittest.TestCase):
    def test_route_parsing(self):
        base = "https://static-100.advancedmd.com/apps/identity/"
        self.assertEqual(cd.identity_route(base + "#/notifications"), "notifications")
        self.assertEqual(cd.identity_route(base + "#/confirm-email?x=1"), "confirm-email")
        self.assertEqual(cd.identity_route(base), "")
        self.assertIsNone(cd.identity_route("https://login.advancedmd.com/"))
        self.assertIsNone(cd.identity_route("https://static-100.advancedmd.com/apps/login/"))
        self.assertIsNone(cd.identity_route(None))
        kinds = {r: cd.classify_route(r) for r in
                 ("notifications", "confirm-email", "", "login", "mfa-setup", None)}
        self.assertEqual(kinds, {"notifications": "notifications", "confirm-email": "confirm-email",
                                 "": "wait", "login": "wait", "mfa-setup": "other", None: None})

    def test_timeout_names_last_identity_page(self):
        class Switch:
            def window(self, h):
                pass

            def default_content(self):
                pass

        class D:   # one identity window that never changes; nothing to click
            window_handles = ["w1"]
            current_url = "https://x/apps/identity/#/login"
            switch_to = Switch()

        with self.assertRaises(cd.TimeoutException) as ctx, \
                contextlib.redirect_stdout(io.StringIO()):
            cd.clear_interstitials(D(), lambda: None, 0.05, "EHR window", sleep=lambda s: None)
        self.assertIn("/apps/identity/#/login", str(ctx.exception))


IDENTITY_HTML = r"""<!doctype html><html><head><title>Log in to AdvancedMD</title></head>
<body><div id="app"></div><script>
var mode = new URLSearchParams(location.search).get('mode') || 'all';
var items = (mode === 'all' || mode === 'items' || mode === 'login') ? 2 : 1;
function go(h) { location.hash = h; }
function done() {
  if (mode === 'login') { window.open('../../pm.html'); go('#/login'); }
  else go('#/confirm-email');
}
function render() {
  var r = location.hash, app = document.getElementById('app'), h = '';
  if (r.indexOf('#/notifications') === 0) {
    for (var i = 0; i < items; i++) {
      h += '<div class="item"><b>Required Maintenance</b> ';
      if (mode !== 'dismissonly')
        h += '<a href="javascript:void 0" onclick="items--; items ? render() : done()"><span>Snooze</span></a> ';
      h += '<a href="javascript:void 0" onclick="' +
           (mode === 'dismissonly' ? 'items--; items ? render() : done()' : "go('#/dismissed-wrongly')") +
           '">Dismiss</a></div>';
    }
    if (mode === 'all') h += '<button type="button" onclick="done()"> Snooze all </button>';
  } else if (r.indexOf('#/confirm-email') === 0) {
    h = '<button type="button" class="btn" id="cl"><span> Confirm later </span></button>';
  } else if (r.indexOf('#/login') === 0) {
    h = '<p>login</p>';
  } else {
    h = '<p>Set up multi-factor authentication</p><button>Continue</button>';
  }
  app.innerHTML = h;
  var cl = document.getElementById('cl');
  if (cl) cl.onclick = function () { location.href = '../../ehr.html'; };
}
window.onhashchange = render; render();
</script></body></html>"""


class TestInterstitialsInChrome(Base):
    """Real headless Chrome on local file:// mock pages - no network, no AdvancedMD."""
    driver = None
    skip_reason = ""

    @classmethod
    def setUpClass(cls):
        cls.site = tempfile.TemporaryDirectory()
        site = Path(cls.site.name)
        (site / "apps" / "identity").mkdir(parents=True)
        (site / "apps" / "identity" / "index.html").write_text(IDENTITY_HTML, encoding="utf-8")
        (site / "ehr.html").write_text("<title>AdvancedMD - EHR | 123</title>EHR", encoding="utf-8")
        (site / "pm.html").write_text("<title>AdvancedMD PM - Test 123</title>PM", encoding="utf-8")
        # a folder named like the login host, so the URL looks like the login window's
        (site / "login.advancedmd.com").mkdir()
        (site / "login.advancedmd.com" / "index.html").write_text(
            '<title>Login | AdvancedMD</title><iframe src="../apps/identity/index.html?mode=login'
            '#/notifications" width="800" height="600"></iframe>', encoding="utf-8")
        cls.base = site.as_uri()
        cls.profile = tempfile.mkdtemp()
        from accounts.amd_common import setup_driver
        try:
            cls.driver = setup_driver(headless=True, user_data_dir=cls.profile)
        except Exception as e:  # no Chrome available: skip, don't fail
            cls.skip_reason = f"Chrome not available ({type(e).__name__})"

    @classmethod
    def tearDownClass(cls):
        if cls.driver:
            cls.driver.quit()
        cls.site.cleanup()
        cd.rmtree_quiet(cls.profile)

    def setUp(self):
        super().setUp()
        if self.driver is None:
            self.skipTest(self.skip_reason)
        cd.configure_client("hometown")
        d = self.driver
        for h in d.window_handles[1:]:
            d.switch_to.window(h)
            d.close()
        d.switch_to.window(d.window_handles[0])
        d.get(self.base + "/pm.html")
        p = mock.patch.object(cd, "INTERSTITIAL_GRACE", 1.0)
        p.start()
        self.addCleanup(p.stop)

    def open_identity(self, query, route):
        self.driver.execute_script("window.open(arguments[0]);",
                                   f"{self.base}/apps/identity/index.html?{query}#/{route}")

    def clear(self, predicate, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            h = cd.clear_interstitials(self.driver, lambda: cd.find_window(self.driver, predicate),
                                       15, "test window", **kw)
        return h, out.getvalue()

    def test_snooze_all_then_confirm_email_then_ehr(self):
        self.open_identity("mode=all", "notifications")
        h, out = self.clear(cd.is_ehr)
        self.assertIn("clicked 'Snooze all'", out)
        self.assertIn("Clicked 'Confirm later'", out)
        self.assertNotIn("Dismiss", out)
        self.driver.switch_to.window(h)
        self.assertTrue(self.driver.title.startswith("AdvancedMD - EHR"))

    def test_snooze_each_item_when_no_snooze_all(self):
        self.open_identity("mode=items", "notifications")
        h, out = self.clear(cd.is_ehr)
        self.assertIn("clicked 'Snooze' on 2 item(s)", out)
        self.assertNotIn("Dismiss", out)

    def test_dismiss_only_as_last_resort(self):
        self.open_identity("mode=dismissonly", "notifications")
        h, out = self.clear(cd.is_ehr)
        self.assertIn("no Snooze option; clicked 'Dismiss'", out)

    def test_unknown_identity_page_stops_with_dump(self):
        self.open_identity("mode=all", "mfa-setup")
        with self.assertRaises(cd.InterstitialError) as ctx:
            self.clear(cd.is_ehr)
        self.assertIn("/apps/identity/#/mfa-setup", str(ctx.exception))
        self.assertTrue((cd.LOG_DIR / "identity_mfa-setup.png").exists())
        self.assertTrue((cd.LOG_DIR / "identity_mfa-setup.html").exists())

    def test_notification_inside_login_window_iframe(self):
        self.driver.get(self.base + "/login.advancedmd.com/index.html")
        h, out = self.clear(cd.is_pm, scan_login_frames=True)
        self.assertIn("clicked 'Snooze' on 2 item(s)", out)

    def test_login_iframe_ignored_without_scan(self):
        self.driver.get(self.base + "/login.advancedmd.com/index.html")
        with self.assertRaises(cd.TimeoutException), contextlib.redirect_stdout(io.StringIO()):
            cd.clear_interstitials(self.driver, lambda: cd.find_window(self.driver, cd.is_pm),
                                   2, "PM window")


if __name__ == "__main__":
    unittest.main()
