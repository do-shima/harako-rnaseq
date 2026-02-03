set dotenv-load := false

REPO := if os() == "windows" { `powershell -NoProfile -Command "(Get-Location).Path"` } else { invocation_directory() }
ENGINE := env_var_or_default("ENGINE", "real")
THREADS := env_var_or_default("THREADS", "1")
ARGS := env_var_or_default("ARGS", "")
INPUT := env_var_or_default("INPUT", "")
OUT := env_var_or_default("OUT", "")

build:
    docker build -t rnaseq_pipeline .

smoke: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && \
      OUTDIR=out_smoke && rm -rf "$OUTDIR" && mkdir -p "$OUTDIR/metadata" && \
      cat > "$OUTDIR/metadata/samples.tsv" <<EOF
sample	condition	fastq1
sample1	A	sample.fastq
EOF
      cat > "$OUTDIR/config.yaml" <<EOF
engine: stub
samples:
  - sample1
input: /app/tests/data
output: /app/$OUTDIR
sample_table: /app/$OUTDIR/metadata/samples.tsv
ref:
  transcripts_fasta: transcripts.fa
  genome_fasta: genome.fa
  gtf: genes.gtf
EOF
      python -m app validate --config "$OUTDIR/config.yaml" --input /app/tests/data --output "/app/$OUTDIR" && \
      python -m app run --config "$OUTDIR/config.yaml" --input /app/tests/data --output "/app/$OUTDIR" --align none --engine stub && \
      test -f "$OUTDIR/report/report.html" && \
      if [ "${ENABLE_ENRICHMENT:-0}" = "1" ]; then \
        python -m snakemake -s tests/enrichment_fixture/Snakefile --cores 1 -p && \
        test -f tests/enrichment_fixture/out/results/enrichment/contrast=A_vs_B/status.json; \
      fi'

list-rules: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc "cd /app && python -m snakemake -s workflow/Snakefile --configfile tests/config.yaml --config input=tests/data output=out --list-rules"

list_rules: list-rules

init: build
    docker run --rm -it -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc "cd /app && python -m app init --input-base /input --out /output"

validate CONFIG:
    docker run --rm -it -v "{{REPO}}:/app" rnaseq_pipeline bash -lc \
      "cd /app && python -m app validate --config '{{CONFIG}}' {{ARGS}}"

dry-run: build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} -n -p --latency-wait 60 --'

dry-run-rat: build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat --cores {{THREADS}} -n -p --latency-wait 60 --'

gentrome: build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} -p --latency-wait 60 -- gentrome'

gentrome-rat: build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat --cores {{THREADS}} -p --latency-wait 60 -- gentrome'

all: build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} -p --latency-wait 60 --'

all-nobuild:
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} -p --latency-wait 60 --'

all-rat-nobuild:
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat --cores {{THREADS}} -p --latency-wait 60 --'

check-outputs:
    docker run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'ls -lh /output/report/report.html /output/deseq2/results.tsv /output/tximport/txi.tsv /output/tximport/tpm.tsv /output/tximport/qc_library_sizes.tsv'

check-salmon-meta:
    docker run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'for s in /output/salmon/*; do if [ -d "$s" ]; then echo "== $s"; ls -lh "$s/meta_info.json" "$s/aux_info/meta_info.json" "$s/cmd_info.json" 2>/dev/null || true; fi; done'

logs:
    docker run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'echo "== /output/logs =="; ls -lh /output/logs || true; echo "== /output/.snakemake/log =="; ls -lh /output/.snakemake/log || true; echo "== tail gentrome =="; tail -n 50 /output/logs/gentrome.log 2>/dev/null || true; echo "== tail salmon_quant =="; tail -n 50 /output/logs/salmon_quant/*.log 2>/dev/null || true'

fetch-refs-rat:
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" rnaseq_pipeline bash -lc 'sh /app/scripts/fetch_refs_ensembl.sh rat'

check-refs-rat:
    docker run --rm -v "{{INPUT}}:/input" rnaseq_pipeline bash -lc 'ls -lh /input/refs/rat/*.fa* /input/refs/rat/*.gtf*'

rat-config:
    docker run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'python -c "import yaml; p=\"/output/config.yaml\"; d=yaml.safe_load(open(p)) or {}; d[\"species\"]=\"rat\"; d.setdefault(\"ref\", {}); d[\"ref\"][\"rat\"]={\"transcripts_fasta\":\"refs/rat/Rattus_norvegicus.GRCr8.cdna.all.fa.gz\",\"genome_fasta\":\"refs/rat/Rattus_norvegicus.GRCr8.dna.toplevel.fa.gz\",\"gtf\":\"refs/rat/Rattus_norvegicus.GRCr8.115.gtf.gz\"}; yaml.safe_dump(d, open(p, \"w\"), sort_keys=False)"'

run INPUT OUTPUT CONFIG ALIGN="none": build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUTPUT}}:/output" rnaseq_pipeline bash -lc "cd /app && python -m app run --input /input --output /output --config '{{CONFIG}}' --align {{ALIGN}} --engine {{ENGINE}} --threads {{THREADS}} {{ARGS}}"

run-real: build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} {{ARGS}} -- report'

run-real-rat: build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat --cores {{THREADS}} {{ARGS}} -- report'

test-tximport: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && rm -rf tests/tximport_mismatch/out && python -m snakemake -s tests/tximport_mismatch/Snakefile --cores 1 -p'

test-tximport-rat-header: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && rm -rf tests/tximport_rat_header/out && python -m snakemake -s tests/tximport_rat_header/Snakefile --cores 1 -p'

test-enrichment: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && rm -rf tests/enrichment_fixture/out && python -m snakemake -s tests/enrichment_fixture/Snakefile --cores 1 -p'

git-sanity:
    python scripts/git_sanity.py
