"""RankLand preflight exercised by the parent inside VMware Firefox ESR.

This module never creates a WebDriver, launches a browser, edits a Firefox
profile, writes page storage, or sends an OJ submission. It uses a supplied
Selenium driver and changes only uniquely named qoj-preflight local VP runs.

Phase 1: run_rankland_probe(driver, output_dir, fixture_url=optional_root_url)
Phase 2: quit/restart Firefox with the same dedicated profile, then call
         resume_rankland_probe(driver, result['restart_manifest']).

Only the fixture mode replaces network responses; the renderer bundle remains
byte-identical to upstream. All synthetic verdict delivery goes through the
real application's problem/result/time controls and Record submission button.
"""

from __future__ import annotations

import json
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit


LIVE_CONTEST_KEY = "icpc2025nanjing"
FIXTURE_CONTEST_KEY = "qoj-preflight-fixture"
RUN_PREFIX = "qoj-preflight-"
TWO_HOURS_MS = 120 * 60 * 1000


class ProbeFailure(RuntimeError):
    pass


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _wait(driver, predicate, description, timeout=45):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as exc:
            last = f"{type(exc).__name__}: {str(exc)[:300]}"
        time.sleep(0.2)
    try:
        body = driver.execute_script("return document.body.innerText.slice(0, 1800)")
    except Exception:
        body = "unavailable"
    raise ProbeFailure(f"Timed out: {description}; last={last}; body={body}")


def _assert_isolated_profile(driver, allow_unmarked_profile=False):
    profile = str(driver.capabilities.get("moz:profile", ""))
    if not profile:
        raise ProbeFailure("Expected a Firefox driver exposing moz:profile")
    if not allow_unmarked_profile and not any(
        marker in profile.lower() for marker in ("preflight", "rankland-probe", "qoj-vp")
    ):
        raise ProbeFailure(
            "Use a dedicated Firefox profile with 'preflight' in its path. "
            "If Selenium generated a temporary profile, the parent may explicitly "
            "pass allow_unmarked_profile=True after verifying its isolation."
        )
    return profile


