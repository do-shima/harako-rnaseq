"""Read-only input-directory discovery shared by GUI, CLI, and agents."""

from __future__ import annotations

from pathlib import Path

from app.core.fastq import FASTQ_EXTS, normalize_input_path, relative_path


def scan_fastq(root: Path) -> list[Path]:
    files: list[Path] = []
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and path.name.lower().endswith(FASTQ_EXTS):
                files.append(path)
    return sorted(files)


def list_subdirs(root: Path) -> list[str]:
    if not root.exists() or not root.is_dir():
        return []
    return [relative_path(entry, root) for entry in sorted(root.iterdir(), key=lambda path: path.name.lower()) if entry.is_dir()]


def _resolve_include_subdirs(root: Path, include_subdirs: list[str] | None) -> list[Path]:
    if include_subdirs is None:
        return [root]
    cleaned = [normalize_input_path(item) for item in include_subdirs]
    cleaned = [item for item in cleaned if item]
    if not cleaned:
        return []
    targets: list[Path] = []
    seen: set[str] = set()
    root_resolved = root.resolve()
    for item in cleaned:
        path = (root / item).resolve()
        try:
            path.relative_to(root_resolved)
        except Exception:
            continue
        if not path.exists() or not path.is_dir():
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        targets.append(path)
    return targets


def scan_fastqs(root: Path, include_subdirs: list[str] | None = None) -> list[Path]:
    targets = _resolve_include_subdirs(root, include_subdirs)
    if not targets:
        return []
    if len(targets) == 1 and targets[0] == root:
        return scan_fastq(root)
    files: list[Path] = []
    for target in targets:
        for path in target.rglob("*"):
            if path.is_file() and path.name.lower().endswith(FASTQ_EXTS):
                files.append(path)
    return sorted(files)


def scan_refs(root: Path) -> tuple[list[Path], list[Path]]:
    fasta_extensions = (".fa", ".fa.gz", ".fasta", ".fasta.gz")
    gtf_extensions = (".gtf", ".gtf.gz")
    fasta: list[Path] = []
    gtf: list[Path] = []
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if name.endswith(fasta_extensions):
                fasta.append(path)
            if name.endswith(gtf_extensions):
                gtf.append(path)
    return sorted(fasta), sorted(gtf)


def scan_input(root: Path, input_root: Path) -> tuple[list[str], dict[str, list[str]]]:
    fastq_files = scan_fastq(root)
    fastq_relative = [relative_path(path, input_root) for path in fastq_files]
    fasta, gtf = scan_refs(root)
    references = {
        "fasta": [relative_path(path, input_root) for path in fasta],
        "gtf": [relative_path(path, input_root) for path in gtf],
    }
    return fastq_relative, references
