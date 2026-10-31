"""Exercise the product UI through a caller-owned isolated Firefox WebDriver.

No driver is created or stopped here. A native ``hello`` must report fixture
routing before this module permits the single source submission. All business
actions use visible forms/buttons; qojVpUi.getState is observation only.
DOMjudge reference capture logs into the official public team demo and never
chooses a source file or submits a solution there.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
import traceback
import uuid
from urllib.parse import urljoin, urlsplit


TWO_HOURS_MS = 120 * 60 * 1000
PINNED_DOMJUDGE_VERSION = "9.0.1"
DEMO_PAGE = "https://www.domjudge.org/demo"


class UiProbeFailure(RuntimeError):
    pass


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return str(path.resolve())


def _require(condition, message):
    if not condition:
        raise UiProbeFailure(message)


def _wait(driver, predicate, description, timeout=45):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:
            # Do not dump source, page HTML, input values, cookies or tokens.
            latest = type(exc).__name__
        time.sleep(0.15)
    raise UiProbeFailure(f"Timed out waiting for {description}; last exception={latest}")


def _profile(driver):
    value = str(driver.capabilities.get("moz:profile", ""))
    _require(bool(value) and any(marker in value.lower() for marker in ("preflight", "qoj-vp", "qojvp")),
             "This probe requires a dedicated Firefox preflight profile")
    return value


def _state(driver):
    return driver.execute_script("return window.qojVpUi?.getState() || null;")


def _ui_ready(driver):
    return _wait(driver, lambda: (value if value and value.get("connected") else None)
                 if (value := _state(driver)) else None, "connected product UI")


def _workbench(driver):
    if driver.current_url.startswith("moz-extension://") and urlsplit(driver.current_url).path == "/ui.html":
        return driver.current_window_handle
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        if driver.current_url.startswith("moz-extension://") and urlsplit(driver.current_url).path == "/ui.html":
            return handle
    raise UiProbeFailure("No installed product ui.html tab is open")


def _click(driver, element_or_id):
    from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
    from selenium.webdriver.common.by import By
    for attempt in range(3):
        element = (driver.find_element(By.ID, element_or_id)
                   if isinstance(element_or_id, str) else element_or_id)
        _wait(driver, lambda: element.is_displayed() and element.is_enabled(), "enabled clickable control", timeout=15)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        try:
            element.click()
            return
        except (ElementClickInterceptedException, StaleElementReferenceException):
            # These failures occur before the target receives the click.
            # Never retry an accepted Submit or its confirmation.
            if attempt == 2:
                raise
            time.sleep(0.2)


def _fill(driver, element_id, value):
    from selenium.webdriver.common.by import By
    control = driver.find_element(By.ID, element_id)
    control.clear()
    control.send_keys(str(value))
    return control


def _modal_visible(driver, modal_id):
    """Wait for Bootstrap's visible dialog to finish its opening transition.

    ``is_displayed`` becomes true before Bootstrap can accept ``hide()``.
    Observe public DOM/CSS animation state, including the dialog's transform
    and backdrop fade; do not inspect/modify Bootstrap private state or hide
    elements from the harness. A brief quiet observation also covers reduced
    motion, where Bootstrap's transition-end callback runs on a later tick.
    """
    quiet_since = None

    def interactive():
        nonlocal quiet_since
        settled = driver.execute_script("""
          const modal=document.getElementById(arguments[0]);
          if(!modal || !modal.classList.contains('show') ||
             modal.getAttribute('aria-modal')!=='true' ||
             !modal.getClientRects().length) return false;
          const surfaces=[modal,...document.querySelectorAll('.modal-backdrop')];
          return surfaces.every(surface=>surface.getAnimations({subtree:true})
            .every(animation=>!animation.pending && animation.playState!=='running'));
        """, modal_id)
        if not settled:
            quiet_since = None
            return False
        quiet_since = quiet_since or time.monotonic()
        return time.monotonic() - quiet_since >= 0.1

    return _wait(driver, interactive, modal_id + " transition-complete interaction")


def _screenshot(driver, output, label, report):
    path = Path(output) / ("ui-" + label + ".png")
    _require(driver.save_screenshot(str(path)), "Firefox did not save the screenshot")
    report.setdefault("screenshots", {})[label] = str(path.resolve())
    return str(path.resolve())


def _record(report, name, evidence=None):
    report.setdefault("checks", []).append({"name": name, "passed": True, "evidence": evidence})


def _alert(driver):
    from selenium.common.exceptions import NoAlertPresentException
    try:
        return driver.switch_to.alert
    except NoAlertPresentException:
        return None


def _native_fixture_hello(driver):
    observed = driver.execute_async_script("""
      const done=arguments[arguments.length-1];
      browser.runtime.sendMessage({type:'vp.task',method:'hello',args:{}}).then(
        r=>done({ok:r?.ok===true,fixture:r?.result?.fixture===true,
          nativePortClosed:r?.result?.nativePortClosed===true}),
        e=>done({ok:false,errorType:e.name}));
    """)
    _require(observed.get("ok") and observed.get("fixture"),
             "Refusing source submission: installed native helper did not confirm fixture routing")
    return observed


def _fill_backdated_start(driver):
    # Standard form input assignment is independent of Firefox's localized
    # datetime picker. It dispatches the same input/change events as typing.
    return driver.execute_script("""
      const d=new Date(Date.now()-arguments[0]);
      const pad=n=>String(n).padStart(2,'0');
      const value=d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+
        'T'+pad(d.getHours())+':'+pad(d.getMinutes());
      const input=document.getElementById('start-input');
      input.value=value;
      input.dispatchEvent(new Event('input',{bubbles:true}));
      input.dispatchEvent(new Event('change',{bubbles:true}));
      return {value:input.value,epochMs:new Date(input.value).getTime(),nowMs:Date.now()};
    """, TWO_HOURS_MS)


def _provider_ids(value):
    return sorted(str(item["id"]) for item in value.get("submissions", []) if item.get("id"))


def _operation_ids(value):
    return sorted(item["operationId"] for item in value.get("submissions", []) if item.get("operationId"))


def _capture_failure(driver, report, output):
    try:
        report["lastUiState"] = _state(driver)
    except Exception:
        pass
    try:
        _screenshot(driver, output, "failure", report)
    except Exception:
        pass


def run_ui_probe(driver, output_dir, source_path, rankland_url, *, get_post_count=None):
    """Create a two-hour fixture VP; cancel then accept a real UI submission.

    Return ``phase1_passed_restart_pending`` plus restart_manifest on success.
    get_post_count is an optional parent-owned fixture counter callable. When
    supplied, assert zero POSTs after cancellation and exactly one on success.
    Source must be an existing synthetic A.cpp. No source body is recorded.
    The active tab on return remains the product workbench whenever available.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "qoj-vp-ui-phase1-v1", "startedAt": time.time(),
              "checks": [], "screenshots": {}, "syntheticQojFixture": True,
              "realQojSubmission": False, "pendingObserved": False}
    workbench_handle = None
    try:
        profile = _profile(driver)
        workbench_handle = _workbench(driver)
        initial = _ui_ready(driver)
        _record(report, "isolated_ui_connected", {"profile": profile, "fixtureHello": _native_fixture_hello(driver)})
        source = Path(source_path).resolve()
        _require(source.is_file() and source.name.lower() == "a.cpp", "Use a pre-created synthetic A.cpp source")
        _require(0 < source.stat().st_size <= 512 * 1024, "Source exceeds the product's bounds")
        report["sourceFile"] = {"name": source.name, "bytes": source.stat().st_size,
                                "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        if get_post_count is not None:
            _require(get_post_count() == 0, "UI acceptance requires a fresh fixture with zero prior POSTs")
        _require(urlsplit(rankland_url).scheme == "https" and urlsplit(rankland_url).hostname == "vp.xcpc.link",
                 "Use the actual RankLand origin and a dedicated test run")

        _click(driver, "new-session")
        _modal_visible(driver, "session-modal")
        _fill(driver, "contest-input", "3387")
        _click(driver, "load-contest")
        _wait(driver, lambda: driver.find_element(By.ID, "prepare-session").is_enabled(), "loaded fixture contest")
        preview = driver.find_element(By.ID, "contest-preview").text
        _require("csj-test" in preview, "The UI did not read the synthetic fixture account")
        _fill(driver, "session-title", "Synthetic UI preflight " + uuid.uuid4().hex[:8])
        _fill(driver, "rankland-input", rankland_url)
        _fill(driver, "duration-input", "300")
        backdated = _fill_backdated_start(driver)
        _require(backdated["nowMs"] - backdated["epochMs"] >= TWO_HOURS_MS, "Two-hour form input was not applied")
        _screenshot(driver, output, "prepare", report)
        _click(driver, "prepare-session")
        ready = _wait(driver, lambda: value if (value := _state(driver)) and value.get("session")
                      and value["session"]["sessionId"] != (initial.get("session") or {}).get("sessionId")
                      and value.get("contest", {}).get("problemCount") == 2 else None,
                      "new fixture session and two-problem contest", timeout=90)
        _wait(driver, lambda: not driver.find_element(By.ID, "session-modal").is_displayed(), "session modal dismissal")
        session = ready["session"]
        session_id = session["sessionId"]
        _require(str(session["contestId"]) == "3387" and session["account"] == "csj-test", "Wrong new-session account or contest")
        _require(session["startAt"] == backdated["epochMs"], "Saved start anchor differs from the filled form")
        _require(session.get("elapsedMs", 0) >= TWO_HOURS_MS, "Two-hour elapsed time was reset")
        _require(driver.find_element(By.ID, "timeleft").text not in ("not started", "no contest"), "Contest timer did not start")
        _record(report, "create_two_hour_session_via_visible_form", {"sessionId": session_id,
                "startAt": session["startAt"], "elapsedMs": session["elapsedMs"], "account": session["account"]})
        _screenshot(driver, output, "home-initial", report)

        _click(driver, "nav-problems")
        _wait(driver, lambda: driver.find_element(By.ID, "problems-view").is_displayed(), "Problemset route")
        cards = driver.find_elements(By.CSS_SELECTOR, "#problems-list .card")
        _require(len(cards) == 2, "Problemset did not render both fixture problems")
        card_evidence = []
        for card in cards:
            label = card.find_element(By.CSS_SELECTOR, ".problem-badge").text
            _require(card.find_element(By.CSS_SELECTOR, "[data-submit-problem]").is_enabled(), "Per-problem Submit is disabled")
            _require(card.find_element(By.CSS_SELECTOR, "[data-pdf-problem]").is_displayed(), "Per-problem PDF action missing")
            _require(card.find_element(By.CSS_SELECTOR, "[data-samples-problem]").is_displayed(), "Per-problem samples action missing")
            _require(card.find_element(By.CSS_SELECTOR, "a[href*='/contest/3387/problem/']").is_displayed(), "Original statement link missing")
            card_evidence.append({"label": label, "actions": ["Submit", "statement", "PDF", "samples"]})
        _record(report, "problemset_per_problem_actions", card_evidence)
        _screenshot(driver, output, "problemset", report)

        # Verify preselection by a real problem-card button, then close it.
        _click(driver, driver.find_element(By.CSS_SELECTOR, '[data-submit-problem="15420"]'))
        _modal_visible(driver, "submit-modal")
        _wait(driver, lambda: Select(driver.find_element(By.ID, "submit_problem_problem")).first_selected_option.get_attribute("value") == "15420", "problem B preselection")
        _click(driver, "submit-cancel")
        _wait(driver, lambda: not driver.find_element(By.ID, "submit-modal").is_displayed(), "B submit modal close")
        _record(report, "problemset_submit_preselects_B")

        _click(driver, "nav-home")
        _wait(driver, lambda: driver.find_element(By.ID, "home-view").is_displayed(), "Home route")
        _wait(driver, lambda: driver.find_element(By.ID, "refresh-status").text.startswith("更新于"), "initial history sync", timeout=90)
        _click(driver, "open-submit")
        _modal_visible(driver, "submit-modal")
        driver.find_element(By.ID, "submit_problem_code").send_keys(str(source))
        _wait(driver, lambda: driver.find_element(By.ID, "submit_problem_problem").get_attribute("value") == "15419", "A.cpp problem inference")
        _wait(driver, lambda: driver.find_element(By.ID, "submit_problem_language").get_attribute("value").lower().replace(" ", "") == "c++20", "A.cpp C++20 inference", timeout=90)
        _record(report, "file_infers_A_and_available_Cpp20")
        _screenshot(driver, output, "submit-inferred", report)
        before_cancel = _state(driver)
        _click(driver, "submit-send")
        prompt = _wait(driver, lambda: _alert(driver), "DOMjudge-style confirmation")
        _require("Main source file: " + source.name in prompt.text and "Make submission?" in prompt.text,
                 "Confirmation omitted the selected source or final question")
        report["confirmDialog"] = {"containsSource": True, "containsAccount": "csj-test" in prompt.text,
                                   "containsProblem": "Problem: A" in prompt.text, "containsLanguage": "C++20" in prompt.text}
        prompt.dismiss()
        # Allow the ordinary event handler to finish, without initiating any
        # API task or modifying UI state from this observer.
        _wait(driver, lambda: not _state(driver).get("submitting"), "cancel handler completion")
        time.sleep(0.4)
        after_cancel = _state(driver)
        _require(_provider_ids(before_cancel) == _provider_ids(after_cancel), "Cancel added a provider submission to UI history")
        _require(_operation_ids(before_cancel) == _operation_ids(after_cancel), "Cancel added a source-send intent to UI history")
        _require(driver.find_element(By.ID, "submit_problem_code").get_attribute("value").endswith(source.name), "Cancel lost the selected source")
        cancel_post_count = get_post_count() if get_post_count is not None else None
        if get_post_count is not None:
            _require(cancel_post_count == 0, "Dismissing the confirm dialog emitted a POST")
        _record(report, "dismiss_confirmation_adds_no_history", {"beforeIds": _provider_ids(before_cancel), "afterIds": _provider_ids(after_cancel),
                "newOperationCount": 0, "serverPostCount": cancel_post_count})
        report["historyCountAfterCancel"] = len(after_cancel["submissions"])

        before_operations = set(_operation_ids(after_cancel))
        before_ids = set(_provider_ids(after_cancel))
        _click(driver, "submit-send")
        prompt = _wait(driver, lambda: _alert(driver), "second explicit confirmation")
        prompt.accept()  # The only source-send authorization in this module.
        observations = []
        new_submission = None

        def observe_judgement():
            nonlocal new_submission
            value = _state(driver)
            if not value:
                return None
            candidates = [item for item in value.get("submissions", [])
                          if item.get("filename") == source.name and item.get("operationId")
                          and item["operationId"] not in before_operations]
            for item in candidates:
                signature = (item.get("state"), item.get("id"), item.get("verdict"), bool(item.get("pending")))
                if not observations or observations[-1]["signature"] != list(signature):
                    observations.append({"signature": list(signature), "observedAt": time.time()})
                if item.get("pending") or item.get("verdict") == "JUDGING":
                    if not report["pendingObserved"]:
                        report["pendingObserved"] = True
                        _screenshot(driver, output, "submission-pending", report)
                if item.get("state") == "confirmed" and item.get("verdict") == "CORRECT" and not item.get("pending"):
                    new_submission = item
                    return item
            return None

        _wait(driver, observe_judgement, "accepted fixture submission and CORRECT verdict", timeout=120)
        _require(new_submission and str(new_submission["id"]) not in before_ids, "No new confirmed provider receipt")
        _require(str(new_submission["problemId"]) == "15419" and new_submission["problemLabel"] == "A", "Receipt belongs to another problem")
        _require(new_submission.get("elapsedMs", 0) >= TWO_HOURS_MS, "Submission lost the session's two-hour offset")
        accepted_post_count = get_post_count() if get_post_count is not None else None
        if get_post_count is not None:
            _require(accepted_post_count == 1, "UI acceptance emitted more or fewer than one POST")
        _wait(driver, lambda: not driver.find_element(By.ID, "submit-modal").is_displayed(), "post-submit modal dismissal")
        _record(report, "accepted_source_receipt_and_final_verdict", {"submissionId": new_submission["id"],
                "operationId": new_submission["operationId"], "verdict": new_submission["verdict"],
                "elapsedMs": new_submission["elapsedMs"], "pendingObserved": report["pendingObserved"],
                "serverPostCount": accepted_post_count, "observations": observations})
        if not report["pendingObserved"]:
            report.setdefault("limitations", []).append("The UI reached CORRECT before the observer saw a pending frame; do not claim the pending rendering was exercised.")
        _screenshot(driver, output, "submission-correct", report)

        # A polling update must not replace a separately opened file selector.
        _click(driver, "open-submit")
        _modal_visible(driver, "submit-modal")
        driver.find_element(By.ID, "submit_problem_code").send_keys(str(source))
        _wait(driver, lambda: driver.find_element(By.ID, "submit_problem_language").get_attribute("value").lower().replace(" ", "") == "c++20", "second modal form ready")
        until = time.monotonic() + 6
        while time.monotonic() < until:
            _require(driver.find_element(By.ID, "submit_problem_code").get_attribute("value").endswith(source.name), "Background polling lost the selected file")
            time.sleep(0.3)
        _require(driver.find_element(By.ID, "submit_problem_problem").get_attribute("value") == "15419", "Polling reset selected problem")
        _require(driver.find_element(By.ID, "submit_problem_language").get_attribute("value").lower().replace(" ", "") == "c++20", "Polling reset selected language")
        _click(driver, "submit-cancel")
        _wait(driver, lambda: not driver.find_element(By.ID, "submit-modal").is_displayed(), "second file modal close")
        _record(report, "polling_preserves_open_file_problem_and_language", {"observedSeconds": 6})

        # Close/reopen the actual workbench tab. Keep the parent's other tabs.
        resume_url = driver.current_url
        old_handle = driver.current_window_handle
        if len(driver.window_handles) == 1:
            driver.switch_to.new_window("tab")
            driver.get("about:blank")
            driver.switch_to.window(old_handle)
        driver.close()
        _require(old_handle not in driver.window_handles, "Workbench tab did not close")
        driver.switch_to.window(driver.window_handles[0])
        driver.switch_to.new_window("tab")
        workbench_handle = driver.current_window_handle
        driver.get(resume_url)
        recovered = _wait(driver, lambda: value if (value := _state(driver)) and value.get("connected")
                          and (value.get("session") or {}).get("sessionId") == session_id
                          and any(str(item.get("id")) == str(new_submission["id"]) and item.get("verdict") == "CORRECT" for item in value.get("submissions", [])) else None,
                          "session and verdict after actual UI tab close/reopen", timeout=90)
        _require(recovered["session"]["startAt"] == session["startAt"], "Reopened workbench changed the start anchor")
        _require(recovered["session"]["ranklandUrl"] == session["ranklandUrl"], "Reopened workbench changed RankLand recovery URL")
        _require(recovered["session"].get("elapsedMs", 0) >= TWO_HOURS_MS, "Reopened workbench reset elapsed time")
        _record(report, "actual_workbench_tab_close_reopen", {"closedHandle": old_handle, "newHandle": workbench_handle})
        _screenshot(driver, output, "tab-restored", report)

        manifest = {"schema": "qoj-vp-ui-restart-v1", "createdAt": time.time(), "outputDir": str(output),
                    "profile": profile, "firefoxPid": driver.capabilities.get("moz:processID"),
                    "sessionId": session_id, "resumeUrl": resume_url, "ranklandUrl": session["ranklandUrl"],
                    "expectedStartAt": session["startAt"], "expectedSubmissionId": str(new_submission["id"]),
                    "expectedOperationId": new_submission["operationId"], "pendingObserved": report["pendingObserved"]}
        manifest_path = _write(output / "ui-restart-manifest.json", manifest)
        report.update(status="phase1_passed_restart_pending", sessionId=session_id, url=resume_url,
                      resumeUrl=resume_url, ranklandUrl=session["ranklandUrl"], expectedSubmissionId=str(new_submission["id"]),
                      twoHoursElapsed=True, state=recovered, restart_manifest=manifest_path)
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:1200]}", traceback=traceback.format_exc())
        _capture_failure(driver, report, output)
    finally:
        try:
            if workbench_handle in driver.window_handles:
                driver.switch_to.window(workbench_handle)
        except Exception:
            pass
        report["finishedAt"] = time.time()
        report["report_path"] = _write(output / "ui-phase1-result.json", report)
    return report


