# MVP implementation contract

2026-10-31. User authorized implementation after reboot. Latest scope is preflight/SCOPE.md; the pause is lifted. No CF/Gym or custom scoreboard.

## Ownership and layout

- `extension/`: Firefox MV3 product, event-page background and full-tab workbench. UI owns ui.html/ui.js/ui.css/assets; root owns background/content scripts/manifest.
- `qojvp/`: importable Python application, SQLite ledger, QOJ adapter and Native Messaging entry. Backend agent owns this directory and tests/.
- `vendor/qoj-submitter`: pinned Git submodule at 807ce1be13d67916b2716f8221a10a12731977fe, import actual library rather than duplicate its submit protocol.
- `preflight/`: isolated feasibility and regression harness, not the production UI.

## UI to extension

`browser.runtime.sendMessage({type:'vp.task', method, args})` resolves `{ok:true,result}` or `{ok:false,error:{code,message}}`. UI must retain a submission's stable `operationId` across retries and must never automatically retry an uncertain POST.

Native transport uses existing preflight length-prefixed frames with task/http.request/http.response/result envelopes. Each task gets a new native port and Python process, closed after its terminal result. Production host name `org.littledrinks.qoj_vp`, extension ID `qoj-vp@littledrinks.local`.

Methods (camelCase JSON fields):

- `hello {}` → `{version, capabilities}`.
- `create_session {contestId,title?,account?,startAt?,durationMs?,ranklandUrl?}` → session below. A missing startAt means prepared; `start_session {sessionId}` persists the local start anchor. This does not claim to register a QOJ native virtual contest.
- `list_sessions {}` → `{sessions:[session]}`; `inspect_session {sessionId}` → session; `archive_session {sessionId}` → session.
- `prepare_rankland {sessionId}` → session with `ranklandPrepared=true`: before first scoreboard opening, freeze the current fractional-minute `from` in the durable URL; later opens reuse it exactly. A past `at` alone does not advance a newly opened original-site replay.
- `qoj_contest {contestId}` → `{id,name,account,problems:[{id,label,name,url}],source}`. Account null means user must log in to QOJ normally.
- `qoj_problem_form {sessionId,problemId}` → `{problemId,languages:[string],csrfPresent,pdfCandidates:[{url,text}],statementUrl}`. Never return CSRF value to UI.
- `qoj_samples {sessionId,problemLabel}` → `{zipFilename,zipBase64,files,warnings,extraFiles}`. Single-problem output from actual upstream samples module.
- `qoj_submit {sessionId,problemId,problemLabel,language,filename,contentsBase64,operationId}` → `{submission,state}`. Confirmed receipt state `confirmed`; uncertain state `unknown` never silently retried. Submission shape below.
- `qoj_submissions {sessionId,refresh?:true}` → `{submissions:[submission],account,coverage:{complete,pages,warning?}}`. Refresh collects same-account original-site history/detail and persists updates; uncertain outcomes require reconciliation before resubmission.

Session: `{sessionId,contestId,title,account,startAt,durationMs,state,effectiveState,elapsedMs,ranklandUrl,createdAt}`. Keep exact durable URL, including stable unique run, not a browser tab ID. Time is derived from a timestamp, never a permanently running Python timer.

Submission: `{id,operationId?,problemId,problemLabel,language,filename?,submittedAt,elapsedMs,verdict,rawVerdict,score?,pending,url,state}`. `id` is provider submission ID when confirmed. DOMjudge verdicts include CORRECT, WRONG-ANSWER, TIMELIMIT, RUN-ERROR, COMPILER-ERROR, NO-OUTPUT, OUTPUT-LIMIT, JUDGING, UNKNOWN. Preserve raw observations; 0 score alone is insufficient to select WA.

Additional browser methods root provides: `rankland.open {sessionId}` (restore exact original-site URL), `rankland.sync {sessionId}`, `problem.pdf {sessionId,problemId}` (prefer original PDF; HTML invokes Firefox's save-as-PDF flow). UI never labels a missing attachment as an existing PDF.

Scoreboard identity includes origin, contest, run, rule, count, ratio, at and from. Opening is serialized. Automatic delivery stops when more than one tab can write the same original-site storage slot; the user keeps one before continuing. Acknowledgements are scoped to both source submission and destination, and rejudging an already delivered result requires review.

## HTTP seam

The Python adapter receives requests-compatible browser transport. All QOJ fetches run in an original-site tab with the browser's own cookies. Requests may include multipart fields and base64 files for one explicit submit. Browser validates origin, method and task authorization. GET can be retried on transient read failures; POST is never retried implicitly. Redirect receipt must come from an observed status/Location, not an invented submission ID; Firefox manual fetch may expose opaque redirects, so root must validate an observational webRequest bridge in the real browser.

No cookie export/import, login UI inside workbench, password storage, disabling Firefox sandbox, or overwriting VM `/usr/local/bin/submit`.

## Verification

First repair isolated GET/native preflight. Then meaningful integration tests cover actual QojClient submit at a controlled fixture, unknown receipts, persisted ledger reconciliation, detailed verdicts, filename/language inference and original RankLand recovery/sync. Real QOJ authenticated submit and real DOMjudge reference-page comparison are separate acceptance items and cannot be replaced by fixture success. No broad test runs after adequate relevant checks pass without a new reason.
