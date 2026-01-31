import gzip
import os


def _open_text(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def _iter_fasta_headers(path):
    with _open_text(path) as handle:
        for line in handle:
            if line.startswith(">"):
                yield line[1:].strip().split()[0]


transcripts_path = snakemake.input.get("transcripts")
genome_path = snakemake.input.get("genome")
gentrome_path = snakemake.output.get("gentrome")
decoys_path = snakemake.output.get("decoys")

os.makedirs(os.path.dirname(gentrome_path), exist_ok=True)

with open(decoys_path, "w", encoding="utf-8") as handle:
    for name in _iter_fasta_headers(genome_path):
        handle.write(name + "\n")

with gzip.open(gentrome_path, "wt", encoding="utf-8") as out_handle:
    with _open_text(transcripts_path) as handle:
        for line in handle:
            out_handle.write(line)
    with _open_text(genome_path) as handle:
        for line in handle:
            out_handle.write(line)
