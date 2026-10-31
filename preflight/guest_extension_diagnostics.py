#!/usr/bin/env python3
"""Run the isolated extension metadata/ready diagnostic, then cleanly stop.

This script performs local GETs only and does not submit to an OJ, read cookies,
or return page/token/source bodies. Default diagnostics do not inject code.
The optional --probe-injection enables the extension's explicit injection probe.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from guest_preflight import ROOT, Harness, atomic_json, require, utc_now
from fixture_server import FixtureServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, help="Defaults to ROOT/results/extension-diagnostics")
    parser.add_argument("--probe-injection", action="store_true", help="Explicitly enable the extension's read-only injection probe")
    parser.add_argument("--probe-fetch", action="store_true", help="GET one loopback fixture through the content script")
    args = parser.parse_args()
    h = Harness(args.root)
    # Keep the full preflight's summary/status intact. The same isolated profile
    # reproduces its installed permission/content-script state, never user state.
    h.results = (args.output or (h.root / "results" / "extension-diagnostics")).resolve()
    h.results.mkdir(parents=True, exist_ok=True)
    h.summary.update(schema="qoj-extension-diagnostics-run-v1", realNetworkRequestsEnabled=False,
                     diagnosticCollectionOnly=True)
    fixture = None
    try:
        setup = h.step("isolated_native_host_and_addon_setup", h.setup)
        if setup:
            fixture = FixtureServer().start()
            h.summary["fixtureOrigin"] = fixture.origin
            launched = h.step("firefox_persistent_isolated_profile", h.start_browser)
            installed = h.step("temporary_addon_install", h.install_extension) if launched else None
            if installed:
                def open_fixture_tab():
                    h.driver.switch_to.new_window("tab")
                    h.driver.get(fixture.origin + "/contest/3387")
                    ready = h.driver.execute_script("return {origin:location.origin,ready:document.readyState}")
                    require(ready["origin"] == fixture.origin, "Fixture tab has the wrong origin")
                    require(urlsplit(h.driver.current_url).hostname == "127.0.0.1", "Diagnostics navigated beyond loopback")
                    h.focus_extension()
                    return ready

                opened = h.step("fixture_same_origin_tab_open", open_fixture_tab)
                if opened:
                    def diagnose():
                        result = h.extension_diagnostics(fixture.origin, probe_injection=args.probe_injection, probe_fetch=args.probe_fetch)
                        atomic_json(h.results / "extension-diagnostics.json", result)
                        return result
                    h.step("extension_resources_permissions_tab_and_ready", diagnose)
                # The test page auto-starts hello. Explicit hello also provides
                # a PID so the standard harness can prove a native task exits.
                # This remains independent of the browser-only diagnostic above.
                h.step("optional_native_helper_exit_observation", h.hello, optional=True)
    except Exception as exc:
        h.summary["fatalError"] = {"type": type(exc).__name__, "message": str(exc)[:1500]}
    finally:
        h.phase = "cleanup"
        h.flush()
        for name, callback in (
                ("firefox", h.quit_browser),
                ("qojHttpServer", lambda: fixture.shutdown() if fixture else None),
                ("nativeManifest", h.cleanup_manifest)):
            try:
                h.summary["cleanup"][name] = {"status": "passed", "evidence": callback()}
            except Exception as exc:
                h.summary["cleanup"][name] = {"status": "failed", "error": {
                    "type": type(exc).__name__, "message": str(exc)[:1000]}}
            h.flush()
        if fixture:
            records = fixture.requests
            atomic_json(h.results / "fixture-http-requests.json", records)

            def verify_server():
                require(not fixture.running, "Fixture HTTP server is still running")
                post_count = sum(record["method"] == "POST" for record in records)
                require(post_count == 0, "Unexpected POST reached the fixture")
                return {"postCount": post_count, "requestCount": len(records), "serverStopped": True}
            h.step("fixture_no_post_and_server_stopped", verify_server)
        failed = [c["name"] for c in h.summary["checks"] if c["status"] != "passed" and not c["optional"]]
        cleanup_failed = any(check["status"] != "passed" for check in h.summary["cleanup"].values())
        h.summary.update(finishedAt=utc_now(), requiredFailures=failed,
                         status="failed" if failed or cleanup_failed or h.summary.get("fatalError") else "passed")
        h.phase = "finished"
        h.flush()
        print(json.dumps({"status": h.summary["status"], "summary": str(h.results / "summary.json")}, ensure_ascii=False))
    return 0 if h.summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
