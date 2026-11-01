# MVP implementation contract

2026-11-01, 0.2.0 follow-up in progress. QOJ only; no CF/Gym or custom scoreboard.
This file describes interfaces, not an all-green acceptance claim. Current
verified/pending status is in ACTIVE_WORK.md; MVP_RESULT.md is the dated 0.1.0
record, including the now-retired PDF export behavior.

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
- `qoj_samples {sessionId,problemLabel}` → `{zipFilename,zipBase64,files,warnings,extraFiles}`. Legacy single-problem CLI method remains; the UI uses the resource cache methods below.
- `qoj_submit {sessionId,problemId,problemLabel,language,filename,contentsBase64,operationId}` → `{submission,state}`. Confirmed receipt state `confirmed`; uncertain state `unknown` never silently retried. Submission shape below.
- `qoj_submissions {sessionId,refresh?:true}` → `{submissions:[submission],account,coverage:{complete,pages,warning?}}`. Refresh collects same-account original-site history/detail and persists updates; uncertain outcomes require reconciliation before resubmission.

Session: `{sessionId,contestId,title,account,startAt,durationMs,state,effectiveState,elapsedMs,ranklandUrl,createdAt}`. Keep exact durable URL, including stable unique run, not a browser tab ID. Time is derived from a timestamp, never a permanently running Python timer.

Submission: `{id,operationId?,problemId,problemLabel,language,filename?,submittedAt,elapsedMs,verdict,rawVerdict,score?,pending,url,state}`. `id` is provider submission ID when confirmed. DOMjudge verdicts include CORRECT, WRONG-ANSWER, TIMELIMIT, RUN-ERROR, COMPILER-ERROR, NO-OUTPUT, OUTPUT-LIMIT, JUDGING, UNKNOWN. Preserve raw observations; 0 score alone is insufficient to select WA.

The default Home table renders only `inSession === true` or a nonempty
`operationId`, without mutating the full history/ledger. Own unknown, sending,
rejected and confirmed operations stay visible even outside the local window.
Outside-window rows display no elapsed time (an em dash); the title retains the
absolute date and the reconciliation/details entry stays available. Remaining
history is accessible through the original-site history link. A prepared session
without current/local operations keeps the original No submissions state.

Additional browser methods: `rankland.open {sessionId}` restores the exact
original-site URL; `rankland.sync {sessionId}` delivers confirmed judgements.
`rankland.snapshot {sessionId}` returns `{state,snapshot,reason?,url}` with state
`live`, `cached`, `unavailable`, `not_configured`, or `attention`.

A non-null snapshot contains `{version:1,sessionId,url,identity,targetKey,ownName,
rank,ranks,score,penaltyMinutes,elapsedMs,running,observedAt}`. It is read from the
unique visible own-team row of the original RankLand table, with exact
contest/run/rule/clock identity checks. An unranked team has `rank:null`;
unavailable penalty remains null. No synthetic ranking or penalty is inferred.
The validated snapshot is persisted in extension storage by session and board
identity. A closed, ambiguous or not-ready page returns an explicitly cached
snapshot if available; it must not refresh `observedAt` on a cache hit.

While the workbench is visible, a 10-second timer refreshes this read-only
snapshot; showing the workbench again also refreshes it. Home uses the original
board's rank, score and penalty, displaying cached observation time explicitly.
Without a snapshot, rank/penalty stay unknown and the local confirmed solve count
remains available. This read path never joins a team or inserts a submission.

Problemset statement is a normal QOJ problem link opened in a new tab. There is
no `problem.pdf` operation or automatic Firefox PDF export in 0.2.0. The navigation
uses the original DOMjudge 9.0.1 trophy dropdown; New contest remains on Home.

Scoreboard identity includes origin, contest, run, rule, count, ratio, at and from. Opening is serialized. Automatic delivery stops when more than one tab can write the same original-site storage slot; the user keeps one before continuing. Acknowledgements are scoped to both source submission and destination, and rejudging an already delivered result requires review.

## Verified submission timestamps

Native-VP history can display only `HH:MM:SS`. That string never establishes an
absolute timestamp or an official VP start. A refresh of a running local session
may read submission details and verify exactly one table row containing the
expected same-origin SID, owner, contest/problem link and `Submit time` cell with
an explicit-zone `time.uoj-time[datetime]`. Unrelated dates, execution-time cells,
missing zones and ambiguous/mismatched identities cannot supply the timestamp.

A verified absolute timestamp is persisted and reused across tasks/restarts.
Unverified detail attempts have a 60-second negative cache; the historical-time
probe stage is capped at three details per refresh, fairly rotating untried and
oldest retries. Prepared sessions do not trigger this historical probe. Explicit
reconciliation gives its requested SID priority, without automatically associating
an unknown intent. Backfill does not invent an official VP start or override the
local session window; records without a verified time remain out of its queue.

## Prepared resources

- `resource_manifest {sessionId}` → `{origin,account,contestId,problems:[entry]}`.
  Pure offline metadata read; missing entries remain unknown.
- `prepare_resource {sessionId,problemId,interactiveHint?:bool}` → entry. Reads QOJ
  with the actual upstream download/organize implementation; allowed before the
  local timer starts. A failed attempt never establishes absence.
