#!/usr/bin/env python3
"""Bounded post-reboot health check; independent of unfinished feature tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results" / "reboot-status.json"
sys.path[:0] = [str(ROOT / "vendor_py"), str(ROOT / "vendor/qoj-submitter")]


def save(result):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix(".writing")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)


def main():
    report = {"startedAt": time.time(), "purpose": "post-reboot-readiness-only",
              "featureTestsResumed": False, "checks": {}, "cleanup": {}}
    save(report)

    def check(name, fn):
        try:
            report["checks"][name] = {"status": "passed", "evidence": fn()}
        except Exception as exc:
            report["checks"][name] = {"status": "failed", "errorType": type(exc).__name__}
        save(report)

    def system():
        assert os.getuid() != 0
        free = shutil.disk_usage(ROOT).free
        assert free > 1024 ** 3
        return {"uid": os.getuid(), "kernel": os.uname().release,
                "diskFreeBytes": free, "uptimeSeconds": float(Path('/proc/uptime').read_text().split()[0])}
    check("guest_system", system)

    def files():
        critical = ["native_core.py", "native_host.py", "guest_preflight.py", "rankland_probe.py",
                    "extension/manifest.json", "extension/http-content.js",
                    "vendor/qoj-submitter/qoj_submitter/client.py",
                    "vendor/qoj-submitter/qoj_submitter/samples.py", "tools/geckodriver"]
        result = {}
        for rel in critical:
            path = ROOT / rel
            assert path.is_file()
            result[rel] = {"bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for rel in ("state/firefox-profile", "state/smoke-firefox-profile"):
            assert (ROOT / rel).is_dir()
        return {"files": result, "persistentProfilesPresent": True}
    check("persistent_test_files", files)

    def database():
        path = ROOT / "state/native/preflight.sqlite3"
        assert path.is_file()
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            integrity = db.execute("PRAGMA quick_check").fetchall()
            assert integrity == [("ok",)]
            count = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            assert count > 0
        return {"quickCheck": "ok", "savedSessionCount": count}
    check("persistent_session_database", database)

    def processes():
        leftovers = []
        needles = ("/geckodriver", "/native_host.py", "/guest_preflight.py",
                   "/guest_extension_diagnostics.py", "/guest_smoke.py")
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit() or int(proc.name) == os.getpid():
                continue
            try:
                data = (proc / "cmdline").read_bytes().replace(b'\0', b' ').decode(errors='replace')
                if any(needle in data for needle in needles):
                    leftovers.append(int(proc.name))
            except (OSError, ProcessLookupError):
                continue
        assert not leftovers
        manifest = Path.home() / '.mozilla/native-messaging-hosts/org.littledrinks.qoj_preflight.json'
        assert not manifest.exists()
        return {"leftoverTestProcessCount": 0, "testNativeManifestAbsent": True}
    check("previous_test_cleanup", processes)

    def network():
        result = {}
        for name, url in (
            ("rankland", 'https://vp.xcpc.link/'),
            ("ranklandAPI", 'https://rl.algoux.cn/api/v2/public/contests/icpc2025nanjing'),
        ):
            request = urllib.request.Request(url, headers={'User-Agent': 'QOJ-VP-Readiness-Check/1'})
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read(2 * 1024 * 1024)
                assert response.status == 200 and body
                result[name] = {"status": response.status, "bytes": len(body)}
        return result
    check("rankland_network", network)

    def browser():
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        import requests
        import bs4
        import pycurl
        from qoj_submitter import client, samples

        options = Options()
        options.binary_location = '/usr/bin/firefox-esr'
        options.add_argument('-headless')
        profile = ROOT / 'state/reboot-smoke-firefox-profile'
        profile.mkdir(parents=True, exist_ok=True)
        options.add_argument('-profile')
        options.add_argument(str(profile))
        options.set_preference('browser.shell.checkDefaultBrowser', False)
        driver = None
        service = Service(str(ROOT / 'tools/geckodriver'), log_output=str(ROOT / 'results/reboot-geckodriver.log'))
        pid = None
        try:
            driver = webdriver.Firefox(options=options, service=service)
            driver.set_page_load_timeout(15)
            driver.set_script_timeout(15)
            pid = driver.capabilities['moz:processID']
            assert Path(driver.capabilities['moz:profile']).resolve() == profile.resolve()
            assert driver.capabilities.get('moz:headless')
            driver.get('data:text/html,<title>Post-reboot readiness</title><p id="probe">ready</p>')
            assert driver.execute_script("return document.getElementById('probe').textContent") == 'ready'
            return {"version": driver.capabilities['browserVersion'], "headless": True,
                    "pid": pid, "javascript": "passed", "qojDependenciesImported": True}
        finally:
            if driver:
                driver.quit()
            else:
                service.stop()
            deadline = time.monotonic() + 10
            while pid and Path(f'/proc/{pid}').exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            gone = pid is None or not Path(f'/proc/{pid}').exists()
            report['cleanup']['firefoxProcessGone'] = gone
            assert gone
    check("firefox_headless_smoke", browser)
    report['finishedAt'] = time.time()
    report['status'] = 'passed' if all(x['status'] == 'passed' for x in report['checks'].values()) else 'failed'
    save(report)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
