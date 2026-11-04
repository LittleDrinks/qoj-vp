FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends qemu-system-x86 qemu-utils ca-certificates && rm -rf /var/lib/apt/lists/*
LABEL org.opencontainers.image.source="https://github.com/LittleDrinks/qoj-vp"
LABEL org.opencontainers.image.description="Preinstalled Hydro Contest OS 2026 in QEMU, with disposable per-run storage"
COPY output/system.qcow2 output/vmlinuz output/initrd output/image.json output/SHA256SUMS /opt/hydro/
COPY entrypoint.sh /usr/local/bin/hydro-ci
RUN chmod 755 /usr/local/bin/hydro-ci && cd /opt/hydro && sha256sum --check SHA256SUMS
EXPOSE 2222
ENTRYPOINT ["/usr/local/bin/hydro-ci"]
