import os

reads = snakemake.input.get("reads")
output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)

with open(output_file, "w", encoding="utf-8") as handle:
    handle.write("Name\tLength\tTPM\n")
    handle.write("tx1\t1000\t1.0\n")
    handle.write("tx2\t900\t0.5\n")
    handle.write(f"reads={reads}\n")