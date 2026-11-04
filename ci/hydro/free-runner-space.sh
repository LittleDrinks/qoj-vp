#!/usr/bin/env bash
set -euo pipefail
# Only disposable hosted GitHub runners; never user's workstation or self-hosted VM.
test "${GITHUB_ACTIONS:-}" = true
test "${RUNNER_ENVIRONMENT:-}" = github-hosted
sudo rm -rf /usr/local/lib/android /usr/share/dotnet /usr/local/.ghcup /opt/ghc /usr/local/share/powershell /opt/hostedtoolcache/CodeQL
sudo docker image prune -af
df -h /
