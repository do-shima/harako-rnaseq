import os

transcripts = snakemake.input.get("transcripts")
genome = snakemake.input.get("genome")
output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)

with open(output_file, "w", encoding="utf-8") as handle:
    if genome:
        handle.write("decoy-aware-index=1\n")
    else:
        handle.write("transcripts-only-index=1\n")
    handle.write(f"transcripts={transcripts}\n")
    handle.write(f"genome={genome}\n")