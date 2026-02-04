set dotenv-load := false

REPO := if os() == "windows" { `powershell -NoProfile -Command "(Get-Location).Path"` } else { invocation_directory() }
IMAGE := env_var_or_default("IMAGE", "rnaseq_pipeline")
ENGINE := env_var_or_default("ENGINE", "real")
THREADS := env_var_or_default("THREADS", "1")
ARGS := env_var_or_default("ARGS", "")
INPUT := env_var_or_default("INPUT", "")
OUT := env_var_or_default("OUT", "")
ENABLE_ENRICHMENT := env_var_or_default("ENABLE_ENRICHMENT", "0")
REPORT := env_var_or_default("REPORT", "")
CONFIG := env_var_or_default("CONFIG", "")
SELFCONTAINED := env_var_or_default("SELFCONTAINED", "strict")
SELFCONTAINED_ARGS := if SELFCONTAINED == "warn" { "--warn-only" } else { "" }

build:
    docker build -t {{IMAGE}} .

build-if-needed:
    @docker image inspect {{IMAGE}} >/dev/null 2>&1 || docker build -t {{IMAGE}} .

smoke: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && \
      OUTDIR=out_smoke && rm -rf "$OUTDIR" && mkdir -p "$OUTDIR/metadata" && \
      printf "sample\tcondition\tfastq1\nsample1\tA\tsample1.fastq\n" > "$OUTDIR/metadata/samples.tsv" && \
      printf "%s\n" \
        "engine: stub" \
        "samples:" \
        "  - sample1" \
        "input: /app/tests/data" \
        "output: /app/$OUTDIR" \
        "sample_table: /app/$OUTDIR/metadata/samples.tsv" \
        "ref:" \
        "  transcripts_fasta: transcripts.fa" \
        "  genome_fasta: genome.fa" \
        "  gtf: genes.gtf" \
        > "$OUTDIR/config.yaml" && \
      python -m app validate --config "$OUTDIR/config.yaml" --input /app/tests/data --output "/app/$OUTDIR" && \
      python -m app run --config "$OUTDIR/config.yaml" --input /app/tests/data --output "/app/$OUTDIR" --align none --engine stub && \
      test -f "$OUTDIR/report/report.html" && \
      if [ "${ENABLE_ENRICHMENT:-0}" = "1" ]; then \
        python -m snakemake -s tests/enrichment_fixture/Snakefile --cores 1 -p && \
        test -f tests/enrichment_fixture/out/results/enrichment/contrast=A_vs_B/status.json; \
      fi'

verify-smoke:
    just smoke
    just check-report-selfcontained out_smoke/report/report.html
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'test -f /app/out_smoke/report/report.html && test -f /app/out_smoke/deseq2/results.tsv && test -f /app/out_smoke/tximport/txi.tsv && test -f /app/out_smoke/salmon/sample1/quant.sf && if [ "{{ENABLE_ENRICHMENT}}" = "1" ]; then test -f /app/tests/enrichment_fixture/out/results/enrichment/contrast=A_vs_B/status.json; fi'

list-rules: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc "cd /app && python -m snakemake -s workflow/Snakefile --configfile tests/config.yaml --config input=tests/data output=out --list-rules"

list_rules: list-rules

init: build
    docker run --rm -it -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc "cd /app && python -m app init --input-base /input --out /output"

validate CONFIG=CONFIG:
    if [ -z "{{CONFIG}}" ]; then echo "CONFIG is required (use CONFIG=... or set CONFIG env var)"; exit 2; fi
    docker run --rm -it -v "{{REPO}}:/app" rnaseq_pipeline bash -lc \
      "cd /app && p='{{CONFIG}}'; p=\${p#CONFIG=}; python -m app validate --config \"\$p\" {{ARGS}}"

validate-out: build
    docker run --rm -it -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc \
      "cd /app && python -m app validate --config /output/config.yaml --input /input --output /output {{ARGS}}"

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

