import os
from datetime import datetime

input_file = snakemake.input["results"]
output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)

html = "\n".join([
    "<!doctype html>",
    "<html lang=\"en\">",
    "<head>",
    "  <meta charset=\"utf-8\">",
    "  <title>RNA-seq Report</title>",
    "  <style>",
    "    body { font-family: Arial, sans-serif; margin: 24px; }",
    "    h1 { margin-bottom: 4px; }",
    "    .meta { color: #555; margin-bottom: 16px; }",
    "    pre { background: #f5f5f5; padding: 12px; }",
    "  </style>",
    "</head>",
    "<body>",
    "  <h1>RNA-seq Report</h1>",
    f"  <div class=\"meta\">Generated: {datetime.utcnow().isoformat()}Z</div>",
    "  <p>Static HTML report (Quarto-ready placeholder).</p>",
    f"  <pre>Input: {input_file}</pre>",
    "</body>",
    "</html>",
])

with open(output_file, "w", encoding="utf-8") as handle:
    handle.write(html)
