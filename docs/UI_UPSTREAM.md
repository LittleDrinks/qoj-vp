# DOMjudge team UI adaptation

The workbench uses DOMjudge 9.0.1's team-page structure and its actual stylesheet. It is a Firefox extension adapting QOJ, not a DOMjudge server. Only Home/Submissions, Problemset, the submit interaction, one local team's progress row and a link to original RankLand are included.

## Fixed upstream source

DOMjudge repository: <https://github.com/DOMjudge/domjudge>

Fixed commit: `90bbb727906efb438ac2ec7512c09f17824cfc41` (9.0.1).

Source byte/Git-blob verification is in `preflight/domjudge-reference/source-manifest.json`. The full downloaded reference files remain under its `upstream/` directory.

| Upstream file under webapp/ | Extension use |
| --- | --- |
| `templates/base.html.twig` | Local CSS/script ordering and container structure in `ui.html`; dynamic server routes become extension actions. |
| `templates/team/menu.html.twig` | Dark fixed navbar, Home/Problemset/Scoreboard navigation, green Submit button and countdown. Out-of-scope menu items omitted. |
| `templates/team/partials/index_content.html.twig` | Top team's progress, teamoverview heading and submissions region. Clarifications are omitted; the right column contains VP controls. |
| `templates/team/partials/submission_list.html.twig` | `data-table table table-hover table-striped table-sm` and time/problem/lang/result columns. Added QOJ receipt link and explicit unknown-outcome reconciliation. |
| `templates/partials/problem_list.html.twig` | Actual responsive card grid, badge/title/card-subtitle structure and Submit/statement/samples actions. Added a distinct PDF action; unknown time/memory/type metadata is omitted instead of invented. |
| `templates/team/submit_modal.html.twig` | Large Bootstrap modal, single source-file input, problem/language fields, file size/mtime notice, Cancel/Submit. QOJ only accepts one source in this adapter. |
| `templates/team/partials/submit_scripts.html.twig` | File-basename problem detection only while autodetect is selected, selectable language, file/problem/language confirmation. No QOJ Java/Kotlin entry-point field is invented. |
| `public/js/domjudge.js` | `humanReadableTimeDiff` and `humanReadableBytes` adapted with the same interval thresholds. The rest of the server AJAX code is not loaded. |
| `src/Twig/TwigExtension.php`, `printResult` | Same `sol`, `sol_correct`, `sol_incorrect`, `sol_queued` styles. UI keeps QOJ's unknown state separate from a rejected verdict. |
| `public/style_domjudge.css` | Copied byte-for-byte into `extension/assets/domjudge/style_domjudge.css`. |

Twig is a server template language. `ui.html` and `ui.js` retain the listed DOM structure and classes but replace Twig loops/routes/filters with DOM updates and native-helper requests. No PHP/Twig runtime is packaged. `ui.css` contains the small VP-specific additions; the upstream stylesheet remains unchanged.

Language preferences match `qoj-submitter`'s `choose_language` aliases at pinned commit `807ce1be13d67916b2716f8221a10a12731977fe`, including C++20, Python3 and Java21. Only exact normalized available options are inferred; missing/ambiguous variants require a manual selection. The actual selected language is still validated by the backend before submission.

## Packaged third-party assets

These are local byte-for-byte copies of the actual files, not the symlink text found in DOMjudge's `public/` Git paths. There are no CDN script, stylesheet or font dependencies at runtime. `extension/assets/UPSTREAM.json` records each packaged file's SHA-256 and source-reference path.

| Package | Version / fixed source | License copy |
| --- | --- | --- |
| DOMjudge | 9.0.1 / `90bbb727906efb438ac2ec7512c09f17824cfc41` | `assets/licenses/DOMjudge-COPYING` (GPL-2.0-or-later as declared by upstream README) |
| Bootstrap | 5.3.7 / `e0032ae6a5a628a51a8552091816cec09b6434df` | `assets/licenses/Bootstrap-LICENSE` (MIT) |
| Font Awesome Free | 6.5.2 / `c0f460dca7f7688761120415ff3c9cf7f73119be` | `assets/licenses/FontAwesome-LICENSE.txt` (CSS/code MIT, fonts SIL OFL 1.1, icons CC BY 4.0) |

