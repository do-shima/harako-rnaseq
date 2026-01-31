import json
import os
import shutil


def _fastq_stats(path):
    total_reads = 0
    total_bases = 0
    gc_bases = 0
    q20_bases = 0
    q30_bases = 0

    with open(path, "r", encoding="utf-8") as handle:
        while True:
            header = handle.readline()
            if not header:
                break
            seq = handle.readline().strip()
            handle.readline()
            qual = handle.readline().strip()
            if not seq or not qual:
                break

            total_reads += 1
            total_bases += len(seq)
            gc_bases += sum(1 for base in seq.upper() if base in ("G", "C"))

            for score in (ord(ch) - 33 for ch in qual):
                if score >= 20:
                    q20_bases += 1
                if score >= 30:
                    q30_bases += 1

    gc_content = (gc_bases / total_bases) if total_bases else 0.0

    summary = {
        "total_reads": total_reads,
        "total_bases": total_bases,
        "q20_bases": q20_bases,
        "q30_bases": q30_bases,
        "gc_content": gc_content,
    }
    return summary


input_file = snakemake.input[0]
output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)
shutil.copyfile(input_file, output_file)

stats = _fastq_stats(output_file)

fastp_payload = {
    "command": "fastp_stub",
    "summary": {
        "before_filtering": stats,
        "after_filtering": stats,
    },
    "filtering_result": {
        "passed_filter_reads": stats["total_reads"],
        "passed_filter_bases": stats["total_bases"],
        "low_quality_reads": 0,
        "too_many_N_reads": 0,
        "too_short_reads": 0,
        "too_long_reads": 0,
    },
}

json_path = os.path.splitext(output_file)[0] + ".json"
with open(json_path, "w", encoding="utf-8") as handle:
    json.dump(fastp_payload, handle, indent=2)

html_path = os.path.splitext(output_file)[0] + ".html"
html = "\n".join(
    [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head>",
        "  <meta charset=\"utf-8\">",
        "  <title>fastp (stub)</title>",
        "</head>",
        "<body>",
        "  <h1>fastp stub output</h1>",
        f"  <p>Input: {os.path.basename(input_file)}</p>",
        f"  <p>Output: {os.path.basename(output_file)}</p>",
        "</body>",
        "</html>",
    ]
)
with open(html_path, "w", encoding="utf-8") as handle:
    handle.write(html)
