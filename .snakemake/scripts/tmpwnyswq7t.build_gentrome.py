######## snakemake preamble start (automatically inserted, do not edit) ########
import sys;sys.path.extend(['/usr/local/lib/python3.11/site-packages', '/app/workflow', '/app', '/usr/local/lib/python3.11', '/usr/local/lib/python3.11/lib-dynload', '/usr/local/lib/python3.11/site-packages', '/root/.cache/snakemake/snakemake/source-cache/snakemake-runtime-cache/tmp7on2tler/file/app/workflow/scripts', '/app/workflow/scripts']);import pickle;from snakemake import script;script.snakemake = pickle.loads(b'\x80\x04\x95\x9a\x05\x00\x00\x00\x00\x00\x00\x8c\x10snakemake.script\x94\x8c\tSnakemake\x94\x93\x94)\x81\x94}\x94(\x8c\x05input\x94\x8c\x0csnakemake.io\x94\x8c\nInputFiles\x94\x93\x94)\x81\x94(\x8c6/input/refs/gencode_M38/gencode.vM38.transcripts.fa.gz\x94\x8c+/input/refs/gencode_M38/GRCm39.genome.fa.gz\x94e}\x94(\x8c\x06_names\x94}\x94(\x8c\x0btranscripts\x94K\x00N\x86\x94\x8c\x06genome\x94K\x01N\x86\x94u\x8c\x12_allowed_overrides\x94]\x94(\x8c\x05index\x94\x8c\x04sort\x94eh\x15h\x06\x8c\x0eAttributeGuard\x94\x93\x94)\x81\x94}\x94\x8c\x04name\x94h\x15sbh\x16h\x18)\x81\x94}\x94h\x1bh\x16sbh\x0fh\nh\x11h\x0bub\x8c\x06output\x94h\x06\x8c\x0bOutputFiles\x94\x93\x94)\x81\x94(\x8c\x1d/output/salmon/gentrome.fa.gz\x94\x8c\x19/output/salmon/decoys.txt\x94e}\x94(h\r}\x94(\x8c\x08gentrome\x94K\x00N\x86\x94\x8c\x06decoys\x94K\x01N\x86\x94uh\x13]\x94(h\x15h\x16eh\x15h\x18)\x81\x94}\x94h\x1bh\x15sbh\x16h\x18)\x81\x94}\x94h\x1bh\x16sbh&h"h(h#ub\x8c\r_params_store\x94h\x06\x8c\x06Params\x94\x93\x94)\x81\x94}\x94(h\r}\x94h\x13]\x94(h\x15h\x16eh\x15h\x18)\x81\x94}\x94h\x1bh\x15sbh\x16h\x18)\x81\x94}\x94h\x1bh\x16sbub\x8c\r_params_types\x94}\x94\x8c\twildcards\x94h\x06\x8c\tWildcards\x94\x93\x94)\x81\x94}\x94(h\r}\x94h\x13]\x94(h\x15h\x16eh\x15h\x18)\x81\x94}\x94h\x1bh\x15sbh\x16h\x18)\x81\x94}\x94h\x1bh\x16sbub\x8c\x07threads\x94K\x01\x8c\tresources\x94h\x06\x8c\tResources\x94\x93\x94)\x81\x94(K\x01K\x01\x8c\x04/tmp\x94e}\x94(h\r}\x94(\x8c\x06_cores\x94K\x00N\x86\x94\x8c\x06_nodes\x94K\x01N\x86\x94\x8c\x06tmpdir\x94K\x02N\x86\x94uh\x13]\x94(h\x15h\x16eh\x15h\x18)\x81\x94}\x94h\x1bh\x15sbh\x16h\x18)\x81\x94}\x94h\x1bh\x16sbhOK\x01hQK\x01hShLub\x8c\x03log\x94h\x06\x8c\x03Log\x94\x93\x94)\x81\x94}\x94(h\r}\x94h\x13]\x94(h\x15h\x16eh\x15h\x18)\x81\x94}\x94h\x1bh\x15sbh\x16h\x18)\x81\x94}\x94h\x1bh\x16sbub\x8c\x06config\x94}\x94(\x8c\x06engine\x94\x8c\x04real\x94\x8c\x07samples\x94]\x94(\x8c\x05Con_1\x94\x8c\x05Con_2\x94\x8c\x05STZ_1\x94\x8c\x05STZ_2\x94e\x8c\x0csample_table\x94\x8c\x10/app/samples.tsv\x94\x8c\x06output\x94\x8c\x07/output\x94\x8c\x03ref\x94}\x94(\x8c\x11transcripts_fasta\x94\x8c6/input/refs/gencode_M38/gencode.vM38.transcripts.fa.gz\x94\x8c\x0cgenome_fasta\x94\x8c+/input/refs/gencode_M38/GRCm39.genome.fa.gz\x94\x8c\x03gtf\x94\x8cK/input/refs/gencode_M38/gencode.vM38.chr_patch_hapl_scaff.annotation.gtf.gz\x94u\x8c\x07threads\x94K\x04\x8c\tcontrasts\x94]\x94\x8c\x12treated_vs_control\x94a\x8c\x05input\x94\x8c\x06/input\x94\x8c\x05align\x94\x8c\x04none\x94u\x8c\x04rule\x94h&\x8c\x0fbench_iteration\x94N\x8c\tscriptdir\x94\x8c\x15/app/workflow/scripts\x94ub.');del script;from snakemake.logging import logger;from snakemake.script import snakemake;__real_file__ = __file__; __file__ = '/app/workflow/scripts/build_gentrome.py';
######## snakemake preamble end #########
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


transcripts_path = snakemake.input.get("transcripts")
genome_path = snakemake.input.get("genome")
gentrome_path = snakemake.output.get("gentrome")
decoys_path = snakemake.output.get("decoys")

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
