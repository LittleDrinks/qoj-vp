#!/bin/sh
set -eu
task_root=/home/csj/.local/share/qoj-vp-preflight/2026-10-31
mkdir -p "$task_root/results/extension-diagnostics"
cd "$task_root"
export PYTHONPATH="$task_root/vendor_py:$task_root/vendor/qoj-submitter"
export MOZ_HEADLESS=1
export MOZ_NO_REMOTE=1
exec /usr/bin/python3 -B -u "$task_root/guest_extension_diagnostics.py" "$@" > results/extension-diagnostics/stdout.log 2> results/extension-diagnostics/stderr.log
