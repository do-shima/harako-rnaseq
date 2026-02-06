import json
import os
import sys
import gzip


def _is_gz(path):
    if path.lower().endswith(".gz"):
        return True
    try:
        with open(path, "rb") as handle:
            return handle.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def _open_text(path):
    if _is_gz(path):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def _open_write(path):
    if path.lower().endswith(".gz"):
        return gzip.open(path, "wt", encoding="utf-8")
    return open(path, "w", encoding="utf-8")


def _copy_fastq(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with _open_text(src) as reader, _open_write(dst) as writer:
        for line in reader:
            writer.write(line)


def _fastq_stats(path):
    total_reads = 0
    total_bases = 0
    gc_bases = 0
    q20_bases = 0
    q30_bases = 0

    with _open_text(path) as handle:
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


if "snakemake" in globals():
    input_file = snakemake.input[0]
    output_file = snakemake.output[0]
    json_path = snakemake.output[1] if len(snakemake.output) > 1 else None
    html_path = snakemake.output[2] if len(snakemake.output) > 2 else None
else:
    args = sys.argv[1:]
    if len(args) < 2:
        raise SystemExit("Usage: fastp_stub.py <input> <output> [json] [html]")
    input_file = args[0]
    output_file = args[1]
    json_path = args[2] if len(args) > 2 else None
    html_path = args[3] if len(args) > 3 else None

_copy_fastq(input_file, output_file)

if json_path or html_path:
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

    if json_path:
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(fastp_payload, handle, indent=2)

    if html_path:
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
