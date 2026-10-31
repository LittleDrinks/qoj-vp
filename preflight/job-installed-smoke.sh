#!/bin/sh
set -eu
task_root=/home/csj/.local/share/qoj-vp-mvp/2026-10-31
mkdir -p "$task_root/results/installed-smoke"
cd "$task_root"
/usr/bin/python3 -B "$task_root/scripts/install_native.py" --dependencies "$task_root/preflight/vendor_py" > results/installed-smoke/install.log 2>&1
export PYTHONPATH="$task_root:$task_root/preflight/vendor_py:$task_root/vendor/qoj-submitter"
export MOZ_HEADLESS=1
export MOZ_NO_REMOTE=1
exec /usr/bin/python3 -B -u "$task_root/preflight/guest_installed_smoke.py" > results/installed-smoke/stdout.log 2> results/installed-smoke/stderr.log
