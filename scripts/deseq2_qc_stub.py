import base64
import json
import os

results_path = snakemake.input["results"]

outputs = snakemake.output

os.makedirs(os.path.dirname(outputs["summary_tsv"]), exist_ok=True)

summary_rows = [
    "contrast\tgenes\tpadj_lt_0_05",
    "stub\t2\t1",
]
with open(outputs["summary_tsv"], "w", encoding="utf-8") as handle:
    handle.write("\n".join(summary_rows) + "\n")

summary_payload = {
    "source": os.path.basename(results_path),
    "contrast": "stub",
    "genes": 2,
    "padj_lt_0_05": 1,
}
with open(outputs["summary_json"], "w", encoding="utf-8") as handle:
    json.dump(summary_payload, handle, indent=2)
    handle.write("\n")

png_bytes = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFElEQVQoU2NkYGD4z0AE"
    "YBxVSF8AAFwAAy/6F2wAAAAASUVORK5CYII="
)

for key in ("padj_hist", "lfc_hist", "mean_vs_lfc", "volcano"):
    with open(outputs[key], "wb") as handle:
        handle.write(png_bytes)
