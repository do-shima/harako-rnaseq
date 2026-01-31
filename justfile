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
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc "cd /app && python -m app run --input tests/data --output out --config tests/config.yaml --align none"

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

run INPUT OUTPUT CONFIG ALIGN="none": build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUTPUT}}:/output" rnaseq_pipeline bash -lc "cd /app && python -m app run --input /input --output /output --config '{{CONFIG}}' --align {{ALIGN}} --engine {{ENGINE}} --threads {{THREADS}} {{ARGS}}"
