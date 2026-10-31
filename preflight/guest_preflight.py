#!/usr/bin/env python3
"""Bounded, isolated VMware Firefox preflight; never submits an OJ solution.

Run this file from its unpacked project directory. All browser/native state is
under this project's state directory. The two loopback servers exist only for
this harness invocation and are stopped before it exits.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import shlex
import sys
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Keep dependencies and the unmodified upstream library inside the test bundle.
sys.path.insert(0, str(ROOT / "vendor" / "qoj-submitter"))
sys.path.insert(0, str(ROOT / "vendor_py"))

HOST_NAME = "org.littledrinks.qoj_preflight"
OWNER = "QOJ VP isolated preflight owned native host v1"
TWO_HOURS_MS = 2 * 60 * 60 * 1000


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def process_exit(pid, timeout=12):
    """Observe /proc disappearance; a closed native port alone is insufficient."""
    require(isinstance(pid, int) and pid > 0, "No valid process ID was returned")
    started = time.monotonic()
    proc = Path("/proc") / str(pid)
    initial = proc.exists()
    while proc.exists() and time.monotonic() - started < timeout:
        time.sleep(0.1)
    evidence = {"pid": pid, "presentWhenChecked": initial,
                "procEntryAbsent": not proc.exists(),
                "waitSeconds": round(time.monotonic() - started, 3)}
    require(evidence["procEntryAbsent"], f"Process {pid} still has a /proc entry after {timeout}s")
    return evidence


class StaticFixtureServer:
    """Separate RankLand origin, rooted only at the checked-in fixture files."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.server = None
        self.thread = None
        self.requests = []
        self.lock = threading.Lock()

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        require(self.directory.is_dir(), "RankLand fixture directory is missing")
        owner = self

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def log_request(self, code="-", size="-"):
                # Never record request headers or bodies.
                with owner.lock:
                    owner.requests.append({"method": self.command,
                                           "path": self.path.split("?", 1)[0], "status": code})

            def do_POST(self):
                self.send_error(405, "Read-only preflight fixture")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(self.directory)))
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="rankland-preflight-http", daemon=True)
        self.thread.start()
        return self

    def shutdown(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)


