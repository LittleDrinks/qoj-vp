#!/usr/bin/env bash
# One-time image build only. Regular regression jobs never run this script.
set -euo pipefail
: "${HYDRO_ISO:?Provide the verified clean ISO path}"
: "${HYDRO_ISO_SHA256:?Pin the exact ISO SHA256}"
test "$(id -u)" = 0
project=$(pwd)
work=$(mktemp -d "${RUNNER_TEMP:-/var/tmp}/hydro-build.XXXXXX")
output="$project/infra/hydro/output"
mkdir -p "$output" "$work/iso" "$work/base" "$work/standard" "$work/merged" "$work/root"
mounts=()
cleanup() {
  for ((i=${#mounts[@]}-1;i>=0;i--)); do umount -R "${mounts[$i]}" || true; done
}
trap cleanup EXIT
printf '%s  %s\n' "$HYDRO_ISO_SHA256" "$HYDRO_ISO" | sha256sum --check
apt-get update -qq
apt-get install -y --no-install-recommends squashfs-tools rsync qemu-utils e2fsprogs
mount -o loop,ro "$HYDRO_ISO" "$work/iso"; mounts+=("$work/iso")
mount -t squashfs -o loop,ro "$work/iso/casper/minimal.squashfs" "$work/base"; mounts+=("$work/base")
mount -t squashfs -o loop,ro "$work/iso/casper/minimal.standard.squashfs" "$work/standard"; mounts+=("$work/standard")
mount -t overlay overlay -o "lowerdir=$work/standard:$work/base" "$work/merged"; mounts+=("$work/merged")
truncate -s 32G "$work/system.raw"
mkfs.ext4 -q -F "$work/system.raw"
mount -o loop "$work/system.raw" "$work/root"; mounts+=("$work/root")
rsync -aHAX --numeric-ids "$work/merged/" "$work/root/"
for name in dev proc sys; do
  mount --rbind "/$name" "$work/root/$name"
  mount --make-rslave "$work/root/$name"
  mounts+=("$work/root/$name")
done
rm -f "$work/root/etc/resolv.conf"
cp /etc/resolv.conf "$work/root/etc/resolv.conf"
printf '#!/bin/sh\nexit 101\n' > "$work/root/usr/sbin/policy-rc.d"
chmod +x "$work/root/usr/sbin/policy-rc.d"
# The installer adds the kernel from the ISO pool after copying filesystem layers.
mkdir -p "$work/root/var/tmp/hydro-kernel"
find "$work/iso/pool" -type f \( -name 'linux-image-[0-9]*-generic_*.deb' -o -name 'linux-modules-[0-9]*-generic_*.deb' \) \
  -exec cp '{}' "$work/root/var/tmp/hydro-kernel/" \;
test "$(find "$work/root/var/tmp/hydro-kernel" -name '*.deb' | wc -l)" -ge 2
cp infra/hydro/provision-guest.sh "$work/root/var/tmp/provision-guest.sh"
chroot "$work/root" /bin/bash /var/tmp/provision-guest.sh
rm "$work/root/var/tmp/provision-guest.sh" "$work/root/usr/sbin/policy-rc.d"
rm -rf "$work/root/var/tmp/hydro-kernel"
rm -f "$work/root/etc/resolv.conf"
ln -s /run/systemd/resolve/stub-resolv.conf "$work/root/etc/resolv.conf"
kernel=$(find "$work/root/lib/modules" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort -V | tail -1)
# Docker's unprivileged context sender must be able to read these public files.
install -m 644 "$work/root/boot/vmlinuz-$kernel" "$output/vmlinuz"
install -m 644 "$work/root/boot/initrd.img-$kernel" "$output/initrd"
chroot "$work/root" dpkg-query -W -f='${Package}\t${Version}\n' > "$output/packages.txt"
python3 - "$output" "$HYDRO_ISO_SHA256" "$kernel" <<'PY'
import json,sys
from pathlib import Path
out=Path(sys.argv[1])
(out/'image.json').write_text(json.dumps({'schema':1,'distribution':'Hydro Contest OS 2026',
 'variant':'icpc-ubuntu-desktop (standard)','isoSha256':sys.argv[2],'kernel':sys.argv[3],
 'ciChanges':['isolated hydroci account','ephemeral SSH key from read-only config share',
 'DHCP networkd','multi-user boot target','preinstalled browser test dependencies']},indent=2)+'\n')
PY
cp "$output/image.json" "$work/root/etc/hydro-ci-image.json"
# Remove identities and logs created during preparation, never personal VM files.
rm -f "$work/root/etc/ssh/ssh_host_"* "$work/root/var/lib/dbus/machine-id"
: > "$work/root/etc/machine-id"
ln -s /etc/machine-id "$work/root/var/lib/dbus/machine-id"
find "$work/root/var/log" -type f -exec truncate -s 0 {} +
sync
cleanup
mounts=()
udevadm settle
sync
bash infra/hydro/check-filesystem.sh "$work/system.raw"
qemu-img convert -p -c -f raw -O qcow2 "$work/system.raw" "$output/system.qcow2"
qemu-img check "$output/system.qcow2"
test "$(stat -c %s "$output/system.qcow2")" -lt 9500000000
(cd "$output" && sha256sum system.qcow2 vmlinuz initrd > SHA256SUMS)
rm -rf "$work"