def run_unknown_ui_probe(driver, output_dir, source_path, rankland_url, *, get_post_count=None):
    """Exercise receipt uncertainty, UI duplicate prevention and explicit linking.

    The caller must install the ``unknown503`` loopback fixture: its only source
    POST is accepted as provider ID 1000001 but returns HTTP 503. A later read
    reveals the provider fact; the UI must retain the unknown intent until the
    user explicitly associates it through the existing reconciliation dialog.
    No business method is called directly here other than the read-only fixture
    hello guard. The restart manifest can be consumed by resume_ui_probe.
    """
    import base64
    from selenium.webdriver.common.by import By

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "qoj-vp-ui-unknown-phase1-v1", "scenario": "unknown503",
              "startedAt": time.time(), "checks": [], "screenshots": {},
              "syntheticQojFixture": True, "realQojSubmission": False,
              "unknownObserved": False, "reconciled": False, "pendingObserved": False}
    workbench_handle = None
    try:
        profile = _profile(driver)
        workbench_handle = _workbench(driver)
        initial = _ui_ready(driver)
        _record(report, "isolated_ui_connected", {"profile": profile, "fixtureHello": _native_fixture_hello(driver)})
        source = Path(source_path).resolve()
        _require(source.is_file() and source.name.lower() == "a.cpp", "Use a pre-created synthetic A.cpp source")
        source_bytes = source.read_bytes()
        _require(0 < len(source_bytes) <= 512 * 1024, "Source exceeds the product's bounds")
        report["sourceFile"] = {"name": source.name, "bytes": len(source_bytes),
                                "sha256": hashlib.sha256(source_bytes).hexdigest()}
        _require(urlsplit(rankland_url).scheme == "https" and urlsplit(rankland_url).hostname == "vp.xcpc.link",
                 "Use the actual RankLand origin and a dedicated test run")
        if get_post_count is not None:
            _require(get_post_count() == 0, "Unknown receipt acceptance requires a fresh zero-POST fixture")

        _click(driver, "new-session")
        _modal_visible(driver, "session-modal")
        _fill(driver, "contest-input", "3387")
        _click(driver, "load-contest")
        _wait(driver, lambda: driver.find_element(By.ID, "prepare-session").is_enabled(), "unknown fixture contest loaded")
        _require("csj-test" in driver.find_element(By.ID, "contest-preview").text,
                 "The UI did not read the synthetic fixture account")
        _fill(driver, "session-title", "Synthetic unknown receipt " + uuid.uuid4().hex[:8])
        _fill(driver, "rankland-input", rankland_url)
        _fill(driver, "duration-input", "300")
        backdated = _fill_backdated_start(driver)
        _click(driver, "prepare-session")
        ready = _wait(driver, lambda: value if (value := _state(driver)) and value.get("session")
                      and value["session"]["sessionId"] != (initial.get("session") or {}).get("sessionId")
                      and (value.get("contest") or {}).get("problemCount") == 2 else None,
                      "unknown-receipt two-hour session", timeout=90)
        _wait(driver, lambda: not driver.find_element(By.ID, "session-modal").is_displayed(), "unknown session modal dismissal")
        session = ready["session"]
        session_id = session["sessionId"]
        _require(session["startAt"] == backdated["epochMs"] and session.get("elapsedMs", 0) >= TWO_HOURS_MS,
                 "Unknown test did not retain its two-hour anchor")
        _require(str(session["contestId"]) == "3387" and session["account"] == "csj-test", "Wrong unknown-session account or contest")
        _record(report, "create_two_hour_session_via_visible_form", {"sessionId": session_id,
                "startAt": session["startAt"], "elapsedMs": session["elapsedMs"], "account": session["account"]})
        _click(driver, "nav-home")
        _wait(driver, lambda: driver.find_element(By.ID, "refresh-status").text.startswith("更新于"), "unknown initial history sync", timeout=90)
        initial_operations = set(_operation_ids(_state(driver)))
        _click(driver, "open-submit")
        _modal_visible(driver, "submit-modal")
        driver.find_element(By.ID, "submit_problem_code").send_keys(str(source))
        _wait(driver, lambda: driver.find_element(By.ID, "submit_problem_problem").get_attribute("value") == "15419", "unknown A.cpp inference")
        _wait(driver, lambda: driver.find_element(By.ID, "submit_problem_language").get_attribute("value").lower().replace(" ", "") == "c++20",
              "unknown C++20 inference", timeout=90)
        _click(driver, "submit-send")
        prompt = _wait(driver, lambda: _alert(driver), "unknown receipt initial explicit confirmation")
        _require("Main source file: " + source.name in prompt.text and "Problem: A" in prompt.text,
                 "Unknown initial confirmation did not identify the source and problem")
        prompt.accept()

        def unknown_operation():
            value = _state(driver)
            if not value or value.get("submitting"):
                return None
            return next((item for item in value.get("submissions", []) if item.get("state") == "unknown"
                         and item.get("operationId") not in initial_operations and item.get("filename") == source.name), None)

        uncertain = _wait(driver, unknown_operation, "visible durable unknown operation after the HTTP 503", timeout=120)
        operation_id = uncertain["operationId"]
        _wait(driver, lambda: not driver.find_element(By.ID, "submit-modal").is_displayed(), "unknown result modal dismissal")
        _require(not uncertain.get("id"), "An unconfirmed receipt was assigned a guessed provider ID")
        _require(driver.find_element(By.CSS_SELECTOR, f'tr[data-operation-id="{operation_id}"]').text.find("结果未确认") >= 0,
                 "The UI did not label the operation as unconfirmed")
        if get_post_count is not None:
            _require(get_post_count() == 1, "The uncertain response did not leave exactly one source POST")
        report["unknownObserved"] = True
        _record(report, "http503_preserves_visible_unknown_operation", {"operationId": operation_id,
                "state": uncertain["state"], "providerId": uncertain.get("id"),
                "serverPostCount": get_post_count() if get_post_count is not None else None})
        _screenshot(driver, output, "unknown-result", report)

        # A normal history refresh can discover a provider fact, but may not
        # silently infer that it is the same source-send intent.
        _click(driver, "refresh-submissions")
        _wait(driver, lambda: driver.find_element(By.ID, "refresh-submissions").is_enabled(), "unknown explicit refresh completion", timeout=90)

        def observed_provider():
            value = _state(driver)
            if not value:
                return None
            return next((item for item in value.get("submissions", []) if str(item.get("id")) == "1000001"
                         and item.get("state") == "confirmed" and item.get("verdict") == "CORRECT"), None)

        provider = _wait(driver, observed_provider, "read-only discovery of the actual accepted provider fact", timeout=120)
        _require(any(item.get("operationId") == operation_id and item.get("state") == "unknown"
                     for item in _state(driver)["submissions"]), "Refresh guessed a source association without explicit user reconciliation")
        _record(report, "history_discovery_does_not_blindly_associate_source", {"providerId": provider["id"],
                "unknownOperationId": operation_id, "providerVerdict": provider["verdict"]})

        resume_url = driver.current_url
        old_handle = driver.current_window_handle
        if len(driver.window_handles) == 1:
            driver.switch_to.new_window("tab")
            driver.get("about:blank")
            driver.switch_to.window(old_handle)
        driver.close()
        _require(old_handle not in driver.window_handles, "Unknown workbench tab did not close")
        driver.switch_to.window(driver.window_handles[0])
        driver.switch_to.new_window("tab")
        workbench_handle = driver.current_window_handle
        driver.get(resume_url)
        restored = _wait(driver, lambda: value if (value := _state(driver)) and value.get("connected")
                         and (value.get("session") or {}).get("sessionId") == session_id
                         and any(item.get("operationId") == operation_id and item.get("state") == "unknown"
                                 for item in value.get("submissions", [])) else None,
                         "unknown operation after actual workbench tab close/reopen", timeout=90)
        _require(restored["session"]["startAt"] == session["startAt"], "Unknown operation recovery changed the VP anchor")
        _record(report, "unknown_intent_survives_refresh_and_tab_reopen", {"operationId": operation_id})
        _screenshot(driver, output, "unknown-restored", report)

        storage = driver.execute_async_script("""
          const done=arguments[arguments.length-1],source=arguments[0],encoded=arguments[1],op=arguments[2];
          browser.storage.local.get(null).then(values=>{
            const containsPayload=value=>typeof value==='string' ? value.includes(source)||value.includes(encoded) :
              Array.isArray(value) ? value.some(containsPayload) : value&&typeof value==='object' ? Object.values(value).some(containsPayload) : false;
            const intent=(values.vpUiSubmissionIntents||[]).find(item=>item.operationId===op);
            done({payloadAbsent:!containsPayload(values),intentFound:!!intent,intentState:intent?.state,
              intentKeys:intent?Object.keys(intent).sort():[]});
          },()=>done({readFailed:true}));
        """, source_bytes.decode("utf-8", errors="replace"), base64.b64encode(source_bytes).decode("ascii"), operation_id)
        _require(storage.get("payloadAbsent") and storage.get("intentFound") and storage.get("intentState") == "unknown",
                 "Unknown operation's stable metadata was not retained without source payload")
        _record(report, "extension_storage_retains_unknown_id_without_source_payload", storage)

        # Attempt the exact same source via the real button after reopening.
        # If a regression opens a new confirmation, dismiss it; never accept a
        # second source delivery merely to demonstrate a bug.
        _click(driver, "open-submit")
        _modal_visible(driver, "submit-modal")
        driver.find_element(By.ID, "submit_problem_code").send_keys(str(source))
        _wait(driver, lambda: driver.find_element(By.ID, "submit_problem_language").get_attribute("value").lower().replace(" ", "") == "c++20",
              "duplicate-source inferred language", timeout=90)
        _click(driver, "submit-send")

        def blocked_duplicate():
            prompt = _alert(driver)
            if prompt:
                prompt.dismiss()
                return {"unexpectedConfirmation": True}
            error = driver.find_element(By.ID, "submit-error")
            if error.is_displayed() and "已有结果未确认" in error.text:
                return {"blocked": True, "message": error.text}
            return None

        blocked = _wait(driver, blocked_duplicate, "same-source duplicate prevention message", timeout=20)
        _require(blocked.get("blocked") and not blocked.get("unexpectedConfirmation"),
                 "Uncertain same-source delivery was incorrectly offered a second confirmation")
        if get_post_count is not None:
            _require(get_post_count() == 1, "The blocked duplicate emitted a second POST")
        _require(_operation_ids(_state(driver)) == _operation_ids(restored), "The duplicate attempt created another source intent")
        _record(report, "same_source_blocked_after_reopen_without_second_post", {"operationId": operation_id,
                "serverPostCount": get_post_count() if get_post_count is not None else None, "confirmDialogOpened": False})
        _screenshot(driver, output, "unknown-duplicate-blocked", report)
        _click(driver, "submit-cancel")
        _wait(driver, lambda: not driver.find_element(By.ID, "submit-modal").is_displayed(), "blocked-source modal close")

        reconcile = driver.find_element(By.CSS_SELECTOR, f'tr[data-operation-id="{operation_id}"] .vp-reconcile')
        _click(driver, reconcile)
        _modal_visible(driver, "reconcile-modal")
        _require(source.name in driver.find_element(By.ID, "reconcile-description").text,
                 "Reconcile dialog omitted the uncertain source")
        _fill(driver, "reconcile-id", "1000001")
        _screenshot(driver, output, "unknown-reconcile-confirmation", report)
        _click(driver, driver.find_element(By.CSS_SELECTOR, '#reconcile-form button[type="submit"]'))

        def reconciled_fact():
            value = _state(driver)
            if not value:
                return None
            facts = value.get("submissions", [])
            if len(facts) != 1:
                return None
            item = facts[0]
            return item if str(item.get("id")) == "1000001" and item.get("operationId") == operation_id \
                and item.get("state") == "confirmed" and item.get("verdict") == "CORRECT" and not item.get("pending") else None

        confirmed = _wait(driver, reconciled_fact, "explicitly linked single confirmed provider fact", timeout=120)
        _wait(driver, lambda: not driver.find_element(By.ID, "reconcile-modal").is_displayed(), "reconcile dialog completion")
        _require(confirmed.get("elapsedMs", 0) >= TWO_HOURS_MS, "Reconciliation lost the two-hour offset")
        if get_post_count is not None:
            _require(get_post_count() == 1, "Explicit read-only reconciliation emitted another source POST")
        report["reconciled"] = True
        _record(report, "explicit_dialog_reconciles_one_fact_without_source_resubmit", {"operationId": operation_id,
                "submissionId": confirmed["id"], "verdict": confirmed["verdict"], "factCount": 1,
                "serverPostCount": get_post_count() if get_post_count is not None else None})
        _screenshot(driver, output, "unknown-reconciled", report)
        recovered = _state(driver)
        manifest = {"schema": "qoj-vp-ui-restart-v1", "scenario": "unknown503", "createdAt": time.time(),
                    "outputDir": str(output), "profile": profile, "firefoxPid": driver.capabilities.get("moz:processID"),
                    "sessionId": session_id, "resumeUrl": resume_url, "ranklandUrl": session["ranklandUrl"],
                    "expectedStartAt": session["startAt"], "expectedSubmissionId": str(confirmed["id"]),
                    "expectedOperationId": operation_id, "unknownObserved": True, "reconciled": True}
        manifest_path = _write(output / "ui-restart-manifest.json", manifest)
        report.update(status="phase1_passed_restart_pending", sessionId=session_id, url=resume_url,
                      resumeUrl=resume_url, ranklandUrl=session["ranklandUrl"], expectedSubmissionId=str(confirmed["id"]),
                      twoHoursElapsed=True, state=recovered, restart_manifest=manifest_path)
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:1200]}", traceback=traceback.format_exc())
        _capture_failure(driver, report, output)
    finally:
        try:
            if workbench_handle in driver.window_handles:
                driver.switch_to.window(workbench_handle)
        except Exception:
            pass
        report["finishedAt"] = time.time()
        report["report_path"] = _write(output / "ui-phase1-result.json", report)
    return report