Bootstrap and Font Awesome versions match the fixed DOMjudge `webapp/composer.lock`. Reference manifests are `third-party-manifest.json`, `fontawesome-manifest.json`, and `composer-frontend-lock-extract.json` in `preflight/domjudge-reference/`.

The derived UI files carry `GPL-2.0-or-later` notices. The per-package licenses remain separate. The root project must retain these files when building an XPI/source distribution.

## User flow and backend interface

The UI calls the message contract in `MVP_CONTRACT.md`. Additional agreed methods are `update_session {sessionId,ranklandUrl,title?}` and `qoj_reconcile {sessionId,operationId,submissionId}`. The former does not alter an existing contest/start/account. The latter requires the user to identify the actual original-site submission and never sends code.

1. Prepare VP: read QOJ contest ID/link using the normal browser login; show the detected account and problem count; save a title, duration, optional RankLand URL and optional prior start time.
2. Start: persist the start anchor. The UI explicitly distinguishes this local practice clock from QOJ's native virtual-contest registration.
3. Submit: select the source file; infer exact problem/available language; allow manual overrides; the original DOMjudge-style browser `confirm` shows the chosen file/account/contest/problem/language before sending. Cancel does not send a native submit task.
4. Confirmed receipts display the provider ID and poll detailed verdicts. The UI updates only the history and progress row, preserving any open file input and selected language.
5. Uncertain delivery retains a stable operation ID and source digest in extension storage, with no source-code copy. A matching unresolved intent cannot be re-sent by the UI. The backend ledger remains the authority and independently prevents duplicate POSTs.
6. RankLand opens the durable exact original-site URL stored with the session. Sync failure does not re-submit source code. Problemset offers original statement, PDF action and each problem's own samples ZIP.

For submit errors, `LOGIN_REQUIRED`, `ACCOUNT_UNKNOWN`, `ACCOUNT_MISMATCH`, and `SESSION_NOT_RUNNING` are definitive pre-send failures: `Application.submit` raises them before creating the durable send intent and calling `QojClient.submit`. The local UI metadata is marked rejected, allowing a fresh explicit attempt after fixing login/account/session state. Generic `QOJ_ERROR`, `INTERNAL_ERROR`, and transport disconnection remain uncertain. An HTTP 503 outcome also stays unknown and requires explicit reconciliation.

## VM acceptance still required

Local checks cover JavaScript syntax, valid unique DOM IDs, matching script references, local asset presence, absence of inline scripts, and copied-asset integrity. These checks do not prove a working browser/native/QOJ integration.

Use the actual VM Firefox to validate:

- Initial empty state and persistent-session selector; prepare and start at a two-hour anchor, then close/reopen the workbench and Firefox.
- Select `A.cpp` through `#submit_problem_code`, observe inferred problem/language, manually override both, then cancel without a POST.
- Submit one controlled fixture source through the actual confirm action; verify receipt ID, pending-to-final transition, and that a polling update preserves an independently open selected file.
- Force an uncertain receipt; refresh/reopen, select the same source, verify that no second POST is emitted. Use the explicit reconciliation dialog for a real matching provider receipt.
- Problemset per-problem Submit preselection, own samples archive and distinct HTML/original-PDF behavior.
- Open stored RankLand, close the tab, reopen it and verify the same original-site VP run/progress. Validate sync through original controls, without writing localStorage directly.

For an actual DOMjudge visual/interaction reference, run or obtain a real team session at the fixed upstream version and capture Home, Problemset, and Submit at the same Firefox viewport. Compare those pages with the workbench; a static adaptation rendered by this extension is not an independent real-DOMjudge reference. The reference source alone does not certify pixel equivalence.

`window.qojVpUi.getState()` returns current session, summarized contest, submission facts and last error for acceptance observation. `refresh()` and `selectSession()` use the same ordinary UI requests. No exposed helper directly submits source, accesses CSRF or writes RankLand storage.
