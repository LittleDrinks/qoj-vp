# Active goal checkpoint — 2026-10-31

User authorized implementation and explicitly requested a goal. It is active: deliver and verify QOJ MVP in VMware Firefox. Continue autonomously, CF/Gym excluded, keep Windows focus unchanged. Source/evidence stay under this workspace.

## Verified and fixed

- Reboot readiness all6 passed. Full preflight round4 all22 required checks passed (23 total including independent real-QOJ403 observation); cleanup passed.
- Production MVP round2 run92dcb28e76bb400384f5ad4f07fbbe36 already passed25 main checks through actual Firefox: visible UI, cancel0POST/confirm1POST, file hash, observed original302/Location, finalAC, samples/form, original RankLand form/own-row, first board opened2h late, tab/browser restart and repeated sync. Final demo/cleanup still needs collection.
- Actual official DOMjudge pages captured during round1, version10.0.0DEV/96199cbe3. Source pinned9.0.1, not pixel-equivalence. Images: artifacts/vm-mvp/round1/results/mvp/8f7e87b1a70b48d3aa2cca8989b84d11/.
- Backend13 meaningful integrations passed, including terminating actual helper after POST acceptance and proving restart does not repeat. Later no-op URL and prepare_rankland clock regressions passed.
- Selenium base64-uploaded addon could not load content files; persistent INSTALL_ADDON path works. Do not claim proven premature file deletion.
- Firefox Xray Headers iterators and TypedArray.subarray spread failed. Use response headers allowlist.get and indexed bytes; final probe7 returned200/649B/stage done.
- First late RankLand open uses prepare_rankland to persist actual elapsed fractional minutes in from once. Reopens use the exact URL.
- RankLand full identity includes origin/contest/run/rule/count/ratio/at/from. Receipt scoped to destination. Opening serialized, duplicate writers block sync, content checks unique writer before click. RTE/NOUT mapping fixed; rejudge requires review.
- PDF checks active tab/final URL and truthful save/cancel status. UI probe now waits Bootstrap animations before Cancel; product Bootstrap unchanged.

## Current work and remaining gate

MVP round2 final status to collect from guest results/mvp-summary.json. UI main path passed; original DOMjudge capture/cleanup was still running at last read.

Agents backend_mvp and ui_mvp are extending controller/probe for --scenario unknown503, --skip-domjudge-reference, actual unknown no-repeat + explicit UI reconciliation, and duplicate-tab/concurrent-open safety. They never operate VM. bridge_fix completed review and documentation; can handle concrete QA findings.

Async user question pending: complete real QOJ security verification/login in ordinary VM Firefox, and give practice contest/problem/source or manually submit. No QOJ password/cookie import. No real-QOJ source POST occurred. Do all independent work first and keep goal active; fixture success alone is insufficient for completion.

## Paths and transport

Workspace /home/q2635/wsl-workspace/qoj-vp, local Git main initialized, submodule vendor/qoj-submitter pinned807ce1be13d67916b2716f8221a10a12731977fe. No remote push requested.

Preflight guest /home/csj/.local/share/qoj-vp-preflight/2026-10-31; product guest /home/csj/.local/share/qoj-vp-mvp/2026-10-31. Exchange E:\shared\qoj-vp-preflight-stage. VMX E:\VirtualBox VMs\hydro-contest-os-2026\hydro contest os.vmx; vmrun D:\Program Files\VMware\VMware Workstation\vmrun.exe.

Functions store qojVmNativePrefix contains ephemeral user-authorized guest credentials: never print/save it. PowerShell encoded in memory, timeout errors omit argv. VIX inline script quoting is broken; copy durable files then runProgramInGuest. Jobs use -noWait and atomic status. No host activation or GUI launching.

Deployed artifacts/mvp-payload.tar.gz SHA1bdbfaa7d885d9dd8dd70d5d6a8c1f10969d9273369d10a9bf981412764282c3, then round2 overlay extension/ui.js+preflight/mvp_ui_probe.py. Build/overlay again for new QA changes.

