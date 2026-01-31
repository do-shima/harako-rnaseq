import os


output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)

with open(output_file, "w", encoding="utf-8") as handle:
    handle.write("stub-index=1\n")
