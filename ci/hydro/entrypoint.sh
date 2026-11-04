#!/usr/bin/env bash
set -euo pipefail
test -c /dev/kvm
test -s /config/authorized_keys
mkdir -p /run/hydro /output
qemu-img create -f qcow2 -F qcow2 -b /opt/hydro/system.qcow2 /run/hydro/session.qcow2
exec qemu-system-x86_64 -machine q35,accel=kvm -cpu host -smp "$(nproc)" -m 4096 \
  -display none -monitor none -serial file:/output/serial.log \
  -kernel /opt/hydro/vmlinuz -initrd /opt/hydro/initrd \
  -append 'root=/dev/vda rw rootwait console=ttyS0 systemd.unit=multi-user.target' \
  -drive file=/run/hydro/session.qcow2,if=virtio,format=qcow2 \
  -nic user,model=virtio-net-pci,hostfwd=tcp:0.0.0.0:2222-:22 \
  -fsdev local,id=config,path=/config,security_model=none,readonly=on \
  -device virtio-9p-pci,fsdev=config,mount_tag=ci-config
