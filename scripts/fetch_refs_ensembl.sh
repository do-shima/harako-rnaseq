#!/bin/sh
set -eu

bundle="${1:-}"
if [ "$bundle" != "--experimental-grcr8" ]; then
  echo "Deprecated helper. Usage: fetch_refs_ensembl.sh --experimental-grcr8" >&2
  echo "For supported presets, use scripts/fetch_reference_preset.py and workflow/ref_manifest.yaml." >&2
  exit 2
fi

echo "WARNING: GRCr8/release-115 is a separate experimental bundle, not the default rat preset." >&2
base_dir="/input/refs/rat_grcr8_release115"
mkdir -p "$base_dir"

USE_CURL=0
USE_WGET=0
if command -v curl >/dev/null 2>&1; then
  USE_CURL=1
elif command -v wget >/dev/null 2>&1; then
  USE_WGET=1
else
  echo "Error: curl or wget is required." >&2
  exit 2
fi

fail() {
  echo "Error: download failed: $1" >&2
  exit 1
}

download_if_missing() {
  url="$1"
  out="$2"
  part="${out}.part"
  if [ -s "$out" ]; then
    echo "skip: $out"
    return 0
  fi
  if [ "$USE_CURL" -eq 1 ]; then
    if ! curl -fL --retry 5 --retry-delay 2 --connect-timeout 20 --speed-time 30 --speed-limit 1024 -C - -o "$part" "$url"; then
      echo "Error: download failed: $url -> $part" >&2
      exit 1
    fi
  else
    if ! wget -O "$part" --tries=5 --timeout=20 --continue "$url"; then
      echo "Error: download failed: $url -> $part" >&2
      exit 1
    fi
  fi
  mv "$part" "$out"
  echo "ok: $out size=$(ls -lh "$out" | awk '{print $5}')"
}

if [ "$bundle" = "--experimental-grcr8" ]; then
  gtf_url="https://ftp.ensembl.org/pub/current_gtf/rattus_norvegicus/Rattus_norvegicus.GRCr8.115.gtf.gz"
  cdna_url="https://ftp.ensembl.org/pub/current_fasta/rattus_norvegicus/cdna/Rattus_norvegicus.GRCr8.cdna.all.fa.gz"
  dna_url="https://ftp.ensembl.org/pub/current_fasta/rattus_norvegicus/dna/Rattus_norvegicus.GRCr8.dna.toplevel.fa.gz"

  gtf_out="${base_dir}/Rattus_norvegicus.GRCr8.115.gtf.gz"
  cdna_out="${base_dir}/Rattus_norvegicus.GRCr8.cdna.all.fa.gz"
  dna_out="${base_dir}/Rattus_norvegicus.GRCr8.dna.toplevel.fa.gz"

  echo "fetch: $gtf_url -> $gtf_out"
  download_if_missing "$gtf_url" "$gtf_out"
  echo "fetch: $cdna_url -> $cdna_out"
  download_if_missing "$cdna_url" "$cdna_out"
  echo "fetch: $dna_url -> $dna_out"
  download_if_missing "$dna_url" "$dna_out"
else
  echo "Error: unsupported bundle: $bundle" >&2
  exit 2
fi

echo "[refs] sizes:"
ls -lh "$base_dir"/*.gz

echo "[refs] gzip integrity:"
for f in "$base_dir"/*.gz; do
  if gzip -t "$f"; then
    echo "verify: gzip -t OK $f"
  else
    echo "verify: gzip -t FAIL $f" >&2
    exit 1
  fi
done

gtf_head="$(zcat -f "$gtf_out" | head -n 1 || true)"
if [ -z "$gtf_head" ]; then
  echo "verify: gtf head FAIL $gtf_out" >&2
  exit 1
fi
echo "verify: gtf head OK $gtf_out"

cdna_head="$(zcat -f "$cdna_out" | head -n 1 || true)"
if [ "${cdna_head#>}" = "$cdna_head" ]; then
  echo "verify: cdna head FAIL $cdna_out" >&2
  exit 1
fi
echo "verify: cdna head OK $cdna_out"

dna_head="$(zcat -f "$dna_out" | head -n 1 || true)"
if [ "${dna_head#>}" = "$dna_head" ]; then
  echo "verify: dna head FAIL $dna_out" >&2
  exit 1
fi
echo "verify: dna head OK $dna_out"