- `resource_chunk {sessionId,problemId,resourceId,offset,maxBytes?}` →
  `{problemId,resourceId,offset,bytesBase64,nextOffset,eof,totalBytes,sha256,chunkSha256}`.
  Pure offline cache read; each chunk is at most 262144 bytes and the whole ZIP
  at most 67108864 bytes.

Entry: `{problemId,status:'ready'|'unknown',lastAttempt?}`. Ready entries also
contain `kind:'samples'|'attachment'`, opaque `resourceId`, safe `filename`,
`totalBytes`, `sha256`, `sampleCount`, `pairCount`, `files`, `extraFiles`,
`sampleSource`, `preparedAt`, and optional `interactiveHint`. New unknown entries
do not advertise a downloadable ID. Failed refreshes preserve the previous ready
object and set `lastAttempt.status='unknown'`; UI must distinguish retained bytes
from a newly successful attempt. No current path produces verified-none.

Cache scope is QOJ origin/account/contest/problem. The helper stores atomic
manifests and content-addressed files under its private state directory, without
returning local filesystem paths or storing credentials in the manifest.
The UI displays only verified ready controls, labels extras/mixed packages as
attachments, reuses ready entries by default, and prepares missing entries
serially. Explicit interactive hints prohibit reuse of old inline-statement
samples as ordinary interactive-task samples.

Downloads validate chunk identity, monotonic offsets/size/EOF, chunk SHA and full
SHA using WebCrypto before creating a Blob download. A mismatch never falls back
to a guessed QOJ URL. `resourceReading` locks preparation while the current
manifest promise is unresolved; read-only UI diagnostics expose the flag.

## Original-site preparation entry

Only the observed current QOJ top-level `/contest/<cid>` form is supported:
`form#form-regvir[method=POST]`, same-origin/cid action, hidden `_token`, and
`button#button-submit-regvir[type=submit][name=submit-regvir]`.
The content script inserts sibling `type=button` controls without changing or
submitting the original form. Unknown later server confirmation pages are not
inferred from older UOJ implementations.

`vp.resources.prepareContest {cid}` is accepted only from this extension's
top-level QOJ contest content sender, with matching live tab URL/cid. It reads
the actual account, coalesces account/cid work, prefers matching prepared
sessions, reuses running sessions without changing timers, or creates a prepared
session without startAt. Existing ready resources are reused; unknown entries
are prepared serially. `vp.resources.progress` sends counts to that contest tab.

`vp.resources.openContest {cid,sessionId?}` revalidates account/cid and opens the
matching `ui.html?session=<UUID>&resources=1`. Normal initialization selects that
session before opening the resource modal. Neither message starts a QOJ VP or
sends source code. Home retains the same preparation modal as a fallback.

## HTTP seam

The Python adapter receives requests-compatible browser transport. All QOJ fetches run in an original-site tab with the browser's own cookies. Requests may include multipart fields and base64 files for one explicit submit. Browser validates origin, method and task authorization. GET can be retried on transient read failures; POST is never retried implicitly. Redirect receipt must come from an observed status/Location, not an invented submission ID. The real Firefox fixture regression confirms the observational webRequest bridge for 302 with Location, and refuses confirmation for 503 or opaque 302 without Location; it never replays an uncertain POST. Persisted diagnostics contain bounded safe metadata, not request credentials or replayable nonce bindings.

No cookie export/import, login UI inside workbench, password storage, disabling Firefox sandbox, or overwriting VM `/usr/local/bin/submit`.

## Verification

Meaningful integration tests cover QojClient at a controlled fixture, uncertain
receipts, explicit reconciliation, history/verdicts, resource caching and original
RankLand recovery. Resource browser acceptance distinguishes offline file reads
from whole-page offline bootstrap. Official 9.0.1 server-rendered snapshots and
original assets are replayed in the same Firefox for computed-style/field/modal
comparison; this does not claim a live VM DOMjudge backend or full-page pixel
equality. Home is captured separately, not certified for parity: its Contest
controls adapt the original Clarifications area. The 0.2.0 navigation and snapshot
changes require fresh regression results; earlier counts are historical evidence.

The one real QOJ source POST is submission 3331061, now AC and explicitly linked
through normal reconciliation UI. Do not send another real source POST or create
an official VP to finish acceptance. The earlier RankLand delivery/reopen,
C samples and Changchun preparation entry/I (22918) attachment checks are recorded
in MVP_RESULT.md. Its PDF evidence describes the retired 0.1.0 export implementation;
it is not the current statement behavior. Real old native submission
1511772 also obtained a verified absolute timestamp through production refresh;
the current queue still contains only 3331061, synced. The original real receipt
loss remains unexplained; no later real source POST re-tested automatic receipt.
The current GitHub CI tests and packages XPI/wheel/source without user state.
Hydro Firefox CI requires a separately provisioned, registered runner and explicit
enablement; it has not yet run on a dedicated CI VM. See CI.md. Temporary Firefox
installation ends at browser restart; AMO unlisted signing for normal persistent
installation is planned, with no signing credentials configured and no global
signature preference changes.