def run_account_mismatch_probe(driver, output_dir, source_path, *, switch_account, get_post_count):
    """Verify a real pre-POST account rejection does not poison the UI cache.

    Reuse an existing csj-test session and the controller's live loopback
    fixture. switch_account changes that fixture's actual GET login response;
    it never intercepts application calls or fabricates a helper result. The
    only accepted confirmation runs while the fixture reports csj-other, so
    authenticate must stop the operation before its durable intent or POST.
    The restored-account confirmation is dismissed without sending source.
    """
    from selenium.webdriver.common.by import By

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "qoj-vp-ui-account-mismatch-v1", "startedAt": time.time(),
              "checks": [], "screenshots": {}, "syntheticQojFixture": True,
              "realQojSubmission": False, "cleanup": {}, "retryPromptShown": False}
    workbench_handle = None
    own_modal = False

    def stored_intents():
        return driver.execute_async_script("""
          const done=arguments[arguments.length-1];
          browser.storage.local.get('vpUiSubmissionIntents').then(values=>done(
            (values.vpUiSubmissionIntents||[]).map(item=>({operationId:item.operationId,
              sessionId:item.sessionId,filename:item.filename,state:item.state}))),
            ()=>done(null));
        """)

    try:
        _require(callable(switch_account) and callable(get_post_count), "Provide the controller's actual fixture callbacks")
        _profile(driver)
        workbench_handle = _workbench(driver)
        initial = _ui_ready(driver)
        session = initial.get("session") or {}
        _require(session.get("account") == "csj-test", "Reuse an existing synthetic csj-test session")
        _require(any(item.get("id") and item.get("verdict") == "CORRECT" for item in initial.get("submissions", [])),
                 "Run the narrow mismatch regression after the confirmed submission check")
        _record(report, "fixture_guard_existing_confirmed_session", _native_fixture_hello(driver))
        source = Path(source_path).resolve()
        _require(source.is_file() and source.name.lower() == "a.cpp", "Use the same pre-created synthetic A.cpp")
        _require(0 < source.stat().st_size <= 512 * 1024, "Source exceeds the product's bounds")
        baseline_posts = get_post_count()
        _require(isinstance(baseline_posts, int) and baseline_posts >= 1, "Expected the existing confirmed fixture POST")
        report.update(sessionId=session["sessionId"], postCountBefore=baseline_posts)
        before_intents = stored_intents()
        _require(isinstance(before_intents, list), "Could not observe local intent metadata")
        before_ids = {item["operationId"] for item in before_intents}

        _click(driver, "nav-home")
        _click(driver, "open-submit")
        own_modal = True
        _modal_visible(driver, "submit-modal")
        driver.find_element(By.ID, "submit_problem_code").send_keys(str(source))
        _wait(driver, lambda: driver.find_element(By.ID, "submit_problem_language").get_attribute("value").lower().replace(" ", "") == "c++20",
              "mismatch source language inference", timeout=90)
        switch_account("csj-other")
        _click(driver, "submit-send")
        prompt = _wait(driver, lambda: _alert(driver), "explicit mismatch confirmation")
        _require("Main source file: " + source.name in prompt.text, "Mismatch confirmation omitted the source")
        prompt.accept()

        def rejected_intent():
            metadata = stored_intents()
            if not isinstance(metadata, list):
                return None
            value = _state(driver)
            if not value or value.get("submitting"):
                return None
            return next((item for item in metadata if item.get("sessionId") == session["sessionId"]
                         and item.get("operationId") not in before_ids and item.get("filename") == source.name
                         and item.get("state") == "rejected"), None)

        rejected = _wait(driver, rejected_intent, "definitive local rejected intent after account mismatch", timeout=90)
        error = driver.find_element(By.ID, "submit-error")
        _require(error.is_displayed() and "differs" in error.text.lower() and "account" in error.text.lower(),
                 "The UI did not show the original definitive account-mismatch error")
        _require("提交结果未确认" not in error.text, "Pre-POST account error was misreported as an uncertain submission")
        _require(get_post_count() == baseline_posts, "Account mismatch emitted a source POST")
        _require(_provider_ids(_state(driver)) == _provider_ids(initial), "Account mismatch added a provider submission")
        _require(_operation_ids(_state(driver)) == _operation_ids(initial), "Account mismatch added a native send intent to history")
        report["rejectedOperationId"] = rejected["operationId"]
        _record(report, "actual_account_mismatch_is_definitive_no_send", {"operationId": rejected["operationId"],
                "localIntentState": rejected["state"], "uiMessage": error.text, "postCount": get_post_count(),
                "nativeOperationAbsenceVerifiedByParent": None})
        _screenshot(driver, output, "account-mismatch-rejected", report)

        switch_account("csj-test")
        _require(driver.find_element(By.ID, "submit_problem_code").get_attribute("value").endswith(source.name),
                 "The pre-send rejection lost the file selection")
        _click(driver, "submit-send")
        prompt = _wait(driver, lambda: _alert(driver), "same-source confirmation after restoring original account", timeout=20)
        _require("Main source file: " + source.name in prompt.text and "Account: csj-test" in prompt.text,
                 "Restored-account retry did not identify the same explicit file/account")
        report["retryPromptShown"] = True
        prompt.dismiss()
        _wait(driver, lambda: not _state(driver).get("submitting"), "restored-account confirmation cancel")
        after_intents = stored_intents()
        _require(isinstance(after_intents, list), "Could not observe final local intent metadata")
        new_intents = [item for item in after_intents if item["operationId"] not in before_ids]
        _require(len(new_intents) == 1 and new_intents[0]["operationId"] == rejected["operationId"]
                 and new_intents[0]["state"] == "rejected", "Dismissing the retry created a new or unknown local intent")
        _require(get_post_count() == baseline_posts, "Restored-account canceled confirmation emitted a POST")
        _record(report, "same_source_can_be_confirmed_after_account_restored", {"retryPromptShown": True,
                "retryDismissed": True, "newLocalIntentCount": 1, "localIntentState": "rejected",
                "postCount": get_post_count()})
        _screenshot(driver, output, "account-mismatch-restored", report)
        report.update(status="passed", postCountAfter=get_post_count())
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:1200]}", traceback=traceback.format_exc())
        _capture_failure(driver, report, output)
    finally:
        try:
            switch_account("csj-test")
            report["cleanup"]["fixtureAccountRestored"] = True
        except Exception as exc:
            report["cleanup"]["fixtureAccountRestored"] = False
            report["cleanup"]["accountRestoreErrorType"] = type(exc).__name__
            report["status"] = "failed"
        try:
            if workbench_handle in driver.window_handles:
                driver.switch_to.window(workbench_handle)
                prompt = _alert(driver)
                if prompt:
                    prompt.dismiss()
                if own_modal and driver.find_element(By.ID, "submit-modal").is_displayed():
                    _wait(driver, lambda: not (_state(driver) or {}).get("submitting"), "mismatch cleanup send completion", timeout=20)
                    _modal_visible(driver, "submit-modal")
                    _click(driver, "submit-cancel")
                    _wait(driver, lambda: not driver.find_element(By.ID, "submit-modal").is_displayed(), "mismatch own modal cleanup")
                report["cleanup"]["ownModalClosed"] = True
        except Exception as exc:
            report["cleanup"]["ownModalClosed"] = False
            report["cleanup"]["modalCloseErrorType"] = type(exc).__name__
            report["status"] = "failed"
        report["finishedAt"] = time.time()
        report["report_path"] = _write(output / "ui-account-mismatch-result.json", report)
    return report


