#!/bin/sh
set -eu
task_root=/home/csj/.local/share/qoj-vp-mvp/2026-10-31
mkdir -p "$task_root/results"
cd "$task_root"
export MOZ_HEADLESS=1
export MOZ_NO_REMOTE=1
export PYTHONPATH="$task_root:$task_root/preflight/vendor_py:$task_root/vendor/qoj-submitter"
exec /usr/bin/python3 -B -u "$task_root/preflight/guest_mvp.py" "$@" > results/mvp.stdout 2> results/mvp.stderr
