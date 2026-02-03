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
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc "cd /app && python -m app run --input tests/data --output out --config tests/config.yaml --align none && ls -lh out/deseq2/qc_summary.tsv out/deseq2/qc_summary.json out/deseq2/padj_hist.png out/deseq2/lfc_hist.png out/deseq2/mean_vs_lfc.png out/deseq2/volcano.png"

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