class Harness:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.results = self.root / "results"
        self.state = self.root / "state"
        self.profile = self.state / "firefox-profile"
        self.driver = None
        self.extension_url = None
        self.extension_handle = None
        self.manifest_path = Path.home() / ".mozilla" / "native-messaging-hosts" / (HOST_NAME + ".json")
        self.manifest_before = None
        self.manifest_installed = False
        self.helper_observations = []
        self.summary = {"schema": "qoj-guest-preflight-v1", "startedAt": utc_now(),
                        "root": str(self.root), "isolatedProfile": str(self.profile),
                        "realSubmissionEnabled": False, "checks": [], "cleanup": {}}
        self.phase = "initializing"
        self.results.mkdir(parents=True, exist_ok=True)

    def flush(self):
        atomic_json(self.results / "status.json", {
            "schema": self.summary["schema"], "phase": self.phase, "updatedAt": utc_now(),
            "checks": self.summary["checks"], "cleanup": self.summary["cleanup"],
            "summaryPath": str(self.results / "summary.json")})
        atomic_json(self.results / "summary.json", self.summary)

    def step(self, name, function, *, optional=False):
        self.phase = name
        self.flush()
        check = {"name": name, "startedAt": utc_now(), "optional": optional}
        try:
            result = function()
            check.update(status="passed", evidence=result)
            return result
        except Exception as exc:
            check.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)[:2500]})
            if name.startswith(("qoj_fixture_samples_", "qoj_fixture_form_")) and getattr(self, "diagnostic_fixture_origin", None):
                try:
                    diagnostic = self.extension_diagnostics(self.diagnostic_fixture_origin)
                    path = self.results / (name + "-extension-diagnostics.json")
                    atomic_json(path, diagnostic)
                    check["extensionDiagnostics"] = {"path": str(path), "result": diagnostic}
                except Exception as diagnostic_error:
                    check["extensionDiagnostics"] = {"status": "unavailable", "error": {
                        "type": type(diagnostic_error).__name__, "message": str(diagnostic_error)[:800]}}
            return None
        finally:
            check["finishedAt"] = utc_now()
            self.summary["checks"].append(check)
            self.flush()

    def setup(self):
        require((self.root / "native_host.py").is_file(), "native_host.py missing")
        require((self.root / "vendor_py").is_dir(), "vendor_py missing")
        require((self.root / "tools" / "geckodriver").is_file(), "Bundled geckodriver missing")
        self.profile.mkdir(parents=True, exist_ok=True)
        (self.state / "native").mkdir(parents=True, exist_ok=True)
        launcher = self.state / "native-launcher.sh"
        expected_manifest = {"name": HOST_NAME, "description": OWNER, "path": str(launcher),
                             "type": "stdio", "allowed_extensions": ["qoj-vp-preflight@littledrinks.local"]}
        if self.manifest_path.exists():
            self.manifest_before = self.manifest_path.read_bytes()
            existing = json.loads(self.manifest_before)
            require(existing == expected_manifest, "Refusing to replace a native host manifest not owned by this test")
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text("#!/bin/sh\n" + "\n".join([
            "export QOJ_PREFLIGHT_QOJ_PATH=" + shlex.quote(str(self.root / "vendor" / "qoj-submitter")),
            "export QOJ_PREFLIGHT_STATE_DIR=" + shlex.quote(str(self.state / "native")),
            "export PYTHONPATH=" + shlex.quote(str(self.root / "vendor_py") + ":" + str(self.root / "vendor" / "qoj-submitter")),
            "exec /usr/bin/python3 " + shlex.quote(str(self.root / "native_host.py")), ""]), encoding="utf-8")
        launcher.chmod(0o700)
        atomic_json(self.manifest_path, expected_manifest)
        self.manifest_installed = True
        addon = self.state / "preflight-addon.xpi"
        with zipfile.ZipFile(addon, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((self.root / "extension").rglob("*")):
                if path.is_file():
                    archive.write(path, str(path.relative_to(self.root / "extension")))
        self.addon = addon
        return {"manifest": str(self.manifest_path), "launcher": str(launcher),
                "addon": str(addon), "profile": str(self.profile), "profileCopied": False}

    def start_browser(self):
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        options = Options()
        options.binary_location = "/usr/bin/firefox-esr"
        options.add_argument("-headless")
        # Options.profile would create a copy and invalidate restart persistence.
        options.add_argument("-profile")
        options.add_argument(str(self.profile))
        options.set_preference("browser.shell.checkDefaultBrowser", False)
        options.set_preference("browser.startup.page", 0)
        options.set_preference("browser.startup.homepage", "about:blank")
        options.set_preference("browser.sessionstore.resume_from_crash", False)
        log_path = self.results / "geckodriver.log"
        service = Service(executable_path=str(self.root / "tools" / "geckodriver"), log_output=str(log_path))
        self.driver = webdriver.Firefox(service=service, options=options)
        try:
            self.driver.set_page_load_timeout(40)
            self.driver.set_script_timeout(105)
            actual = Path(self.driver.capabilities.get("moz:profile", "")).resolve()
            require(actual == self.profile.resolve(), "Firefox did not use the dedicated persistent profile")
            pid = self.driver.capabilities.get("moz:processID")
            require(isinstance(pid, int), "Firefox did not expose its process ID")
        except Exception:
            # Never use a browser whose isolation/persistence was not verified.
            self.quit_browser()
            raise
        return {"profile": str(actual), "browserPid": pid,
                "browserVersion": self.driver.capabilities.get("browserVersion"),
                "geckodriverVersion": self.driver.capabilities.get("moz:geckodriverVersion"),
                "profileCopied": False, "headless": self.driver.capabilities.get("moz:headless")}

    def install_extension(self):
        require(self.driver is not None, "Firefox is unavailable")
        install_mode = os.environ.get("QOJ_PREFLIGHT_ADDON_INSTALL", "path")
        if install_mode == "path":
            extension_id = self.driver.execute("INSTALL_ADDON", {"path": str(self.addon), "temporary": True})["value"]
        else:
            require(install_mode == "base64", "Unknown isolated addon install mode")
            extension_id = self.driver.install_addon(str(self.addon), temporary=True)
        deadline = time.monotonic() + 20
        last_error = None
        while time.monotonic() < deadline:
            for handle in self.driver.window_handles:
                try:
                    self.driver.switch_to.window(handle)
                    url = self.driver.current_url
                    if url.startswith("moz-extension://") and url.split("?", 1)[0].endswith("/test.html"):
                        if self.driver.execute_script("return !!window.preflight && typeof window.preflight.run === 'function'"):
                            self.extension_url, self.extension_handle = url, handle
                            return {"extensionId": extension_id, "url": url, "temporary": True, "installMode": install_mode}
                except Exception as exc:
                    last_error = type(exc).__name__
            time.sleep(0.15)
        raise RuntimeError("The extension's onInstalled test.html did not become ready: " + str(last_error))

    def focus_extension(self):
        require(self.driver is not None and self.extension_handle in self.driver.window_handles,
                "The extension test tab is unavailable")
        self.driver.switch_to.window(self.extension_handle)

    def extension_diagnostics(self, fixture_origin, *, probe_injection=False, probe_fetch=False):
        """Read only extension metadata/ready state; do not create or alter tabs.

        Firefox tab IDs are obtained from browser.tabs, never Selenium handles.
        The extension API returns no page body, source text, cookies or CSRF.
        """
        self.focus_extension()
        response = self.driver.execute_async_script("""
            const done = arguments[arguments.length - 1];
            const fixtureOrigin = arguments[0], probeInjection = arguments[1], probeFetch = arguments[2];
            (async () => {
              if (typeof window.preflight?.diagnostics !== 'function') {
                return {ok:false, error:{code:'diagnostics_api_unavailable'}};
              }
              // Some WebDriver realms do not expose extension APIs directly.
              // The background API can also resolve an existing tab by origin.
              const tabs = typeof browser !== 'undefined' && browser.tabs
                ? await browser.tabs.query({}) : [];
              const tab = tabs.find(candidate => {
                try { return new URL(candidate.url).origin === fixtureOrigin; }
                catch (_) { return false; }
              });
              const args = {fixtureOrigin, probeInjection, probeFetch};
              if (tab) args.httpTabId = tab.id;
              return {ok:true, result:await window.preflight.diagnostics(args)};
            })().then(done, error => done({ok:false, error:{code:error.name || 'diagnostics_failed'}}));
        """, fixture_origin, bool(probe_injection), bool(probe_fetch))
        require(response and response.get("ok"), "Extension diagnostics unavailable: " + str((response or {}).get("error")))
        diagnostic = response["result"]
        require(diagnostic.get("schema") == "qoj-extension-diag-v1", "Unknown extension diagnostics schema")
        # Keep only the agreed metadata fields, even if a future API expands.
        safe = {key: diagnostic[key] for key in (
            "schema", "extension", "resources", "permissions", "targetTab",
            "readyBefore", "injectionProbes", "readyAfter") if key in diagnostic}

        def ensure_metadata(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    require(not any(fragment in key.lower() for fragment in (
                        "cookie", "token", "password", "authorization", "rawhtml", "bodybase64", "sourcetext")),
                        "Diagnostics unexpectedly contains a forbidden field")
                    ensure_metadata(child)
            elif isinstance(value, list):
                for child in value:
                    ensure_metadata(child)
        ensure_metadata(safe)
        expected_resources = {}
        for filename in ("http-content.js", "background.js", "test.js", "manifest.json"):
            path = self.root / "extension" / filename
            if path.is_file():
                payload = path.read_bytes()
                expected_resources[filename] = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        return {"browserDiagnostics": safe, "localExpectedResources": expected_resources,
                "probeInjectionRequested": bool(probe_injection)}

    def call(self, method, args=None):
        self.focus_extension()
        response = self.driver.execute_async_script("""
            const done = arguments[arguments.length - 1];
            window.preflight.run(arguments[0], arguments[1]).then(
                result => done({ok: true, result}),
                error => done({ok: false, error: {name: error.name, message: error.message}}));
        """, method, args or {})
        require(response and response.get("ok"), "Native task failed: " + str((response or {}).get("error")))
        result = response["result"]
        pid = result.get("helperPid")
        observation = process_exit(pid)
        self.helper_observations.append(observation)
        self.summary["helperProcessExitObservations"] = self.helper_observations
        require(result.get("nativePortClosed") is True, "Native port closure not reported")
        return result

    def hello(self):
        result = self.call("hello", {"pageUrl": self.extension_url})
        require(result.get("qojPathConfigured"), "QOJ library path is not configured")
        require(Path(result["stateDir"]).resolve() == (self.state / "native").resolve(), "Unexpected native state directory")
        return result

    def inspect(self, session_id, started_at):
        result = self.call("inspect_session", {"sessionId": session_id})
        require(result.get("startAt") == started_at, "Original session start was not restored")
        require(result.get("elapsedMs", 0) >= TWO_HOURS_MS, "Elapsed time restarted from zero")
        require(result.get("effectiveState") == "running", "Unexpected recovered session state")
        return result

    def assert_browser_transport(self, result):
        transports = result.get("browserTransport", [])
        require(bool(transports), "No browser transport was observed")
        require(all(item.get("transport") == "content-script-same-origin" for item in transports),
                "QOJ HTTP did not use content-script-same-origin")

    def sample(self, fixture_origin, label, expected):
        result = self.call("qoj_contest_and_sample", {"contestId": "3387", "problemLabel": label,
                                                    "fixtureOrigin": fixture_origin, "includeZip": True})
        self.assert_browser_transport(result)
        require(result.get("source") == "fixture", "Fixture provenance is missing")
        mapping = {p["label"]: {"id": str(p["id"]), "name": p["name"]} for p in result["problems"]}
        require(mapping == expected["problems"], "Contest problem mapping differs from expected fixtures")
        sample = result["samples"]
        payload = base64.b64decode(sample.pop("zipBase64"), validate=True)
        artifact = self.results / f"samples-{label}.zip"
        artifact.write_bytes(payload)
        sample["savedZipPath"] = str(artifact)
        require(hashlib.sha256(payload).hexdigest() == sample["zipSha256"], "Returned ZIP hash mismatch")
        expected_names = sorted(name for name in expected["samplePaths"] if name.startswith(f"samples-{label}/"))
        require(sorted(item["name"] for item in sample["files"]) == expected_names, "Sample file set differs")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            require(sorted(archive.namelist()) == expected_names, "Saved ZIP members differ from expected")
            for item in sample["files"]:
                data = archive.read(item["name"])
                require(len(data) == item["bytes"] and hashlib.sha256(data).hexdigest() == item["sha256"], "Sample integrity mismatch")
        if label == "B":
            require(bool(sample["warnings"]) and bool(sample["extraFiles"]), "Special attachment was not identified")
        return result

    def form(self, fixture_origin, label, expected):
        result = self.call("qoj_problem_form", {"contestId": "3387", "problemId": expected["problems"][label]["id"],
                                               "fixtureOrigin": fixture_origin})
        self.assert_browser_transport(result)
        require(result["languages"] == expected["languages"], "Form language parsing differs")
        require(result.get("csrfPresent"), "Fixture CSRF was not found")
        require(bool(result.get("pdfCandidates")) if label == "A" else not result.get("pdfCandidates"),
                "PDF discovery did not distinguish PDF attachment A from HTML-only B")
        return result

    def real_qoj(self):
        """No login is imported. A failed GET is an observation, not fixture proof."""
        try:
            result = self.call("qoj_contest_and_sample", {"contestId": "3387", "problemLabel": "A", "includeZip": False})
            self.assert_browser_transport(result)
            require(result.get("source") == "real-qoj-browser", "Unexpected real-QOJ provenance")
            return {"outcome": "real_read_only_get_passed", "authenticatedProfile": False, "result": result}
        except Exception as exc:
            error = str(exc)
            lower = error.lower()
            outcome = "login_required_or_access_denied" if any(s in lower for s in ("login", "403", "forbidden", "session expired")) else "network_or_page_parse_failed"
            return {"outcome": outcome, "authenticatedProfile": False,
                    "error": {"type": type(exc).__name__, "message": error[:1800]},
                    "limitation": "An isolated unauthenticated browser failure does not invalidate local-fixture round trips."}

    def pdf_fixture(self, origin, expected):
        self.driver.switch_to.new_window("tab")
        handle = self.driver.current_window_handle
        try:
            self.driver.get(origin + "/contest/3387/problem/15419")
            fetched = self.driver.execute_async_script("""
                const done = arguments[arguments.length-1];
                fetch('/fixture-statements/A.pdf', {method:'GET'}).then(async response => {
                  const bytes = new Uint8Array(await response.arrayBuffer());
                  let s=''; for (const byte of bytes) s += String.fromCharCode(byte);
                  done({status:response.status, contentType:response.headers.get('content-type'),
                        base64:btoa(s), transport:'browser-page-same-origin-fetch'});
                }).catch(e => done({error:e.name+': '+e.message}));
            """)
            require(fetched.get("status") == 200, "PDF fixture fetch failed")
            data = base64.b64decode(fetched.pop("base64"), validate=True)
            artifact = self.results / "fixture-statement-A.downloaded.pdf"
            artifact.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            require(data.startswith(b"%PDF-") and b"%%EOF" in data[-100:], "Downloaded PDF is incomplete")
            require(digest == expected["assets"]["statement-A.pdf"]["sha256"], "PDF fixture hash mismatch")
            return {**fetched, "artifact": str(artifact), "bytes": len(data), "sha256": digest,
                    "synthetic": True, "realQojPdfAvailabilityProven": False}
        finally:
            if handle in self.driver.window_handles:
                self.driver.close()
            self.focus_extension()

    def print_html(self, origin):
        from selenium.webdriver.common.print_page_options import PrintOptions
        self.driver.switch_to.new_window("tab")
        handle = self.driver.current_window_handle
        try:
            self.driver.get(origin + "/contest/3387/problem/15420")
            require(not self.driver.execute_script("return !!document.querySelector('a[href$=\".pdf\"],iframe[src$=\".pdf\"]')"), "B fixture should be HTML-only")
            options = PrintOptions()
            options.background = True
            options.page_width, options.page_height = 21, 29.7
            data = base64.b64decode(self.driver.print_page(options), validate=True)
            require(data.startswith(b"%PDF-") and b"%%EOF" in data[-100:], "Firefox print_page did not produce a complete PDF")
            artifact = self.results / "fixture-statement-B.printed.pdf"
            artifact.write_bytes(data)
            return {"artifact": str(artifact), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    "method": "WebDriver print_page", "synthetic": True,
                    "limitation": "Synthetic HTML printing does not verify real QOJ mathematics, images, or pagination."}
        finally:
            if handle in self.driver.window_handles:
                self.driver.close()
            self.focus_extension()

    def reopen_extension(self, session_id, started_at):
        self.focus_extension()
        closed = self.extension_handle
        url = self.extension_url
        self.driver.close()
        require(closed not in self.driver.window_handles, "Original extension tab did not close")
        self.driver.switch_to.window(self.driver.window_handles[0])
        self.driver.switch_to.new_window("tab")
        self.driver.get(url)
        self.extension_handle = self.driver.current_window_handle
        self.wait_preflight_page()
        return {"originalTabClosed": True, "restored": self.inspect(session_id, started_at)}

    def wait_preflight_page(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.driver.execute_script("return !!window.preflight && typeof window.preflight.run === 'function'"):
                return
            time.sleep(0.1)
        raise RuntimeError("Extension test API was unavailable after reopening")

    def quit_browser(self):
        if self.driver is None:
            return {"alreadyStopped": True}
        driver, self.driver = self.driver, None
        pid = driver.capabilities.get("moz:processID")
        try:
            driver.quit()
        finally:
            self.extension_handle = None
        return process_exit(pid, timeout=20)

    def cleanup_manifest(self):
        if not self.manifest_installed:
            return {"modified": False}
        current = json.loads(self.manifest_path.read_text(encoding="utf-8")) if self.manifest_path.exists() else None
        require(current is None or (current.get("description") == OWNER and current.get("path") == str(self.state / "native-launcher.sh")),
                "Manifest changed during test; refusing cleanup overwrite")
        if self.manifest_before is None:
            self.manifest_path.unlink(missing_ok=True)
            return {"removedOwnedManifest": True, "persistentStateRetained": str(self.state)}
        self.manifest_path.write_bytes(self.manifest_before)
        return {"restoredPreviousOwnedManifest": True, "persistentStateRetained": str(self.state)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Unpacked preflight project root")
    args = parser.parse_args()
    h = Harness(args.root)
    qoj_server = rankland_server = None
    try:
        setup = h.step("isolated_native_host_and_addon_setup", h.setup)
        if setup is None:
            return 1
        from fixture_server import FixtureServer
        from rankland_probe import run_rankland_probe, resume_rankland_probe
        expected = json.loads((h.root / "fixtures" / "expected.json").read_text(encoding="utf-8"))
        qoj_server = FixtureServer().start()
        h.diagnostic_fixture_origin = qoj_server.origin
        rankland_server = StaticFixtureServer(h.root / "rankland-fixtures").start()
        h.summary["temporaryServers"] = {"qoj": qoj_server.origin, "rankland": rankland_server.origin}
        first = h.step("firefox_first_launch", h.start_browser)
        addon = h.step("temporary_addon_install", h.install_extension) if first else None
        created = None
        session_id, start_at = "qoj-preflight-" + uuid.uuid4().hex, int(time.time() * 1000) - TWO_HOURS_MS
        if addon:
            h.step("native_hello_and_process_exit", h.hello)
            created = h.step("native_create_session_two_hours_elapsed", lambda: h.call("create_session", {
                "sessionId": session_id, "contestId": "3387", "title": "Isolated synthetic preflight",
                "startAt": start_at, "durationMs": 5 * 60 * 60 * 1000}))
            if created:
                h.step("native_session_inspect", lambda: h.inspect(session_id, start_at))
            for label in ("A", "B"):
                h.step("qoj_fixture_samples_" + label, lambda label=label: h.sample(qoj_server.origin, label, expected))
                h.step("qoj_fixture_form_" + label, lambda label=label: h.form(qoj_server.origin, label, expected))
            h.step("qoj_live_read_only_get_separate_observation", h.real_qoj, optional=True)
            h.step("pdf_fixture_browser_fetch_and_download", lambda: h.pdf_fixture(qoj_server.origin, expected))
            h.step("html_only_statement_firefox_print_page", lambda: h.print_html(qoj_server.origin))
            if created:
                h.step("native_session_restores_after_tab_close", lambda: h.reopen_extension(session_id, start_at))

        rankland = None
        if h.driver:
            rankland = h.step("rankland_phase1_real_network_then_fixture", lambda: run_rankland_probe(
                h.driver, h.results / "rankland", fixture_url=rankland_server.origin))
            if rankland and rankland.get("status") != "phase1_passed_restart_pending":
                h.step("rankland_phase1_assertions", lambda: require(False, "RankLand phase 1 reported failure; see its report"))
            stopped = h.step("firefox_shutdown_before_restart", h.quit_browser)
            second = h.step("firefox_second_launch_same_persistent_profile", h.start_browser) if stopped else None
            if second:
                h.step("firefox_restart_uses_new_pid", lambda: {
                    "beforePid": first["browserPid"], "afterPid": second["browserPid"],
                    "changed": require(first["browserPid"] != second["browserPid"], "Firefox PID did not change") is None})
                reinstall = h.step("temporary_addon_reinstall_after_restart", h.install_extension)
                if reinstall and created:
                    h.step("native_session_restores_after_firefox_restart", lambda: h.inspect(session_id, start_at))
                if rankland and rankland.get("restart_manifest"):
                    resumed = h.step("rankland_phase2_after_real_firefox_restart", lambda: resume_rankland_probe(
                        h.driver, rankland["restart_manifest"], h.results / "rankland"))
                    if resumed and resumed.get("status") != "passed":
                        h.step("rankland_phase2_assertions", lambda: require(False, "RankLand phase 2 reported failure; see its report"))
    except Exception as exc:
        h.summary["fatalError"] = {"type": type(exc).__name__, "message": str(exc)[:2500]}
    finally:
        h.phase = "cleanup"
        h.flush()
        for name, fn in (("firefox", h.quit_browser),
                         ("qojHttpServer", lambda: qoj_server.shutdown() if qoj_server else None),
                         ("ranklandHttpServer", lambda: rankland_server.shutdown() if rankland_server else None),
                         ("nativeManifest", h.cleanup_manifest)):
            try:
                h.summary["cleanup"][name] = {"status": "passed", "evidence": fn()}
            except Exception as exc:
                h.summary["cleanup"][name] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:1000]}"}
            h.flush()
        if qoj_server:
            records = qoj_server.requests
            atomic_json(h.results / "qoj-fixture-http-requests.json", records)
            h.summary["qojFixtureRequests"] = {"count": len(records), "postCount": sum(r["method"] == "POST" for r in records),
                                                "rejectedPostCount": qoj_server.rejected_post_count, "serverStopped": not qoj_server.running}
            h.step("qoj_fixture_no_post_and_http_server_stopped", lambda: (
                require(h.summary["qojFixtureRequests"]["postCount"] == 0, "Unexpected POST reached QOJ fixture"),
                require(not qoj_server.running, "QOJ fixture server still running"), h.summary["qojFixtureRequests"])[-1])
        if rankland_server:
            atomic_json(h.results / "rankland-fixture-http-requests.json", rankland_server.requests)
            h.summary["ranklandFixtureRequests"] = {"count": len(rankland_server.requests),
                                                    "postCount": sum(r["method"] == "POST" for r in rankland_server.requests),
                                                    "serverStopped": not rankland_server.running}
            h.step("rankland_fixture_no_post_and_http_server_stopped", lambda: (
                require(h.summary["ranklandFixtureRequests"]["postCount"] == 0, "Unexpected POST reached RankLand fixture"),
                require(not rankland_server.running, "RankLand fixture server still running"), h.summary["ranklandFixtureRequests"])[-1])
        required_failures = [c["name"] for c in h.summary["checks"] if c["status"] != "passed" and not c["optional"]]
        cleanup_failures = [n for n, v in h.summary["cleanup"].items() if v["status"] != "passed"]
        h.summary.update(finishedAt=utc_now(), requiredFailures=required_failures,
                         status="failed" if required_failures or cleanup_failures or h.summary.get("fatalError") else "passed")
        h.phase = "finished"
        h.flush()
        print(json.dumps({"status": h.summary["status"], "summary": str(h.results / "summary.json"),
                          "requiredFailures": required_failures}, ensure_ascii=False))
    return 0 if h.summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