def _validate_base(base_url, fixture=False):
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ProbeFailure("Expected an HTTP(S) RankLand base URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ProbeFailure("Base URL must not contain credentials, query or fragment")
    if parts.path not in ("", "/"):
        raise ProbeFailure("RankLand's router requires fixture/app at the origin root /")
    if not fixture and parts.hostname != "vp.xcpc.link":
        raise ProbeFailure("Live probing is restricted to vp.xcpc.link")
    if parts.hostname in ("qoj.ac", "contest.ucup.ac", "codeforces.com"):
        raise ProbeFailure("This harness never navigates to an OJ submission site")
    return base_url.rstrip("/") + "/"


def _run_url(base, contest, run, team, play=True):
    if not run.startswith(RUN_PREFIX):
        raise ProbeFailure("Unsafe run identifier")
    return base + "?" + urlencode({
        "contest": contest, "run": run, "rule": "ICPC", "speed": "1",
        "from": "120", "feed": "0", "play": "1" if play else "0",
        "team": team, "organization": "Synthetic preflight only",
    })


def _state(driver, run, required=True):
    if not run.startswith(RUN_PREFIX):
        raise ProbeFailure("Refusing storage access outside the preflight namespace")
    rows = driver.execute_script("""
      const run = arguments[0];
      return Object.keys(localStorage)
        .filter(k => k.startsWith('RanklandVP2:') && k.includes(':' + run + ':'))
        .map(k => ({key: k, value: JSON.parse(localStorage.getItem(k))}));
    """, run)
    if not rows and not required:
        return None
    if len(rows) != 1:
        raise ProbeFailure(f"Expected one isolated state for {run}, got {len(rows)}")
    return rows[0]


def _wait_board(driver, team, timeout=45):
    _wait(driver, lambda: driver.execute_script("""
      return !!document.querySelector('[data-id="vp-ranklist-content"]') &&
        !!document.querySelector('select[aria-label="题目"]') &&
        [...document.querySelectorAll('.srk-user-name-text')]
          .some(e => e.textContent.trim() === arguments[0]);
    """, team), f"upstream VP board and own row {team}", timeout)


def _own_row(driver, team):
    return driver.execute_script("""
      const name = [...document.querySelectorAll('.srk-user-name-text')]
        .find(e => e.textContent.trim() === arguments[0]);
      if (!name) return null;
      const row = name.closest('tr'), user = name.closest('td');
      if (!row || !user) return null;
      const cells = [...row.cells], index = cells.indexOf(user);
      return {
        text: row.innerText,
        cells: cells.map(c => ({text: c.innerText, className: c.className})),
        score: cells[index + 1] ? cells[index + 1].textContent.trim() : null,
        penaltyMinutes: cells[index + 2] ? cells[index + 2].textContent.trim() : null,
        problemCells: cells.slice(index + 3).map(c => ({text: c.innerText,
          className: c.className, html: c.innerHTML.slice(0, 1600)}))
      };
    """, team)


def _dismiss_settings_intro(driver, timeout=10):
    """Acknowledge only the known upstream first-use dialog through its OK UI.

    The board can render before the mounted hook/teleported modal becomes
    visible. Waiting for the site's own read flag plus a quiet disappearance
    handles that race without removing DOM, editing Vue, or writing storage.
    """
    from selenium.common.exceptions import (
        ElementClickInterceptedException, StaleElementReferenceException,
    )
    from selenium.webdriver.common.by import By

    deadline = time.monotonic() + timeout
    quiet_since = None
    clicked = False
    latest_flag = None
    while time.monotonic() < deadline:
        wrappers = []
        for element in driver.find_elements(
            By.CSS_SELECTOR, ".srk-ranklist-settings-intro-wrap"
        ):
            try:
                if element.is_displayed():
                    wrappers.append(element)
            except StaleElementReferenceException:
                pass
        latest_flag = driver.execute_script(
            "return localStorage.getItem('StyledRanklistSettingsIntroRead');"
        )
        if wrappers:
            quiet_since = None
            if not clicked:
                for wrapper in wrappers:
                    try:
                        buttons = wrapper.find_elements(
                            By.XPATH, ".//button[normalize-space()='OK']"
                        )
                        button = next((b for b in buttons if b.is_displayed() and b.is_enabled()), None)
                        if not button:
                            continue
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", button
                        )
                        button.click()
                        clicked = True
                        events = getattr(driver, "_qoj_rankland_intro_events", [])
                        events.append({"action": "clicked_original_settings_intro_ok",
                                       "url": driver.current_url,
                                       "observed_at_ms": int(time.time() * 1000)})
                        driver._qoj_rankland_intro_events = events
                        break
                    except (ElementClickInterceptedException, StaleElementReferenceException):
                        # These failures occur before a successful click dispatch.
                        # Retry only the idempotent acknowledgement, never a verdict.
                        continue
        elif latest_flag == "true":
            quiet_since = quiet_since or time.monotonic()
            if time.monotonic() - quiet_since >= 0.25:
                return {"clicked": clicked, "read_flag": latest_flag}
        else:
            # The mounted hook may still be about to open the first-use dialog.
            quiet_since = None
        time.sleep(0.1)
    raise ProbeFailure(
        "The original settings introduction did not finish closing through its "
        f"OK button; clicked={clicked}, read_flag={latest_flag!r}"
    )


def _click_text(driver, text):
    from selenium.common.exceptions import ElementClickInterceptedException
    from selenium.webdriver.common.by import By
    for attempt in range(2):
        _dismiss_settings_intro(driver)
        button = _wait(driver, lambda: next((e for e in driver.find_elements(
            By.XPATH, f"//button[normalize-space()={json.dumps(text, ensure_ascii=False)}]"
        ) if e.is_displayed() and e.is_enabled()), None), f"enabled button {text}", 12)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
        try:
            button.click()
            return
        except ElementClickInterceptedException:
            # Intercepted means the target received no click. A successful
            # non-idempotent record click is never repeated here.
            if attempt:
                raise


def _snapshot(driver, output, label, run, team):
    fixture = driver.execute_script("return window.__qojPreflightFixture || null")
    value = {
        "url": driver.current_url, "state": _state(driver, run),
        "own_row": _own_row(driver, team), "fixture": fixture,
        "captured_at_ms": int(time.time() * 1000),
    }
    _write_json(Path(output) / f"rankland-{label}.json", value)
    try:
        driver.save_screenshot(str(Path(output) / f"rankland-{label}.png"))
    except Exception as exc:
        value["screenshot_error"] = type(exc).__name__
    return value


def _new_tab(driver, url):
    driver.switch_to.new_window("tab")
    handle = driver.current_window_handle
    driver.get(url)
    return handle


def _record(checks, name, passed, evidence=None):
    checks.append({"name": name, "passed": bool(passed), "evidence": evidence})
    if not passed:
        raise ProbeFailure(f"Check failed: {name}")