run INPUT=INPUT OUTPUT=OUT CONFIG=CONFIG ALIGN="none": build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUTPUT}}:/output" {{IMAGE}} bash -lc "cd /app && p='{{CONFIG}}'; p=\${p#CONFIG=}; python -m app run --input /input --output /output --config \"\$p\" --align {{ALIGN}} --engine {{ENGINE}} --threads {{THREADS}} {{ARGS}}"

run-real: build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} {{ARGS}} -- report'

run-real-rat: build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat --cores {{THREADS}} {{ARGS}} -- report'

run-out: build
    if [ -z "{{INPUT}}" ] || [ -z "{{OUT}}" ]; then echo "INPUT/OUT are required (set env vars)"; exit 2; fi
    @docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && test -f /output/config.yaml || (echo "Missing /output/config.yaml (run UI Save first)"; exit 2); python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output engine={{ENGINE}} --cores {{THREADS}} {{ARGS}} -- report'

report-out: build
    if [ -z "{{INPUT}}" ] || [ -z "{{OUT}}" ]; then echo "INPUT/OUT are required (set env vars)"; exit 2; fi
    @docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && test -f /output/config.yaml || (echo "Missing /output/config.yaml (run UI Save first)"; exit 2); python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output engine={{ENGINE}} --cores {{THREADS}} {{ARGS}} -- report'

open-out:
    if [ -z "{{OUT}}" ]; then echo "OUT is required (set env var)"; exit 2; fi
    @echo "Report: {{OUT}}/report/report.html"

app: build-if-needed
    @echo "Starting UI... open http://127.0.0.1:8501"
    @docker run --rm -p 127.0.0.1:8501:8501 -e HOST_INPUT="{{INPUT}}" -e HOST_OUT="{{OUT}}" -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" {{IMAGE}} bash -lc 'cd /app && streamlit run app/ui/app_ui.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false --logger.level=warning'

ui: app

launcher-web:
    @echo "Deprecated: use just app"

launcher: launcher-web

test-tximport: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && rm -rf tests/tximport_mismatch/out && python -m snakemake -s tests/tximport_mismatch/Snakefile --cores 1 -p'

test-tximport-rat-header: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && rm -rf tests/tximport_rat_header/out && python -m snakemake -s tests/tximport_rat_header/Snakefile --cores 1 -p'

test-enrichment: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && rm -rf tests/enrichment_fixture/out && python -m snakemake -s tests/enrichment_fixture/Snakefile --cores 1 -p'

git-sanity:
    python scripts/git_sanity.py

check-report-selfcontained PATH:
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && p="{{PATH}}"; p="${p#REPORT=}"; python /app/scripts/check_report_selfcontained.py --report "$p"'

debug-report-externals:
    docker run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'python /app/scripts/check_report_selfcontained.py --report /output/report/report.html --print-externals --strict-links || true'

verify-real: build
    @docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" {{IMAGE}} bash -lc 'set -euo pipefail; test -d /input || { echo "Missing /input mount (set INPUT env var)"; exit 2; }; test -d /output || { echo "Missing /output mount (set OUT env var)"; exit 2; }; test -f /output/config.yaml; test -f /output/metadata/samples.tsv; samples=$(tail -n +2 /output/metadata/samples.tsv | cut -f1 | tr "\r" "\n"); for s in $samples; do test -f "/output/salmon/$s/quant.sf"; done; test -f /output/tximport/txi.tsv; engine=$(python -c "import yaml; cfg=yaml.safe_load(open('\''/output/config.yaml'\'')) or {}; print(cfg.get('\''engine'\'','\''real'\''))"); if [ "$engine" = "real" ]; then test -f /output/deseq2/results.tsv; fi; test -f /output/report/report.html; python /app/scripts/check_report_selfcontained.py --report /output/report/report.html {{SELFCONTAINED_ARGS}}; echo "Share these outputs:"; echo " - /output/report/report.html"; echo " - /output/run/config_resolved.yaml"; echo " - /output/run/versions.tsv"; echo " - /output/deseq2/results.tsv"'

check: verify-real
