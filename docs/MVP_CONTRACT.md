# MVP implementation contract

2026-11-03, 0.3.5 native QOJ VP start integration and delayed-result synchronization. QOJ only; no CF/Gym or custom scoreboard.
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
- `qoj_bind_virtual {contestId,registrationPage?}` → `{session,contest,virtual}`. Read-only binding to the current QOJ account and verified registration rules; reuse the same prepared/native session. The optional `{url,html}` is a minimal token-free registration DOM captured before the original POST and validated by the background sender guard. The helper independently checks the live account, contest, form and rule identity.
- `qoj_confirm_virtual_start {sessionId}` → `{session,contest,virtual}`. Read the real dashboard and atomically adopt the QOJ start. The observed server countdown and footer timestamp belong to one response; the duration comes from the same contest's registration rules. No local click or response-arrival clock supplies startAt. Unknown clocks stay unconfirmed; conflicting clocks cannot reset an existing session.
- `list_sessions {}` → `{sessions:[session]}`; `inspect_session {sessionId}` → session; `archive_session {sessionId}` → session.
- `update_session {sessionId,title?,durationMs?,ranklandUrl?}` → session. Title and duration are editable only while prepared; duration is an integer from 1 ms through 14 days. RankLand target settings retain their existing behavior in other states.
- `finish_session {sessionId}` → session with `state:'finished'` and `finishedAt`. Ends only the local participation window and freezes elapsed time; it does not contact either original site. Prepared/future-start sessions are rejected; repeated finish does not change the recorded end.
- `delete_session {sessionId,confirmed:true}` → `{deleted:true,sessionId}`. Only prepared, archived or effectively finished local sessions may be deleted. Unconfirmed source intents block deletion even after archiving; see the lifecycle boundaries below.
- `prepare_rankland {sessionId}` → session with `ranklandPrepared=true`: before first scoreboard opening, freeze the current fractional-minute `from` in the durable URL; later opens reuse it exactly. A past `at` alone does not advance a newly opened original-site replay.
- `qoj_contest {contestId}` → `{id,name,account,problems:[{id,label,name,url}],source}`. Account null means user must log in to QOJ normally.
- `qoj_problem_form {sessionId,problemId}` → `{problemId,languages:[string],csrfPresent,pdfCandidates:[{url,text}],statementUrl}`. Never return CSRF value to UI.
- `qoj_samples {sessionId,problemLabel}` → `{zipFilename,zipBase64,files,warnings,extraFiles}`. Legacy single-problem CLI method remains; the UI uses the resource cache methods below.
- `qoj_submit {sessionId,problemId,problemLabel,language,filename,contentsBase64,operationId}` → `{submission,state}`. Confirmed receipt state `confirmed`; uncertain state `unknown` never silently retried. Submission shape below.
- `qoj_submissions {sessionId,refresh?:true}` → `{submissions:[submission],account,coverage:{complete,pages,warning?}}`. Refresh collects same-account original-site history/detail and persists updates; uncertain outcomes require reconciliation before resubmission.
- `rankland_plan {sessionId}` → `{sessionId,items,waiting,allItems,pendingCount,blockedCount,planToken}`. `items` is the complete desired owned projection, sorted by verified submission time and numeric provider ID. Same-problem pending or unknown earlier submissions hold later final results. `allItems` also includes withdrawal candidates.
- `rankland_ack_batch {sessionId,acknowledgements,planToken}` atomically acknowledges every current `allItems` ID and revision, or rejects a stale plan. An empty plan uses an empty batch. Applied withdrawal is acknowledged without inventing a new result.
- `refresh_sessions {}` → `{sessions}` with `refreshRequired` and `syncRequired`. Started, unarchived sessions remain eligible after the deadline while outcomes, complete post-deadline history or projection acknowledgements are outstanding.

Session: `{sessionId,contestId,title,account,startAt,durationMs,state,effectiveState,elapsedMs,ranklandUrl,createdAt,finishedAt?}`. Keep exact durable URL, including stable unique run, not a browser tab ID. Time is derived from a timestamp, never a permanently running Python timer.

Native-bound sessions also carry `qojVirtual` with mode, origin, contest, account,
verified duration and optional confirmed start/timeSource/serverNow/remainingMs.
`start_session` rejects a prepared native binding; the UI opens QOJ's original
registration page instead. Content code never cancels or programmatically
submits its Start form. A main-frame POST observer covers native JavaScript
form submissions too. Durable start intents retry for up to 24 hours while a
matching QOJ tab exists; closing Firefox suspends retries. A later page visit
without an intent does not start or import an old VP. Minimal pre-POST rules
are kept locally for this handshake and removed with the completed intent.
Late prepared snapshots cannot replace a confirmed start or reload the running
resource preparation page. No native task is permitted to POST registration.

