#!/usr/bin/env bash
set -euo pipefail

: "${SALMON_VERSION:=1.10.0}"
: "${SALMON_SHA256:=b876d041ef3bfbe44422b052b99ce387ff4e521c76002355c7b27882cf19c01b}"
: "${SALMON_SOURCE_SHA256:=fd8039c20f8dc717d414c89d32ce80a37b1cf4fda2eb9dba839adedd33a4fa3a}"
: "${FASTP_VERSION:=0.23.4}"
: "${FASTP_SHA256:=4037508afcfa41e85586d4f06bb001bb73d9f29f159fb264c59b98deff27d377}"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

salmon_url="https://github.com/COMBINE-lab/salmon/releases/download/v${SALMON_VERSION}/salmon-${SALMON_VERSION}_linux_x86_64.tar.gz"
salmon_source_url="https://github.com/COMBINE-lab/salmon/archive/refs/tags/v${SALMON_VERSION}.tar.gz"
fastp_url="http://opengene.org/fastp/fastp.${FASTP_VERSION}"

curl -fsSL "$salmon_url" -o "$workdir/salmon.tar.gz"
echo "${SALMON_SHA256}  $workdir/salmon.tar.gz" | sha256sum -c -
tar -xzf "$workdir/salmon.tar.gz" -C "$workdir"
salmon_root="$(find "$workdir" -maxdepth 1 -type d -name 'salmon-*' | head -n 1)"
test -n "$salmon_root"
rm -rf /opt/salmon
mkdir -p /opt
cp -a "$salmon_root" /opt/salmon
cat >/usr/local/bin/salmon <<'EOF'
#!/usr/bin/env bash
export LD_LIBRARY_PATH="/opt/salmon/lib:${LD_LIBRARY_PATH:-}"
exec /opt/salmon/bin/salmon "$@"
EOF
chmod +x /usr/local/bin/salmon

curl -fsSL "$salmon_source_url" -o "$workdir/salmon-source.tar.gz"
echo "${SALMON_SOURCE_SHA256}  $workdir/salmon-source.tar.gz" | sha256sum -c -
mkdir -p /usr/src
install -m 0644 "$workdir/salmon-source.tar.gz" "/usr/src/salmon-${SALMON_VERSION}.tar.gz"

curl -fsSL "$fastp_url" -o "$workdir/fastp"
echo "${FASTP_SHA256}  $workdir/fastp" | sha256sum -c -
install -m 0755 "$workdir/fastp" /usr/local/bin/fastp

salmon --version >/dev/null
fastp --version >/dev/null