def resume_ui_probe(driver, manifest):
    """After the parent restarts Firefox, observe restored UI without mutations."""
    if not isinstance(manifest, dict):
        manifest = json.loads(Path(manifest).read_text(encoding="utf-8"))
    output = Path(manifest["outputDir"])
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "qoj-vp-ui-phase2-v1", "startedAt": time.time(), "checks": [], "screenshots": {}}
    try:
        _require(manifest.get("schema") == "qoj-vp-ui-restart-v1", "Unknown UI restart manifest")
        profile = _profile(driver)
        _require(Path(profile).resolve() == Path(manifest["profile"]).resolve(), "Firefox profile changed across restart")
        pid = driver.capabilities.get("moz:processID")
        _require(isinstance(pid, int) and pid != manifest["firefoxPid"], "The parent did not restart Firefox into a new process")
        _record(report, "real_firefox_restart_same_profile", {"beforePid": manifest["firefoxPid"], "afterPid": pid})
        _workbench(driver)
        recovered = _wait(driver, lambda: value if (value := _state(driver)) and value.get("connected")
                          and (value.get("session") or {}).get("sessionId") == manifest["sessionId"]
                          and any(str(item.get("id")) == manifest["expectedSubmissionId"] and item.get("verdict") == "CORRECT" for item in value.get("submissions", [])) else None,
                          "saved session, source receipt, and final verdict after Firefox restart", timeout=90)
        session = recovered["session"]
        _require(session["startAt"] == manifest["expectedStartAt"], "Firefox restart changed session start")
        _require(session["ranklandUrl"] == manifest["ranklandUrl"], "Firefox restart changed exact RankLand URL")
        _require(session.get("elapsedMs", 0) >= TWO_HOURS_MS, "Firefox restart reset the two-hour elapsed time")
        record = next(item for item in recovered["submissions"] if str(item.get("id")) == manifest["expectedSubmissionId"])
        _require(record.get("operationId") == manifest["expectedOperationId"], "Source operation association was lost")
        _record(report, "session_receipt_verdict_and_clock_restored", {"sessionId": session["sessionId"],
                "submissionId": record["id"], "verdict": record["verdict"], "elapsedMs": session["elapsedMs"]})
        _screenshot(driver, output, "firefox-restarted", report)
        report.update(status="passed", sessionId=session["sessionId"], expectedSubmissionId=record["id"],
                      twoHoursElapsed=True, state=recovered)
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:1200]}", traceback=traceback.format_exc())
        _capture_failure(driver, report, output)
    finally:
        report["finishedAt"] = time.time()
        report["report_path"] = _write(output / "ui-phase2-result.json", report)
    return report


