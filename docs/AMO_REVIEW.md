# Mozilla review notes

QOJ VP Workbench is a self-distributed Firefox extension for Linux desktop. It
adapts DOMjudge 9.0.1 team pages to QOJ and the original RankLand scoreboard. It
needs a Python native-messaging host installed by the same desktop user. The
host starts for a task and exits; there is no always-running web server.

## Reproduce the XPI

The source archive contains committed project files and the exact pinned
`vendor/qoj-submitter` submodule, plus `SOURCE_COMMIT` and file SHA-256 hashes in
`SOURCE_MANIFEST.json`. It contains no login, profile or contest database.

On Ubuntu 24.04, Python 3.12:

```sh
python3 scripts/package_extension.py
```

This zips the files in `extension/` without transpilation, minification or code
generation. Archive timestamps/compression need not match, but every uncompressed
extension file must match. The release verifier checks precisely that property
after AMO signing and excludes only Mozilla signature entries. It checks file
presence, not signature authenticity; Firefox checks the actual signature.

Node 24 and `npm ci --ignore-scripts` install pinned web-ext 10.8.0 from the lock
file. `npm run lint:firefox` runs Mozilla's validator. The extension runs without
Node or npm. The build currently reports no errors and three warnings: desktop
140 data-consent compatibility on Android, and two `innerHTML` assignments inside
unmodified Bootstrap. Distribution metadata selects desktop Firefox only.

First-party JavaScript is readable and unminified. Third-party source, release
versions, image digest and per-file checksums are documented in
[UI_UPSTREAM.md](UI_UPSTREAM.md) and `extension/assets/UPSTREAM.json`. Copies of
each applicable license are bundled. Libraries are local; no remote code is
downloaded or executed. Root code is GPL-2.0-or-later; the AMO metadata uses a
custom license because AMO's predefined GPL-2.0-only entry is narrower.

## Data flow and installation consent

Firefox 140+ is required so the installation prompt can explain the required
data types through Firefox's built-in consent system:

- `authenticationInfo`: the QOJ username identifying the account and contest.
- `websiteContent`: QOJ contest/problem/statement/submission responses and source
  files selected for submission, transferred to the local helper for parsing and
  processing; submission source is sent to QOJ only after the Submit confirmation.
- `websiteActivity`: selected contest/run, submission results and times used to
  persist practice progress and update the original RankLand page.

The extension reads only supported judge/scoreboard pages. QOJ requests use the
existing Firefox login in a QOJ content script. It does not request the cookies
API or export login cookies/passwords to Python. Account, contest and submission
state is retained in the local helper's SQLite/cache directory. Browser display
cache is separate and carries no submitted source text. Results may be passed
to the selected RankLand replay through its original controls. No developer
telemetry service is used. Native messaging is included in the declaration,
even though its destination is on the user's own machine.

Install the helper using [README.md](../README.md#安装). Do not move the source
directory after registering it, since the native launcher references that path.
The add-on ID stays `qoj-vp@littledrinks.local`; updates use the same registration
and retain existing contest state. Localhost host permissions permit isolated
QOJ-shaped HTTP fixtures used by the checked-in integration tests.

## Test without a live contest

Backend and frontend suites use fixtures:

```sh
python3 -m pip install .
python3 -m unittest discover -s tests -v
node --test preflight/test_*.cjs tests/test_*.cjs
```

For full UI/native checks in a Linux desktop Firefox, see the dedicated Hydro
fixture runner in [CI.md](CI.md). It uses isolated browser profiles and helper
state, not a user's existing account. Do not start an official QOJ virtual
contest or submit to a real contest to test the extension. Optional real
RankLand checks are separate from the offline fixture suite.

No account credentials are included with this submission. If Mozilla requires
additional authenticated tests, the owner must arrange a separate test account;
existing personal credentials must not be added to the source package or notes.
