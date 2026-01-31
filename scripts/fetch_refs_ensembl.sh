#!/bin/sh
set -eu

species="${1:-}"
if [ -z "$species" ]; then
  echo "Usage: fetch_refs_ensembl.sh <species>" >&2
  exit 2
fi

base_dir="/input/refs/${species}"
mkdir -p "$base_dir"

if command -v curl >/dev/null 2>&1; then
  FETCH="curl -fL -o"
elif command -v wget >/dev/null 2>&1; then
  FETCH="wget -O"
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
  if [ -s "$out" ]; then
    echo "skip: $out"
    return 0
  fi
  if ! $FETCH "$out" "$url"; then
    fail "$url"
  fi
  echo "downloaded: $out"
}

if [ "$species" = "rat" ]; then
  gtf_url="https://ftp.ensembl.org/pub/current_gtf/rattus_norvegicus/Rattus_norvegicus.GRCr8.115.gtf.gz"
  cdna_url="https://ftp.ensembl.org/pub/current_fasta/rattus_norvegicus/cdna/Rattus_norvegicus.GRCr8.cdna.all.fa.gz"
  dna_url="https://ftp.ensembl.org/pub/current_fasta/rattus_norvegicus/dna/Rattus_norvegicus.GRCr8.dna.primary_assembly.fa.gz"

  gtf_out="${base_dir}/Rattus_norvegicus.GRCr8.115.gtf.gz"
  cdna_out="${base_dir}/Rattus_norvegicus.GRCr8.cdna.all.fa.gz"
  dna_out="${base_dir}/Rattus_norvegicus.GRCr8.dna.primary_assembly.fa.gz"

  download_if_missing "$gtf_url" "$gtf_out"
  download_if_missing "$cdna_url" "$cdna_out"
  download_if_missing "$dna_url" "$dna_out"
else
  echo "Error: unsupported species: $species" >&2
  exit 2
fi

echo "[refs] sizes:"
ls -lh "$base_dir"/*.gz

echo "[refs] gzip integrity:"
gzip -t "$base_dir"/*.gz