def deliver_synthetic_result(driver, run, team, source, receipt_path):
    """A test-only form adapter with local receipt dedup, not exactly-once.

    Source IDs must be synthetic. Existing matching records without a local
    receipt produce an ambiguous result instead of being blindly appended.
    No storage writes or Vue internals are used to perform the delivery.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    if not str(source.get("source_id", "")).startswith(RUN_PREFIX):
        raise ProbeFailure("Only synthetic preflight observations are accepted")
    _dismiss_settings_intro(driver)
    time_ms = int(source["timeMs"])
    if time_ms % 60000:
        raise ProbeFailure("The original site's past-time form is only minute precise")
    expected = {"problemIndex": int(source["problemIndex"]),
                "timeMs": time_ms, "result": source["result"]}
    before = _state(driver, run)
    manual_before = before["value"]["manual"]
    path = Path(receipt_path)
    ledger = json.loads(path.read_text()) if path.exists() else {"version": 1, "receipts": {}}
    old = ledger["receipts"].get(source["source_id"])
    if old:
        if old["run"] != run or old["record"] != expected:
            raise ProbeFailure("Synthetic source ID was reused with a different target/payload")
        if sum(item == expected for item in manual_before) == 1:
            row = _own_row(driver, team)
            if not row or row["score"] != old["own_row_score"]:
                raise ProbeFailure("Receipt exists but the visible target acknowledgement changed")
            return {"status": "deduplicated_from_local_receipt", "record": expected,
                    "manual_count": len(manual_before), "own_row": row,
                    "exactly_once_guaranteed": False}
        return {"status": "ambiguous_receipt_target_mismatch", "exactly_once_guaranteed": False}
    if expected in manual_before:
        return {"status": "ambiguous_matching_target_without_source_id",
                "exactly_once_guaranteed": False}
    if not before["value"].get("running"):
        raise ProbeFailure("The original record form requires a running replay")
    if not 0 <= time_ms <= before["value"]["elapsed"]:
        raise ProbeFailure("Synthetic submission time is outside the current replay")
    Select(driver.find_element(By.CSS_SELECTOR, 'select[aria-label="题目"]')).select_by_value(
        str(expected["problemIndex"]))
    Select(driver.find_element(By.CSS_SELECTOR, 'select[aria-label="结果"]')).select_by_value(
        expected["result"])
    for label, value in (("提交时间（时）", time_ms // 3600000),
                         ("提交时间（分）", time_ms // 60000 % 60)):
        element = driver.find_element(By.CSS_SELECTOR, f'input[aria-label="{label}"]')
        element.clear()
        element.send_keys(str(value))
    _click_text(driver, "记录提交")
    after = _wait(driver, lambda: (lambda current: current if
        len(current["value"]["manual"]) == len(manual_before) + 1 and
        current["value"]["manual"][-1] == expected else None)(_state(driver, run)),
        "recorded manual verdict persisted by the real form", 12)
    row = _wait(driver, lambda: (lambda current: current if current and
        current["score"] == "1" else None)(_own_row(driver, team)),
        "the real rendered own row acknowledges one accepted problem", 12)
    receipt = {"run": run, "record": expected, "storage_key": after["key"],
               "manual_count": len(after["value"]["manual"]),
               "own_row_score": row["score"], "observed_at_ms": int(time.time() * 1000)}
    ledger["receipts"][source["source_id"]] = receipt
    _write_json(path, ledger)
    return {"status": "applied_via_original_form_and_observed", "record": expected,
            "manual_count": receipt["manual_count"], "own_row": row,
            "exactly_once_guaranteed": False}


def run_rankland_probe(driver, output_dir, *, base_url="https://vp.xcpc.link/",
                       contest_key=None, fixture_url=None, timeout=45,
                       allow_unmarked_profile=False):
    """Run phase 1; leave run A paused for a true Firefox restart by the parent.

    With fixture_url supplied, a failed real-network load is recorded explicitly
    before the same checks run with the unmodified upstream renderer and a local
    synthetic feed. This never upgrades fixture evidence into a live-site pass.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    profile = _assert_isolated_profile(driver, allow_unmarked_profile)
    live_base = _validate_base(base_url)
    if fixture_url:
        fixture_url = _validate_base(fixture_url, fixture=True)
    trial = RUN_PREFIX + uuid.uuid4().hex[:16]
    run_a, run_b = trial + "-a", trial + "-b"
    team_a, team_b = trial + "-team-a", trial + "-team-b"
    control = driver.current_window_handle
    result = {"schema": "qoj-rankland-preflight-v1", "trial_id": trial,
              "profile": profile,
              "firefox_process_id": driver.capabilities.get("moz:processID"),
              "mode": "live", "checks": [], "network_attempts": [],
              "notes": ["Synthetic local replay only; no QOJ/CF submission.",
                        "Past-time initialization uses the original from=120 parameter.",
                        "No localStorage.setItem or Vue-state mutation is used."]}
    handle_a = None
    active_base, active_contest = live_base, contest_key or LIVE_CONTEST_KEY
    try:
        url_a = _run_url(active_base, active_contest, run_a, team_a)
        try:
            handle_a = _new_tab(driver, url_a)
            _wait_board(driver, team_a, timeout)
            result["network_attempts"].append({"kind": "live", "url": url_a, "loaded": True})
        except Exception as exc:
            attempt = {"kind": "live", "url": url_a, "loaded": False,
                       "error": f"{type(exc).__name__}: {str(exc)[:2400]}"}
            result["network_attempts"].append(attempt)
            try:
                driver.save_screenshot(str(output / "rankland-live-load-failure.png"))
            except Exception:
                pass
            if not fixture_url:
                raise
            if handle_a and handle_a in driver.window_handles:
                driver.close()
                driver.switch_to.window(control)
            result["mode"] = "synthetic_feed_upstream_renderer"
            active_base, active_contest = fixture_url, FIXTURE_CONTEST_KEY
            url_a = _run_url(active_base, active_contest, run_a, team_a)
            handle_a = _new_tab(driver, url_a)
            _wait_board(driver, team_a, timeout)
            marker = driver.execute_script("return window.__qojPreflightFixture || null")
            _record(result["checks"], "fixture_origin_explicitly_marked", bool(marker), marker)
            result["network_attempts"].append({"kind": "fixture", "url": url_a, "loaded": True})

        initial = _snapshot(driver, output, "initial-two-hours", run_a, team_a)
        _record(result["checks"], "two_hours_initialized_by_original_query",
                initial["state"]["value"]["elapsed"] >= TWO_HOURS_MS and
                initial["state"]["value"]["ownName"] == team_a and
                initial["state"]["value"]["manual"] == [], initial["state"])

        url_b = _run_url(active_base, active_contest, run_b, team_b, play=False)
        handle_b = _new_tab(driver, url_b)
        _wait_board(driver, team_b, timeout)
        state_b, state_a = _state(driver, run_b), _state(driver, run_a)
        _record(result["checks"], "run_parameter_separates_same_contest_configuration",
                state_a["key"] != state_b["key"] and
                state_a["value"]["ownName"] == team_a and
                state_b["value"]["ownName"] == team_b,
                {"run_a": state_a, "run_b": state_b})
        driver.close()
        driver.switch_to.window(handle_a)

        source = {"source_id": trial + "-synthetic-accepted-1", "problemIndex": 0,
                  "timeMs": TWO_HOURS_MS, "result": "AC",
                  "provenance": "synthetic already-judged observation; not a real OJ submission"}
        receipt_path = output / "rankland-delivery-receipts.json"
        first = deliver_synthetic_result(driver, run_a, team_a, source, receipt_path)
        _record(result["checks"], "synthetic_verdict_uses_original_form_and_visible_own_row",
                first["status"] == "applied_via_original_form_and_observed" and
                first["manual_count"] == 1 and first["own_row"]["score"] == "1", first)
        duplicate = deliver_synthetic_result(driver, run_a, team_a, source, receipt_path)
        _record(result["checks"], "same_source_id_not_redelivered_with_local_receipt",
                duplicate["status"] == "deduplicated_from_local_receipt" and
                duplicate["manual_count"] == 1, duplicate)
        _record(result["checks"], "other_run_remains_unmodified",
                _state(driver, run_b)["value"]["manual"] == [], _state(driver, run_b))
        _snapshot(driver, output, "after-synthetic-form-submit", run_a, team_a)

        before_close = _state(driver, run_a)
        old_handle = driver.current_window_handle
        driver.close()
        driver.switch_to.window(control)
        _record(result["checks"], "original_vp_tab_was_closed",
                old_handle not in driver.window_handles, {"closed_handle": old_handle})
        handle_a = _new_tab(driver, url_a)
        _wait_board(driver, team_a, timeout)
        after_reopen = _snapshot(driver, output, "restored-new-tab", run_a, team_a)
        restored = after_reopen["state"]
        _record(result["checks"], "accurate_url_recovers_progress_and_manual_in_new_tab",
                restored["key"] == before_close["key"] and
                restored["value"]["elapsed"] >= before_close["value"]["elapsed"] and
                restored["value"]["manual"] == before_close["value"]["manual"] and
                after_reopen["own_row"]["score"] == "1", after_reopen)

        _click_text(driver, "暂停")
        paused = _wait(driver, lambda: (lambda current: current if not
            current["value"]["running"] else None)(_state(driver, run_a)),
            "original pause control persisted running=false", 12)
        _snapshot(driver, output, "restart-checkpoint-paused", run_a, team_a)
        manifest = {"schema": result["schema"], "trial_id": trial,
                    "mode": result["mode"], "profile_before_restart": profile,
                    "firefox_process_id_before_restart": result["firefox_process_id"],
                    "resume_url": url_a, "other_run_url": url_b,
                    "run_a": run_a, "run_b": run_b, "team_a": team_a, "team_b": team_b,
                    "expected_state_a": paused, "expected_state_b": _state(driver, run_b),
                    "source": source, "receipt_path": str(receipt_path),
                    "output_dir": str(output),
                    "restart_instruction": "Parent must quit Firefox and relaunch it with the same dedicated profile, then call resume_rankland_probe."}
        result["restart_manifest"] = _write_json(output / "rankland-restart-manifest.json", manifest)
        result["status"] = "phase1_passed_restart_pending"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
        try:
            driver.save_screenshot(str(output / "rankland-phase1-failure.png"))
        except Exception:
            pass
    result["report_path"] = str(output / "rankland-phase1-result.json")
    result["ui_events"] = getattr(driver, "_qoj_rankland_intro_events", [])
    _write_json(result["report_path"], result)
    return result


