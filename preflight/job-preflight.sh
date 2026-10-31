#!/bin/sh
set -eu
task_root=/home/csj/.local/share/qoj-vp-preflight/2026-10-31
mkdir -p "$task_root/results" "$task_root/state"
cd "$task_root"
export PYTHONPATH="$task_root/vendor_py:$task_root/vendor/qoj-submitter"
export MOZ_HEADLESS=1
export MOZ_NO_REMOTE=1
exec /usr/bin/python3 -u "$task_root/guest_preflight.py" > results/preflight.stdout 2> results/preflight.stderr
