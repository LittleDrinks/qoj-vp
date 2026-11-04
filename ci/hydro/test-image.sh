#!/usr/bin/env bash
# Run a preinstalled image. Nothing here installs the guest OS or browser tools.
set -euo pipefail
image=${1:?Image name or immutable digest required}
mode=${2:-full}
project=$(pwd)
run=$(mktemp -d "${RUNNER_TEMP:-/var/tmp}/hydro-run.XXXXXX")
mkdir -p "$run/config" "$project/results/hydro-hosted"
output="$project/results/hydro-hosted"
ssh-keygen -q -t ed25519 -N '' -f "$run/id"
cp "$run/id.pub" "$run/config/authorized_keys"
chmod 755 "$run" "$run/config"
container="hydro-ci-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
cleanup() {
  docker logs "$container" > "$output/container.log" 2>&1 || true
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$run"
}
trap cleanup EXIT
docker run -d --name "$container" --device /dev/kvm \
  -p 127.0.0.1:2222:2222 \
  -v "$run/config:/config:ro" -v "$output:/output" "$image"
ssh_args=(-p 2222 -i "$run/id" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile="$run/known_hosts" -o ConnectTimeout=5 -o ServerAliveInterval=15)
ssh_guest() { ssh "${ssh_args[@]}" hydroci@127.0.0.1 "$@"; }
ready=false
for ((attempt=0;attempt<90;attempt++)); do
  if ssh_guest true 2>/dev/null; then ready=true;break;fi
  test "$(docker inspect -f '{{.State.Running}}' "$container")" = true
  sleep 2
done
if test "$ready" != true; then tail -100 "$output/serial.log";exit 1;fi
ssh_guest 'cat /etc/hydro-ci-image.json; uname -r; /usr/bin/firefox-esr --version; /usr/bin/python3 --version' > "$output/environment.txt"
# Test the installed system survives a guest reboot (not just a browser restart).
first_boot=$(ssh_guest cat /proc/sys/kernel/random/boot_id)
ssh_guest 'printf preserved > /home/hydroci/reboot-proof; sudo systemctl reboot' || true
rebooted=false
for ((attempt=0;attempt<90;attempt++)); do
  new_boot=$(ssh_guest cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)
  if test -n "$new_boot" && test "$new_boot" != "$first_boot"; then rebooted=true;break;fi
  sleep 2
done
test "$rebooted" = true
ssh_guest 'test "$(cat /home/hydroci/reboot-proof)" = preserved'
printf '{"guestBoot":true,"guestReboot":true,"diskPreserved":true}\n' > "$output/boot.json"
if test "$mode" = smoke; then
  # A real browser launch in the installed Hydro image, before publishing it.
  ssh_guest /usr/bin/python3 - <<'PY' > "$output/firefox-smoke.json"
import json,sys,tempfile
sys.path.insert(0,'/opt/hydro-ci/vendor_py')
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
options=Options();options.binary_location='/usr/bin/firefox-esr';options.add_argument('-headless')
with webdriver.Firefox(options=options,service=Service('/opt/hydro-ci/geckodriver',log_output='/tmp/browser-smoke.log')) as driver:
    driver.get('data:text/html,<title>Hydro CI</title><p>ready</p>')
    assert driver.title=='Hydro CI'
    print(json.dumps({'firefox':driver.capabilities['browserVersion'],'headless':driver.capabilities['moz:headless'],'status':'passed'}))
PY
  exit 0
fi
ssh_guest 'mkdir -p project'
tar --exclude=.git --exclude=node_modules --exclude=.venv --exclude=artifacts \
  --exclude=dist --exclude=results --exclude=.scratch --exclude=ci/hydro/output \
  --exclude=preflight --exclude=tests/browser/vendor_py --exclude=__pycache__ -czf - . | ssh_guest 'tar -xzf - -C project'
set +e
ssh_guest 'cd project && mkdir -p tests/browser/tools && ln -s /opt/hydro-ci/vendor_py tests/browser/vendor_py && ln -sf /opt/hydro-ci/geckodriver tests/browser/tools/geckodriver && /usr/bin/python3 scripts/run_hydro_ci.py' 2>&1 | tee "$output/regression.log"
status=${PIPESTATUS[0]}
ssh_guest 'cd project && tar --exclude="*.sqlite*" -czf - results' > "$output/guest-results.tar.gz"
set -e
# The archive contains only the test reports/screenshots, not profiles or keys.
mkdir -p "$output/guest"
tar -xzf "$output/guest-results.tar.gz" -C "$output/guest"
exit "$status"
