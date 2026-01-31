import json
import os


output_file = snakemake.output[0]
output_dir = os.path.dirname(output_file)

os.makedirs(output_dir, exist_ok=True)

with open(output_file, "w", encoding="utf-8") as handle:
    handle.write("Name\tLength\tEffectiveLength\tTPM\tNumReads\n")
    handle.write("tx1\t1000\t900\t1.0\t10\n")
    handle.write("tx2\t900\t800\t0.5\t5\n")

meta_info = {
    "mapping_rate": 1.0,
}

meta_path = os.path.join(output_dir, "meta_info.json")
with open(meta_path, "w", encoding="utf-8") as handle:
    json.dump(meta_info, handle, indent=2)
