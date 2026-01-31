import argparse
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


def build_gentrome(transcripts_path, genome_path, gentrome_path, decoys_path):
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


def main():
    parser = argparse.ArgumentParser(description="Build gentrome and decoy list.")
    parser.add_argument("--transcripts", required=True)
    parser.add_argument("--genome", required=True)
    parser.add_argument("--gentrome", required=True)
    parser.add_argument("--decoys", required=True)
    args = parser.parse_args()
    build_gentrome(args.transcripts, args.genome, args.gentrome, args.decoys)


if __name__ == "__main__":
    if "snakemake" in globals():
        build_gentrome(
            snakemake.input.get("transcripts"),
            snakemake.input.get("genome"),
            snakemake.output.get("gentrome"),
            snakemake.output.get("decoys"),
        )
    else:
        main()
