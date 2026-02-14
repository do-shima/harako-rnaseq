from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

FASTQ_EXTS = (".fastq.gz", ".fq.gz", ".fastq", ".fq")


def rel(path: Path, input_root: Path) -> str:
    try:
        return str(path.relative_to(input_root))
    except ValueError:
        return str(path)


def _safe_normalized(value: str) -> str:
    raw = (value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if raw.startswith("/"):
        return raw
    norm = os.path.normpath(raw).replace("\\", "/")
    if norm in (".", ""):
        return ""
    if norm.startswith("../") or norm == "..":
        return ""
    return norm.lstrip("./")


def normalize_input_value(value: str) -> str:
    return _safe_normalized(value)


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
    out: list[str] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir():
            out.append(rel(entry, root))
    return out


def _resolve_include_subdirs(root: Path, include_subdirs: list[str] | None) -> list[Path]:
    if include_subdirs is None:
        return [root]
    cleaned = [normalize_input_value(item) for item in include_subdirs]
    cleaned = [item for item in cleaned if item]
    if not cleaned:
        return []
    targets: list[Path] = []
    seen: set[str] = set()
    root_resolved = root.resolve()
    for item in cleaned:
        p = (root / item).resolve()
        try:
            p.relative_to(root_resolved)
        except Exception:
            continue
        if not p.exists() or not p.is_dir():
            continue
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        targets.append(p)
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
    fasta_exts = (".fa", ".fa.gz", ".fasta", ".fasta.gz")
    gtf_exts = (".gtf", ".gtf.gz")
    fasta: list[Path] = []
    gtf: list[Path] = []
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if name.endswith(fasta_exts):
                fasta.append(path)
            if name.endswith(gtf_exts):
                gtf.append(path)
    return sorted(fasta), sorted(gtf)


def scan_input(root: Path, input_root: Path) -> tuple[list[str], dict[str, list[str]]]:
    fastq_files = scan_fastq(root)
    fastq_rel = [rel(p, input_root) for p in fastq_files]
    fasta, gtf = scan_refs(root)
    refs_rel = {
        "fasta": [rel(p, input_root) for p in fasta],
        "gtf": [rel(p, input_root) for p in gtf],
    }
    return fastq_rel, refs_rel


def split_fastq_name(path_value: str) -> tuple[str, str, str]:
    normalized = normalize_input_value(path_value)
    path = Path(normalized)
    parent = path.parent.as_posix()
    if parent == ".":
        parent = ""
    filename = path.name
    lower = filename.lower()
    for ext in FASTQ_EXTS:
        if lower.endswith(ext):
            return parent, filename[: -len(ext)], filename[-len(ext) :]
    stem, ext = os.path.splitext(filename)
    return parent, stem, ext


def split_read_suffix(stem: str) -> tuple[str, str, bool, str]:
    match = re.match(r"(?i)^(?P<prefix>.+?)(?P<sep>[._-])(?P<tag>R?[12])$", stem)
    if match:
        prefix = match.group("prefix")
        tag = match.group("tag").upper()
        sep = match.group("sep")
        is_plain_numeric = (tag in ("1", "2")) and (sep in ("_", ".", "-"))
        if is_plain_numeric:
            looks_like_accession = bool(re.match(r"(?i)^(SRR|ERR|DRR|GSM|SRS|SRX|SAMN|PRJ)", prefix))
            has_nested_delimiter = any(ch in prefix for ch in ("_", ".", "-"))
            if not (looks_like_accession or has_nested_delimiter):
                return stem, "", False, ""
        return (prefix, "1" if tag.endswith("1") else "2", bool(tag.startswith("R")), sep)
    match = re.match(r"(?i)^(?P<prefix>.+?)(?P<tag>R[12])$", stem)
    if match:
        tag = match.group("tag").upper()
        return (match.group("prefix"), "1" if tag.endswith("1") else "2", True, "")
    return stem, "", False, ""


def read_side(path_value: str) -> str:
    _, stem, _ = split_fastq_name(path_value)
    _, read, _, _ = split_read_suffix(stem)
    return read


def is_r1(path_value: str) -> bool:
    return read_side(path_value) == "1"


def sample_base(path_value: str) -> str:
    _, stem, _ = split_fastq_name(path_value)
    prefix, read, _, _ = split_read_suffix(stem)
    return prefix if read else stem


def _join_path(parent: str, filename: str) -> str:
    return filename if not parent else f"{parent}/{filename}"


def infer_pair_candidates(name: str) -> list[str]:
    parent, stem, ext = split_fastq_name(name)
    prefix, read, has_r, sep = split_read_suffix(stem)
    if not read:
        return []

    target_read = "2" if read == "1" else "1"
    token_order = [f"R{target_read}", target_read] if has_r else [target_read, f"R{target_read}"]
    separators: list[str] = []
    if sep:
        separators.append(sep)
    for alt in ("_", ".", "-"):
        if alt not in separators:
            separators.append(alt)

    suffixes: list[str] = []
    if not sep:
        suffixes.extend(token_order)
    for candidate_sep in separators:
        suffixes.extend([f"{candidate_sep}{token}" for token in token_order])

    candidates: list[str] = []
    seen: set[str] = set()
    for suffix in suffixes:
        candidate = _join_path(parent, f"{prefix}{suffix}{ext}")
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


def fastq_read_counts(fastq_rel: Iterable[str]) -> dict[str, int]:
    r1, r2, unknown = 0, 0, 0
    for fq in fastq_rel or []:
        side = read_side(fq)
        if side == "1":
            r1 += 1
        elif side == "2":
            r2 += 1
        else:
            unknown += 1
    return {"r1": r1, "r2": r2, "unknown": unknown}