The local submission/outbox interval ends at the earlier of `startAt+durationMs`
and explicit `finishedAt`; ending a practice does not shorten its configured
duration or alter a frozen RankLand URL. A new send intent rechecks the session
inside its transaction, so finishing during form lookup cannot send code after
the local finish. Existing unknown intents retain the normal reconciliation path.

Deletion checks state, confirmation and unresolved source operations in one
transaction, then removes only that session's operations, history associations
and outbox. Provider facts are removed only if no other local session references
them. Account/contest-scoped resource objects and verified contest snapshots are
shared and retained. Deletion never removes QOJ submissions, a RankLand run or
original-site storage. These local controls are not QOJ contest administration.

Submission: `{id,operationId?,problemId,problemLabel,language,filename?,submittedAt,elapsedMs,verdict,rawVerdict,score?,pending,url,state}`. `id` is provider submission ID when confirmed. DOMjudge verdicts include CORRECT, WRONG-ANSWER, TIMELIMIT, RUN-ERROR, COMPILER-ERROR, NO-OUTPUT, OUTPUT-LIMIT, JUDGING, UNKNOWN. Preserve raw observations; 0 score alone is insufficient to select WA.

The default Home table renders only `inSession === true` or a nonempty
`operationId`, without mutating the full history/ledger. Own unknown, sending,
rejected and confirmed operations stay visible even outside the local window.
Outside-window rows display no elapsed time (an em dash); the title retains the
absolute date and the reconciliation/details entry stays available. Remaining
history is accessible through the original-site history link. A prepared session
without current/local operations keeps the original No submissions state.

Additional browser methods: `rankland.open {sessionId}` restores the exact
original-site URL; `rankland.sync {sessionId}` first refreshes QOJ, delivers the
current projection and enables later automatic delivery. QOJ outages preserve
the retry intent. Automatic delivery may reopen the exact board in an inactive
tab while Firefox is running; closing Firefox suspends polling.
`rankland.snapshot {sessionId}` returns `{state,snapshot,reason?,url,syncStatus?}` with state
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
no `problem.pdf` operation or automatic Firefox PDF export since 0.2.0. The player
navigation uses the original DOMjudge 9.0.1 trophy dropdown to switch contests.
Creation, configuration, local finish/deletion and manual resource preparation
belong to the separate Jury view: Jury → Contests → Add new contest. They are not
player Home actions. The Jury layout follows the official administrator entry
structure while its local-session semantics remain an extension adaptation.

Scoreboard identity includes origin, contest, run, rule, count, ratio, at and from.
Opening is serialized. Automatic delivery stops when more than one tab can write
the same original-site storage slot. The adapter pins the supported bundle path
and archive schema, navigates the old replay away to finish its writes, then
compares and replaces its owned records using a durable journal and backup.
The original application restores the archive and recalculates its scoreboard.
Unchanged records do not reload the page. Owned rejudgements replace or withdraw
earlier results; unowned manual records remain. Conflicting manual edits or
ambiguous ownership require review. Acknowledgements cover the entire current
plan, including source revisions and destination identity. Implementation and
compatibility limits are recorded in [0.3.4 synchronization](RANKLAND_SYNC_0.3.4.md).

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
  Offline validated cache read, including lazy migration of older entries;
  missing entries remain unknown. Migration makes no QOJ request.
- `prepare_resource {sessionId,problemId,interactiveHint?:bool}` → entry. Reads QOJ
  with the actual upstream download/organize implementation; allowed before the
  local timer starts. A failed attempt never establishes absence. A verified
  manual sample entry is returned locally without requesting QOJ or overwriting it.
- `import_samples {sessionId,problemId,zipBase64?,files?,confirmedReplace?}` → ready
  entry. Exactly one of ZIP base64 or `files:[{name,base64}]` is required. This is
  an offline import with the ownership, confirmation and size checks below.
- `resource_chunk {sessionId,problemId,resourceId,offset,maxBytes?}` →
  `{problemId,resourceId,offset,bytesBase64,nextOffset,eof,totalBytes,sha256,chunkSha256}`.
  Pure offline cache read; each chunk is at most 262144 bytes and the whole ZIP
  at most 67108864 bytes.

Entry: `{problemId,status:'ready'|'unknown',lastAttempt?}`. Since 0.2.1, ready
entries contain `downloads:[descriptor]`, with one or two independently
downloadable ZIPs, ordered samples before attachment. A descriptor contains
`{problemId,problemLabel,status:'ready',kind:'samples'|'attachment',filename,
resourceId,totalBytes,sha256,sampleSource,preparedAt,interactiveHint,sampleCount,
pairCount,files,extraFiles}`. `files` contains `{name,bytes,sha256}` for each ZIP
member. Each descriptor's size, SHA and file list describe only its own ZIP.

