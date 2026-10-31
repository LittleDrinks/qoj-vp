#!/bin/sh
set -eu
task_root=/home/csj/.local/share/qoj-vp-preflight/2026-10-31
export QOJ_PREFLIGHT_ADDON_INSTALL=path
exec /bin/sh "$task_root/job-extension-diagnostics.sh" --probe-injection --output "$task_root/results/bridge-diag-4-path"
