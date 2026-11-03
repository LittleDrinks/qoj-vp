# QOJ native VP integration — 0.3.5

The preparation entry lives on `/contest/<cid>/virtual/register`, next to the
original QOJ Start form. **准备比赛文件并打开工作台** binds the current account and
contest, reuses the existing prepared session and automatically prepares its
resources. The normal Python helper is reused and exits after each operation.

Clicking QOJ's own **Start!** starts the native VP. Once its active dashboard is
verified, the workbench adopts that start and opens Home. There is no second
local Start step. For a direct Start without resource preparation, the content
script captures the registration rules before the POST makes that page
unavailable. The account, contest, form and rules are validated again by the
helper. No CSRF inputs, source code, cookies or passwords belong to that snapshot.

## Start and recovery

The browser observes the native form and its actual main-frame POST; it never
cancels, replaces or retries the registration request. Source submission remains
a separate explicitly confirmed operation. A pending start survives an event
page/browser restart and can recover when Firefox has a matching QOJ page open.
The retry window is 24 hours. Observing a historical contest without a pending
start does not silently import it.

For the observed QOJ page, the formula is:

`startAt = server footer timestamp + server countdown remaining - verified duration`

All time operands come from the provider, including the footer timezone. The
local click and network response-arrival times are not used. Unsupported clocks
stay unconfirmed. An already confirmed start cannot be reset by duplicate
callbacks, late preparation, an old UI snapshot or a conflicting provider clock.
The frozen RankLand replay target is preserved on repeated confirmation.

QOJ-bound contests show **前往 QOJ 开始** in Jury; hand-created local practices
retain their existing **Start now** behavior. Resource preparation continues
through the successful Start transition without reloading the workbench.

## Real VMware check, 2026-11-03

The user authorized end-to-end testing on QOJ **2644**, the CCPC 2025 Zhengzhou
warm-up. In the normal Hydro Firefox ESR profile:

- The new control appeared on the actual registration confirmation page.
- One preparation click reused the existing account-scoped prepared session and
  opened its resource modal. A/B/D had verified samples; C/E stayed unconfirmed.
- The original QOJ Start button was clicked once and the native five-hour VP
  began. No solution source was submitted.
- Raw response 1: server time `18:07:28 UTC+8`, `data-rest=17384` seconds.
- Raw response 2: server time `18:09:33 UTC+8`, `data-rest=17259` seconds.
- Both independently reconstruct **2026-11-03 17:57:12 UTC+8**, Unix milliseconds
  **1793699832000**, using the 300-minute registration rule.
- After deploying the clock parser, the saved intent recovered automatically at
  about 18:20, retained that original start, opened Home and cleared the intent.
  The preparation session was reused; no replacement session or second VP was
  created.

The delayed confirmation above was caused by development/verification, and is
also an observed recovery after roughly 22 minutes. It does not measure normal
start-notification latency. Marionette initially triggered QOJ's security check;
normal Firefox access and the existing login were retained for the successful
run. Browser state was inspected with guest-only input, without activating the
Windows host window.

Local sanitized evidence is under `artifacts/prepare-entry-20261103/`, including
`native-active.json`, `native-active-full.json` and the final VM state capture.
Automated tests cover direct Start without prior preparation, original POST
observation, failed/unknown responses, account mismatch, changed/closed tabs,
restart recovery, repeated confirmation and asynchronous UI/preparation races.

## RankLand SDUT compatibility

The live public metadata for `sdutpc14` and `sdutpc18_warmup` omits problem
metadata. The resolver now follows the original site's public file reference to
its SRK JSON, verifies file ownership/size/SHA-256, and caches compact metadata.
Live production resolution found A–J / 4 hours for `sdutpc14`, and A–M / 2 hours
for `sdutpc18_warmup`.

Neither file supplies QOJ problem links matching QOJ 2644 (5 problems, 5 hours).
They were checked independently, not linked into an unrelated replay. This is
live metadata compatibility, not a claim that QOJ-to-SDUT submission transfer
was exercised. The existing original-RankLand fixture regression covers result
transfer; details of this lookup are in
[the SDUT investigation](research/2026-11-03/rankland-sdut-metadata.md).

Both extension and helper must be upgraded to 0.3.5.

## Automated checks

Python: 187 passing tests, including 22 native VP cases. Node: 233 passing tests,
including 29 lifecycle cases and the full UI startup/resource flow. Mozilla
validation: zero errors and three existing warnings (Android minimum-version
metadata and two unmodified Bootstrap assignments).