QA creates an owned fixture native manifest and unique DB per run, removes manifest afterward. Do not install permanent product registration until QA ends; controller refuses to overwrite it. Final install uses scripts/install_native.py --dependencies <guest-root>/preflight/vendor_py. User can temporary-load extension/manifest.json in normal Firefox; XPI unsigned. Persistent user state separate from QA.

## Latest follow-up

MVP accepted round2 finished: all28 required checks passed; optional official-demo reference and all cleanup passed. Full archive artifacts/vm-mvp/round2/results.tar.gz collected. Current backend full suite15 tests passed independently, artifacts/backend-tests.txt.

Unknown503 VM run e8b34deb349446389fa542bc3092cd54: real UI unknown/reopen/no-repeat/explicit reconciliation and source503/noLocation checks passed. RankLand delivery then failed a unique-writer guard; later snapshots cascaded from that failure. It is not yet proven whether transient duplicate creation or sender identity caused the guard. Root added safe guard decision metadata and made open coalescing wait until Tab.url commits. Next accepted QA must include this fix, UI pre-POST error classification fix, duplicate/concurrent checks and account-mismatch probe. If failing, inspect vp.diagnostics.ranklandGuards before guessing. Backend agent is making dependent-check gating to avoid repeated50s waits after same sync failure.

Host PowerShell Get-Content -Raw must specify -Encoding UTF8 before ConvertFrom-Json; default ANSI corrupted interpretation of Chinese JSON messages. Files themselves were valid UTF8; Python readback verified. Unknown QA launch was retried only after this host parsing failure, not after any sourcePOST.

Safety QA accepted rerun launched with overlay mvp-safety-overlay.tar.gz (hash manifest in artifacts) after unknown QA cleanup finished. It includes UI deterministic-no-POST error classification and controller account-mismatch probe, all RankLand guards and safe diagnostic events, plus open coalescing held until Tab.url commits. The unknown UI/503/no-repeat/reconcile path itself passed, but its overall run remained failed due later scoreboard guard. Need rerun unknown after guard fix.

A final local UI type guard now excludes null/unverified elapsedMs from the own-team score; Number(null) had counted it as0. This one-line fix is not yet deployed to currently running QA. Preserve in final overlay/package.

## Independent implementation and delivery complete

Safety accepted run c8f60e0edf454263aa2cd9ac1d967883 passed all30 checks including account mismatch/no native intent, duplicate-tab stop and concurrent-open coalescing. Final unknown503 run6d1d889976e149dd8ae526c75a5272e1 passed all29 with no skipped checks, after open coalescing waited for Tab.url commit. All Firefox/fixture/native-helper cleanup passed. Archives collected locally. No more routine testing needed absent new failures or real-account changes.

Permanent real-mode helper installed in VM, app state /home/csj/.local/share/qoj-vp. Installed smoke passed fixture=false, helper PID11450 exited, Firefox PID11190 exited, saveAsPDF API exists. Latest real-QOJ read reaches LOGIN_REQUIRED rather than earlier403; real authenticated source submission still not done. Do not run fixture QA controller over this permanent registration without explicit owned-registration handling (it correctly refuses).

Final XPI dist/qoj-vp-firefox-0.1.0.xpi SHA eab96db6b1ec1c729577da8ca62dac5d144e681280ed4c8442613eaa87b32b17, unsigned. Copied to VM root/qoj-vp-firefox-0.1.0.xpi and E:\shared\qoj-vp-mvp-release with Chinese instructions and report. Final source/README/report copied to guest; foregroundUnchanged=true recorded artifacts/installed-smoke/delivery-status.json. Universal Python wheel build passed. docs/MVP_RESULT.md is current concise acceptance report.

Only required remaining gate: user must log into QOJ in ordinary VM Firefox and supply practice contest/problem/source or manually submit. Async question already pending; do not repeat permission requests. Goal remains active; this is the first goal turn reaching the final external blocker. Under goal rules do not mark blocked until the same blocker recurs for3 consecutive goal turns. Do not claim complete from fixture success. Human OS PDF dialog/real statement layout is also not yet manually verified.