Complete same-stem `.in` / `.ans` pairs under `samples-X/` enter
`samples-X.zip`. Everything else enters `attachments-X.zip`: the entire original
`attachment-extras/problem-X/` tree, including its original `.in` / `.ans` files
and tool dependencies, plus unpaired generated sample items. Complete generated
sample copies do not also appear in the attachment ZIP. No original attachment
member is discarded. The samples descriptor counts its complete pairs; the
attachment descriptor has `sampleCount=pairCount=0` even if its preserved original
tree contains sample files.

The entry's top-level `kind`, `resourceId`, `filename`, `totalBytes`, `sha256`,
`sampleCount`, `pairCount`, `files`, `extraFiles`, `sampleSource`, `preparedAt` and
optional `interactiveHint` remain the legacy combined-object metadata. New UI
controls consume `downloads`; the combined ID is retained for older callers.
For a single-kind resource the descriptor reuses the top-level object without
copying it. Mixed resources retain that object and add two separate ZIP objects.

New unknown entries advertise no downloadable ID or descriptors. Failed refreshes
preserve previous ready downloads only after verification and set
`lastAttempt.status='unknown'`; UI must distinguish retained bytes from a newly
successful attempt. No current path produces verified-none.

Cache scope is QOJ origin/account/contest/problem. The helper stores atomic
manifests and content-addressed files under its private state directory, without
returning local filesystem paths or storing credentials in the manifest.
Old schema-1 entries without `downloads` migrate on an offline manifest read;
a legacy chunk request also migrates before serving bytes. Migration validates
the original ZIP size/SHA and each member's name, size and SHA, rejects unsafe
paths, links and duplicate members, and enforces at most 2000 members / 128 MiB
expanded data. Child objects publish before the updated manifest, using a
per-problem lock and atomic writes. The original combined object is retained.
Invalid caches are not advertised as ready.

The UI displays a samples button and/or an attachment button from the verified
descriptors, reuses ready entries by default, and prepares missing entries
serially. Explicit interactive hints prohibit inline-statement fallback and
reuse of old inline-statement samples as ordinary interactive-task samples.
They do not suppress complete paired samples obtained from official attachments;
those may be downloaded separately from the interactor or other tools.

`resource_chunk` accepts only a descriptor ID or legacy top-level ID explicitly
bound by the current account/contest/problem manifest. It validates the selected
ZIP's size and SHA for each chunk, without decompressing members again. ZIP member
validation takes place on storage, manifest reads and legacy migration.

Downloads validate chunk identity, monotonic offsets/size/EOF, chunk SHA and full
SHA using WebCrypto before creating a Blob download. A mismatch never falls back
to a guessed QOJ URL. `resourceReading` locks preparation while the current
manifest promise is unresolved; read-only UI diagnostics expose the flag.

### Manual sample imports

Imports require an account-bound session and a problem in the verified
account/contest snapshot saved by successful QOJ reads. Older scoped resource
metadata with a verified label also permits import when no snapshot exists.
An arbitrary problem list supplied by a caller cannot authorize an import;
missing ownership data returns `CONTEST_NOT_CACHED` and requires a separate
contest read. The import itself never makes network requests.

Individual files and ZIP content allow at most 1000 members, 4 MiB per file and
8 MiB total uncompressed bytes. ZIP directory entries count toward the member
limit; the uploaded ZIP is also at most 8 MiB. Unsafe/duplicate paths, symlinks,
encrypted or special members, malformed archives and unsupported compression
are rejected; stored and deflated ZIPs are accepted. No archive is extracted to
a user-selected path. Files must be complete same-stem `.in` plus `.ans` or
`.out` pairs; unrelated files, partial pairs and dual `.ans`/`.out` answers fail
validation. Pairs normalize to naturally ordered numbered `.in`/`.ans` files
under `samples-X/` while preserving every input/output byte.

If samples already exist, import requires `confirmedReplace:true` regardless
of their original source. The old attachment descriptor and object are retained
unchanged, including tool dependencies and incomplete inputs. New numbering
skips names occupied by those incomplete files. The helper builds and verifies
the new combined object before publishing a complete manifest under the resource
lock. The entry is marked `manualSamples:true` and `sampleSource:'manual'`; its
samples descriptor has manual provenance, while attachment provenance stays
unchanged. Automatic prepare/refresh, including a provider write racing the
import, cannot silently replace manual samples.

Incoming native frames allow 96 MiB. The maximum 8 MiB import encodes to about
10.7 MiB base64 plus bounded JSON and filenames, below that limit. The response
contains metadata only and stays within the existing 1 MiB outgoing ceiling;
ZIP download bytes continue through 256 KiB chunks. The maximum upload size is
verified through the real host framing entry in the Python suite; a fully
offline workbench bootstrap is still outside this interface guarantee.

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
session before opening the resource modal in the Jury view. Neither message
starts a QOJ VP or sends source code. Jury retains the same preparation modal
as a fallback.

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
equality. Home is captured separately, not certified for parity. Administration
is a separate Jury view adapted to local practice sessions. Current 0.3.0 changes
require fresh regression results; earlier counts are historical evidence.

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
