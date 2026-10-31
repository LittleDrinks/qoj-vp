# Official DOMjudge 9.0.1 visual reference

This is the real `domjudge/domserver:9.0.1` image with its original PHP/Twig
rendering, not a hand-written clone. It runs only a web server and MariaDB.
There is no judgehost, so submitted programs cannot execute.

- WSL URL: `http://127.0.0.1:19081/`
- Team pages: `/team`, `/team/problems`, `/team/submit`
- API version evidence: `/api` reports `domjudge.version = 9.0.1`.
- Image digest: `sha256:e9704bdae8e08440eb0042c9817116dc9767a511f577e9318c4f0710ad5b5727`.
- Containers/network/volume all use the independent `qoj-vp-domjudge-ref` prefix.
- The database publishes no port. Only the web port binds to loopback.

The official image instructions are at
<https://hub.docker.com/r/domjudge/domserver/>; packaging source is
<https://github.com/DOMjudge/domjudge-packaging>.

## Start and inspect

From the repository root:

```sh
python3 preflight/visual-reference/prepare.py
docker compose -f preflight/visual-reference/compose.yaml -p qoj-vp-domjudge-ref up -d
python3 preflight/visual-reference/reference.py
python3 preflight/visual-reference/seed_xian.py
python3 preflight/visual-reference/configure_reference.py
python3 preflight/visual-reference/export_rendered.py
python3 preflight/visual-reference/export_assets.py
```

`reference.py` creates a dedicated visual-reference team account through the
original REST API. Its credentials are in ignored mode-600
`private/team-credentials.json` (keys: `baseUrl`, `username`, `password`, `teamId`);
read them locally for login without printing or
committing them. Database credentials are also generated privately. Do not dump
container startup logs, because the official image prints its initial passwords.

`artifacts/visual-reference/service.json` records actual HTTP statuses, version,
image digest, and asset hashes. `xian-seed.json` records fixture metadata. These
artifacts contain no credential values. The default demo is also available.

## Literal HTML reference

`rendered/` contains actual response HTML, with all hidden CSRF token values
replaced by `CSRF_TOKEN_REDACTED`. Markup, classes, inline styles and whitespace
are otherwise preserved. These snapshots are evidence for the UI implementation,
not standalone pages: external resources and server routes still belong to the
original DOMjudge service.

- `navbar.html` / `navbar-submit.html`: original team navbar / Submit anchor.
- `card-a.html` / `card-submit.html`: original first problem card / Submit anchor.
- `submit-modal-generic.html`: `/team/submit` requested with
  `X-Requested-With: XMLHttpRequest`.
- `submit-modal-a.html`: `/team/submit/4` requested with that same header.
- `home.html`, `problemset.html`, `submit-page.html`: complete team pages.
- `manifest.json`: capture paths, metadata, and sanitized snapshot hashes.
- `configuration.json`: actual 12-problem limits/types/colors and reference
  configuration, with explicit limits on whole-page pixel comparisons.
- `site-assets/`, `site-assets.tar.gz`, `site-assets-manifest.json`: all resources
  referenced by the actual page HTML and CSS, preserving original URL paths.

For a new session, fetch `/login`, keep its token only in memory, submit login,
then fetch the desired page or AJAX modal and redact its token before export.
The export script performs this flow and does not print tokens.

The reference uses the official `sourcefiles_limit = 1` setting, changed through
its original Symfony/Doctrine console; no application source is modified. The
original source field then renders **Source file**, without `multiple`, and uses
the name `submit_problem[code]`. The export script verifies these properties.
The same official configuration mechanism sets `show_public_stats = false` and
`show_limits_on_team_page = false`. `DOMJudgeService::getTwigDataForProblemsAction`
checks those exact keys, and the original Twig omits the histogram and Limits
row accordingly. The Type row remains unconditional in the original template.

The original per-problem modal hides its selected Problem selector inside
`div.d-none`. The generic modal displays it. The original source field accepts
one file under this configuration. Differences deliberately required by the QOJ backend should be
recorded explicitly when adapting the literal reference.