def _demo_version(driver):
    return driver.execute_script(r"""
      const walker=document.createTreeWalker(document,NodeFilter.SHOW_COMMENT);
      let node; while((node=walker.nextNode())) {
        const found=node.nodeValue.match(/DOMjudge version\s+([^\s]+)/);
        if(found) return found[1];
      }
      for(const link of document.querySelectorAll('link[href]')) {
        const version=new URL(link.href).searchParams.get('v'); if(version) return version;
      }
      return null;
    """)


def _demo_nav(driver, text):
    from selenium.webdriver.common.by import By
    return _wait(driver, lambda: next((link for link in driver.find_elements(By.CSS_SELECTOR, "nav a[href]")
                 if link.is_displayed() and link.text.strip().lower() == text.lower()), None), "official demo " + text + " navigation")


def capture_domjudge_reference(driver, output_dir):
    """Read-only Home/Problemset/Submit capture at the official public demo.

    The public demo documents team/team login. This is the sole external POST
    used here (login). No source is selected, and no solution is submitted.
    Actual version is captured; current development demo need not equal 9.0.1.
    """
    from selenium.webdriver.common.by import By

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "domjudge-official-team-reference-v1", "startedAt": time.time(),
              "source": DEMO_PAGE, "checks": [], "screenshots": {}, "sourceSubmitted": False,
              "pinnedSourceVersion": PINNED_DOMJUDGE_VERSION}
    previous_handle = driver.current_window_handle
    before_handles = set(driver.window_handles)
    try:
        _profile(driver)
        driver.switch_to.new_window("tab")
        driver.get(DEMO_PAGE)
        _require(urlsplit(driver.current_url).hostname == "www.domjudge.org", "Official demo discovery left the expected origin")
        links = driver.find_elements(By.TAG_NAME, "a")
        team_link = next((link for link in links if link.text.strip() == "Team interface"), None)
        _require(team_link is not None, "Official demo page did not link a Team interface")
        team_url = team_link.get_attribute("href")
        _require(urlsplit(team_url).hostname == "www.domjudge.org" and "/demoweb/team" in urlsplit(team_url).path,
                 "Unexpected official Team demo destination")
        _record(report, "official_demo_discovery", {"teamUrl": team_url})
        driver.get(team_url)
        login_fields = driver.find_elements(By.NAME, "_username")
        if login_fields:
            login_fields[0].send_keys("team")
            driver.find_element(By.NAME, "_password").send_keys("team")
            login_form = login_fields[0].find_element(By.XPATH, "ancestor::form")
            submit = login_form.find_element(By.CSS_SELECTOR, 'button[type="submit"],input[type="submit"]')
            _click(driver, submit)
        _wait(driver, lambda: "/demoweb/team" in urlsplit(driver.current_url).path
              and bool(driver.find_elements(By.CSS_SELECTOR, "nav.navbar")), "official team demo login", timeout=45)
        report["version"] = _demo_version(driver)
        _require(bool(report["version"]), "Could not observe the actual DOMjudge demo version")
        report["matchesPinnedVersion"] = report["version"] == PINNED_DOMJUDGE_VERSION
        if not report["matchesPinnedVersion"]:
            report["limitation"] = "The official running demo differs from pinned 9.0.1 source; screenshots are a real-server reference, not proof of pixel equivalence to 9.0.1."
        report["homeUrl"] = driver.current_url
        _record(report, "real_team_home", {"title": driver.title,
                "version": report["version"], "hasSubmissions": bool(driver.find_elements(By.CSS_SELECTOR, ".submissions-table"))})
        _screenshot(driver, output, "domjudge-home", report)

        _click(driver, _demo_nav(driver, "Problemset"))
        _wait(driver, lambda: bool(driver.find_elements(By.CSS_SELECTOR, ".problem-list .card")), "real DOMjudge Problemset cards")
        report["problemsetUrl"] = driver.current_url
        cards = driver.find_elements(By.CSS_SELECTOR, ".problem-list .card")
        _record(report, "real_problemset", {"cardCount": len(cards), "version": _demo_version(driver)})
        _screenshot(driver, output, "domjudge-problemset", report)

        nav_submit = _wait(driver, lambda: next((link for link in driver.find_elements(By.CSS_SELECTOR, "nav [data-ajax-modal]")
                          if link.is_displayed() and "Submit" in link.text and not link.find_elements(By.CSS_SELECTOR, ".disabled")), None),
                          "real DOMjudge Submit modal link")
        _click(driver, nav_submit)
        modal = _wait(driver, lambda: next((item for item in driver.find_elements(By.CSS_SELECTOR, ".modal.show") if item.is_displayed()), None),
                      "real DOMjudge Submit modal")
        fields = {}
        for label, selector in (("source", 'input[type="file"]'), ("problem", 'select[id*="problem"]'), ("language", 'select[id*="language"]')):
            fields[label] = bool(modal.find_elements(By.CSS_SELECTOR, selector))
        _record(report, "real_submit_modal_opened_without_source", {"fieldsPresent": fields, "version": _demo_version(driver)})
        _screenshot(driver, output, "domjudge-submit", report)
        close = next((control for control in modal.find_elements(By.CSS_SELECTOR, '[data-bs-dismiss="modal"]') if control.is_displayed()), None)
        if close:
            _click(driver, close)
        report.update(status="passed", sourceSubmitted=False)
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:1200]}", traceback=traceback.format_exc())
        try:
            _screenshot(driver, output, "domjudge-reference-failure", report)
        except Exception:
            pass
    finally:
        # Keep the caller's workbench and RankLand tabs intact.
        for handle in list(driver.window_handles):
            if handle not in before_handles:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                except Exception:
                    pass
        if previous_handle in driver.window_handles:
            driver.switch_to.window(previous_handle)
        report["finishedAt"] = time.time()
        report["report_path"] = _write(output / "domjudge-reference-result.json", report)
    return report
