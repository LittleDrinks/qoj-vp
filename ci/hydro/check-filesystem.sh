#!/usr/bin/env bash
set -euo pipefail
disk=${1:?Filesystem image required}
status=0
e2fsck -f -y "$disk" || status=$?
# Exit 1 means repairs completed; uncorrected errors (4+) must still fail.
if ((status != 0 && status != 1)); then exit "$status"; fi
# Require a clean, read-only second pass before packaging the image.
e2fsck -f -n "$disk"
