#!/usr/bin/env bash
set -euo pipefail
# Only disposable hosted GitHub runners; never user's workstation or self-hosted VM.
test "${GITHUB_ACTIONS:-}" = true
test "${RUNNER_ENVIRONMENT:-}" = github-hosted
required_gib=${1:-110}
[[ "$required_gib" =~ ^[1-9][0-9]*$ ]]
required_bytes=$((required_gib * 1024 * 1024 * 1024))
available_bytes() { df -B1 --output=avail / | tail -1; }
df -h /
if (( $(available_bytes) >= required_bytes )); then
  echo "Enough disk space (${required_gib} GiB required); skipping cleanup."
  exit 0
fi
sudo rm -rf /usr/local/lib/android /usr/share/dotnet /usr/local/.ghcup /opt/ghc /usr/local/share/powershell /opt/hostedtoolcache/CodeQL
sudo docker image prune -af
df -h /
(( $(available_bytes) >= required_bytes ))
