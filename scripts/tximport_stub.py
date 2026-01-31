import os

input_files = snakemake.input
output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)

with open(output_file, "w", encoding="utf-8") as handle:
    handle.write("transcript_id\tcounts\n")
    for idx, path in enumerate(input_files, start=1):
        handle.write(f"tx{idx}\t{idx * 10}\n")