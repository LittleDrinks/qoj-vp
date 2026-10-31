#!/usr/bin/env python3
"""Run only inside the guest; launch a separate headless Firefox profile."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "vendor_py"), str(ROOT / "vendor/qoj-submitter")]
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)


def write(name, value):
    path = OUT / name
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


result = {"stage": "starting", "pid": os.getpid(), "startedAt": time.time()}
write("smoke-status.json", result)
driver = service = None
try:
    import pycurl
    import requests
    import bs4
    import selenium
    from qoj_submitter import client, samples
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service

    result["dependencies"] = {
        "selenium": selenium.__version__, "requests": requests.__version__,
        "bs4": bs4.__version__, "pycurl": pycurl.version,
        "qojClientSha256": hashlib.sha256(Path(client.__file__).read_bytes()).hexdigest(),
        "qojSamplesSha256": hashlib.sha256(Path(samples.__file__).read_bytes()).hexdigest(),
    }
    result["stage"] = "starting_firefox"
    write("smoke-status.json", result)
    profile = ROOT / "state/smoke-firefox-profile"
    profile.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.binary_location = "/usr/bin/firefox-esr"
    options.add_argument("-headless")
    options.add_argument("-profile")
    options.add_argument(str(profile))
    options.set_preference("browser.shell.checkDefaultBrowser", False)
    options.set_preference("browser.startup.page", 0)
    options.set_preference("browser.startup.homepage", "about:blank")
    options.set_preference("datareporting.policy.dataSubmissionEnabled", False)
    os.environ["MOZ_HEADLESS"] = "1"
    os.environ["MOZ_NO_REMOTE"] = "1"
    service = Service(str(ROOT / "tools/geckodriver"), log_output=str(OUT / "geckodriver-smoke.log"))
    driver = webdriver.Firefox(options=options, service=service)
    driver.set_page_load_timeout(25)
    driver.set_window_size(1280, 900)
    driver.get("data:text/html,<title>QOJ VM preflight</title><h1 id='probe'>Firefox inside VMware</h1>")
    actual = driver.execute_script("return document.getElementById('probe').textContent")
    assert actual == "Firefox inside VMware", actual
    assert Path(driver.capabilities["moz:profile"]).resolve() == profile.resolve()
    driver.save_screenshot(str(OUT / "firefox-headless-smoke.png"))
    result["firefox"] = {
        key: driver.capabilities.get(key) for key in
        ["browserName", "browserVersion", "platformName", "moz:profile", "moz:processID", "moz:headless"]
    }
    result["stage"] = "passed"
except Exception as exc:
    result.update(stage="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
finally:
    if driver is not None:
        try:
            driver.quit()
            result["driverQuit"] = True
        except Exception as exc:
            result["driverQuitError"] = type(exc).__name__
    elif service is not None:
        service.stop()
    result["finishedAt"] = time.time()
    write("smoke-status.json", result)
    write("smoke-result.json", result)

print(json.dumps({"stage": result["stage"], "result": str(OUT / "smoke-result.json")}))
raise SystemExit(0 if result["stage"] == "passed" else 1)