## Xi'an display fixture

The active reference contest is `qoj-vp-xian-reference` (internal CID 2), with the
title **The 2022 ICPC Asia Xi'an Regional Contest**. It has 12 problems A–L,
internal IDs 4–15 and external IDs `xian-a` through `xian-l`. Titles come from
the public RankLand SRK:
<https://cdn.algoux.cn/rankland/file/94031158458802176/icpc2022xi_an.srk.json>.
The team is `exteam` (internal ID 2).

Attached PDFs and samples are explicitly marked display fixtures. They are not
the real contest statements or samples and must not be used for solving. They
exist so original DOMjudge renders its actual statement/sample controls.

All seeded problems are pass-fail (`types = 1`), have a two-second time limit,
use the default 2,097,152-KiB memory and 8,192-KiB output limits, and allow
submission while disabling judging. Original cards display `Limits: 2 seconds /
2 GB` when limits are enabled; this profile hides that row and statistics through
official flags while retaining `Type: pass-fail`. Each
problem color is now `NULL`, matching QOJ's absent color metadata; the actual
original renderer uses a white `#ffffff` badge, `#bfbfbf` border and black
`#000000` text. `rendered/configuration.json` records this metadata. These values are not
claims about the real QOJ problems. A whole-page pixel comparison must align
metadata, visible controls, timestamps, viewport and control states first.

## Offline browser replay

The actual service remains the authoritative renderer. If VM-to-WSL networking
is unavailable, a VM loopback fixture may serve the frozen HTML and assets
verbatim for comparison in the same Firefox. This is an **original service
snapshot replay**, not a running DOMjudge backend. It must not manufacture a
DOMjudge API/version response or claim to exercise backend behavior.

`site-assets-manifest.json` maps each original absolute path to `mirrorPath`,
`sha256`, `bytes`, `contentType` and its capture source. All static responses are
byte-verified against the actual running official image file. The dynamic
`/public/scoreboard-category-color.css` is captured by a real GET from the
reference service. Only response resource bytes and selected public metadata are
saved, never authentication headers or cookies. Query strings such as `?v=9.0.1`
do not change the local file mapping.

Serve `/team/submit` with the generic AJAX response when the request has
`X-Requested-With: XMLHttpRequest`, and `/team/submit/4` with the A response.
Serve `submit-page.html` for non-AJAX `/team/submit`. The reference archive
includes jQuery, debounce, Bootstrap, DOMjudge JS, all CSS, the referenced four
Font Awesome font families in WOFF2/TTF, favicon and flag. Existing manifest
hashes should be checked before the replay starts.

## Asset and state comparison

The image's `style_domjudge.css`, Bootstrap 5.3.7 CSS/bundle JS, and Font Awesome
Free 6.5.2 CSS match the current extension files byte for byte. The image's three
WOFF2 font files differ from the previously downloaded same-version font files;
the actual image bytes are exported under `rendered/assets/fontawesome/webfonts/`.
`service.json` contains their SHA-256 values. Hash inequality alone does not prove
a glyph difference.

Original `style_domjudge.css` sets `.btn-success { background: #0a8927; }`.
Compare normal, hovered, active and disabled controls in matching states. Disabled
opacity can make an otherwise identical button appear lighter.

## Local startup findings

The host's existing Docker networks exhaust the default address pools. This
project therefore uses an explicitly overlap-checked `198.18.253.0/24` network;
no pre-existing networks were removed or modified. MariaDB's default packet limit
rejected the official demo problem import with `max_allowed_packet` / SQLSTATE
2006. The owned database is configured with `--max-allowed-packet=512M`, after
which the unchanged official application starts and both containers are healthy.

To stop the reference while preserving its data:

```sh
docker compose -f preflight/visual-reference/compose.yaml -p qoj-vp-domjudge-ref stop
```

Do not use global Docker prune commands. This project shares the Docker daemon
with unrelated work.
