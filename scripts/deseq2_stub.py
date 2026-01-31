import os

input_file = snakemake.input[0]
output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)

with open(output_file, "w", encoding="utf-8") as handle:
    handle.write("gene_id\tlog2FoldChange\tpvalue\n")
    handle.write("geneA\t1.0\t0.05\n")
    handle.write("geneB\t-0.5\t0.25\n")
    handle.write(f"source={input_file}\n")