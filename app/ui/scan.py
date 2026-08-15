"""Compatibility imports for FASTQ helpers formerly owned by the UI."""

from app.core.fastq import (
    FASTQ_EXTS,
    infer_pair_candidates,
    is_r1,
    normalize_input_path,
    read_counts,
    read_side,
    relative_path,
    sample_base,
    split_fastq_name,
    split_read_suffix,
)
from app.services.input_files import list_subdirs, scan_fastq, scan_fastqs, scan_input, scan_refs


rel = relative_path
normalize_input_value = normalize_input_path
fastq_read_counts = read_counts


__all__ = [
    "FASTQ_EXTS",
    "fastq_read_counts",
    "infer_pair_candidates",
    "is_r1",
    "list_subdirs",
    "normalize_input_value",
    "read_side",
    "rel",
    "sample_base",
    "scan_fastq",
    "scan_fastqs",
    "scan_input",
    "scan_refs",
    "split_fastq_name",
    "split_read_suffix",
]
