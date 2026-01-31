import os
import shutil

input_file = snakemake.input[0]
output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)
shutil.copyfile(input_file, output_file)