def resume_rankland_probe(driver, manifest_path, output_dir=None, *, timeout=45,
                          allow_unmarked_profile=False):
    """Phase 2: parent must supply a newly launched Firefox using the same profile."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not str(manifest.get("trial_id", "")).startswith(RUN_PREFIX):
        raise ProbeFailure("Manifest is not an isolated preflight trial")
    profile = _assert_isolated_profile(driver, allow_unmarked_profile)
    output = Path(output_dir or manifest["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    result = {"schema": manifest["schema"], "trial_id": manifest["trial_id"],
              "mode": manifest["mode"], "phase": "after_parent_firefox_restart",
              "profile_before_restart": manifest["profile_before_restart"],
              "profile_after_restart": profile,
              "firefox_process_id_before_restart": manifest.get("firefox_process_id_before_restart"),
              "firefox_process_id_after_restart": driver.capabilities.get("moz:processID"),
              "checks": []}
    try:
        old_pid = result["firefox_process_id_before_restart"]
        new_pid = result["firefox_process_id_after_restart"]
        _record(result["checks"], "firefox_process_really_changed",
                old_pid is not None and new_pid is not None and old_pid != new_pid,
                {"before_pid": old_pid, "after_pid": new_pid,
                 "note": "A refresh/new tab in the old driver does not satisfy a Firefox restart."})
        _new_tab(driver, manifest["resume_url"])
        _wait_board(driver, manifest["team_a"], timeout)
        snapshot = _snapshot(driver, output, "after-firefox-restart",
                             manifest["run_a"], manifest["team_a"])
        before, after = manifest["expected_state_a"], snapshot["state"]
        _record(result["checks"], "same_profile_restart_restores_exact_paused_checkpoint",
                before["key"] == after["key"] and
                after["value"]["ownName"] == manifest["team_a"] and
                after["value"]["manual"] == before["value"]["manual"] and
                abs(after["value"]["elapsed"] - before["value"]["elapsed"]) < 1000 and
                after["value"]["elapsed"] >= TWO_HOURS_MS and
                not after["value"]["running"] and snapshot["own_row"]["score"] == "1", snapshot)
        other = _state(driver, manifest["run_b"])
        _record(result["checks"], "second_run_still_separate_after_restart",
                other["key"] == manifest["expected_state_b"]["key"] and
                other["value"]["ownName"] == manifest["team_b"] and
                other["value"]["manual"] == [], other)
        duplicate = deliver_synthetic_result(driver, manifest["run_a"], manifest["team_a"],
                                             manifest["source"], manifest["receipt_path"])
        _record(result["checks"], "delivery_receipt_dedup_survives_browser_restart",
                duplicate["status"] == "deduplicated_from_local_receipt" and
                duplicate["manual_count"] == 1, duplicate)
        result["status"] = "passed"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
        try:
            driver.save_screenshot(str(output / "rankland-phase2-failure.png"))
        except Exception:
            pass
    result["report_path"] = str(output / "rankland-phase2-result.json")
    result["ui_events"] = getattr(driver, "_qoj_rankland_intro_events", [])
    _write_json(result["report_path"], result)
    return result
