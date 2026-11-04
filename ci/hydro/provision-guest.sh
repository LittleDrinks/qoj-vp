#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends openssh-server python3-pip python3-requests python3-bs4 python3-pycurl ca-certificates curl sudo
mkdir -p /opt/hydro-ci/vendor_py
python3 -m pip install --disable-pip-version-check --target /opt/hydro-ci/vendor_py 'selenium==4.38.0'
curl --fail --location --retry 3 --max-time 120 https://github.com/mozilla/geckodriver/releases/download/v0.37.1/geckodriver-v0.37.1-linux64.tar.gz -o /var/tmp/geckodriver.tar.gz
printf '%s  %s\n' e815130ea95983e162ae91843b48d3a3ce991735635fce83a647afde21e09f7e /var/tmp/geckodriver.tar.gz | sha256sum --check
tar -xzf /var/tmp/geckodriver.tar.gz -C /opt/hydro-ci geckodriver
rm /var/tmp/geckodriver.tar.gz
useradd --create-home --shell /bin/bash hydroci
# Account has no reusable password; SSH accepts only each job's temporary key.
usermod --password '*' hydroci
printf 'hydroci ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/hydro-ci
chmod 440 /etc/sudoers.d/hydro-ci
mkdir -p /etc/ssh/sshd_config.d /etc/systemd/system/ssh.service.d
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\nAllowUsers hydroci\n' > /etc/ssh/sshd_config.d/00-hydro-ci.conf
cat > /usr/local/sbin/hydro-ci-init <<'SCRIPT'
#!/bin/sh
set -eu
mkdir -p /run/ci-config
mountpoint -q /run/ci-config || mount -t 9p -o trans=virtio,version=9p2000.L,ro ci-config /run/ci-config
install -d -m 700 -o hydroci -g hydroci /home/hydroci/.ssh
install -m 600 -o hydroci -g hydroci /run/ci-config/authorized_keys /home/hydroci/.ssh/authorized_keys
ssh-keygen -A
SCRIPT
chmod 755 /usr/local/sbin/hydro-ci-init
cat > /etc/systemd/system/hydro-ci-init.service <<'UNIT'
[Unit]
Description=Initialize ephemeral Hydro CI access
Before=ssh.service
After=local-fs.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/hydro-ci-init
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
printf '[Unit]\nRequires=hydro-ci-init.service\nAfter=hydro-ci-init.service\n' > /etc/systemd/system/ssh.service.d/hydro-ci.conf
# Keep the installed desktop unchanged; CI boots without a graphical login.
systemctl set-default multi-user.target
systemctl enable hydro-ci-init ssh systemd-networkd systemd-resolved
systemctl disable NetworkManager.service NetworkManager-wait-online.service || true
mkdir -p /etc/systemd/network
printf '[Match]\nName=en* eth*\n[Network]\nDHCP=yes\n' > /etc/systemd/network/05-hydro-ci.network
printf '/dev/vda / ext4 defaults 0 1\n' > /etc/fstab
printf 'hydro-ci\n' > /etc/hostname
printf '127.0.0.1 localhost\n127.0.1.1 hydro-ci\n' > /etc/hosts
printf 'virtio_pci\nvirtio_blk\nvirtio_net\n9p\n9pnet\n9pnet_virtio\next4\n' >> /etc/initramfs-tools/modules
update-initramfs -u -k all
apt-get clean
