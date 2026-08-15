"""Pure FASTQ path, read-side, and pairing-name rules."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable


FASTQ_EXTS = (".fastq.gz", ".fq.gz", ".fastq", ".fq")


def relative_path(path: Path, input_root: Path) -> str:
    try:
        return path.relative_to(input_root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def normalize_input_path(value: str) -> str:
    raw = (value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if raw.startswith("/"):
        return raw
    normalized = os.path.normpath(raw).replace("\\", "/")
    if normalized in (".", ""):
        return ""
    if normalized.startswith("../") or normalized == "..":
        return ""
    return normalized.lstrip("./")


def split_fastq_name(path_value: str) -> tuple[str, str, str]:
    normalized = normalize_input_path(path_value)
    path = Path(normalized)
    parent = path.parent.as_posix()
    if parent == ".":
        parent = ""
    filename = path.name
    lower = filename.lower()
    for extension in FASTQ_EXTS:
        if lower.endswith(extension):
            return parent, filename[: -len(extension)], filename[-len(extension) :]
    stem, extension = os.path.splitext(filename)
    return parent, stem, extension


def split_read_suffix(stem: str) -> tuple[str, str, bool, str]:
    match = re.match(r"(?i)^(?P<prefix>.+?)(?P<sep>[._-])(?P<tag>R?[12])$", stem)
    if match:
        prefix = match.group("prefix")
        tag = match.group("tag").upper()
        separator = match.group("sep")
        is_plain_numeric = tag in ("1", "2") and separator in ("_", ".", "-")
        if is_plain_numeric:
            looks_like_accession = bool(re.match(r"(?i)^(SRR|ERR|DRR|GSM|SRS|SRX|SAMN|PRJ)", prefix))
            has_nested_delimiter = any(character in prefix for character in ("_", ".", "-"))
            if not (looks_like_accession or has_nested_delimiter):
                return stem, "", False, ""
        return prefix, "1" if tag.endswith("1") else "2", bool(tag.startswith("R")), separator
    match = re.match(r"(?i)^(?P<prefix>.+?)(?P<tag>R[12])$", stem)
    if match:
        tag = match.group("tag").upper()
        return match.group("prefix"), "1" if tag.endswith("1") else "2", True, ""
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
    parent, stem, extension = split_fastq_name(name)
    prefix, read, has_r, separator = split_read_suffix(stem)
    if not read:
        return []

    target_read = "2" if read == "1" else "1"
    token_order = [f"R{target_read}", target_read] if has_r else [target_read, f"R{target_read}"]
    separators: list[str] = []
    if separator:
        separators.append(separator)
    for alternative in ("_", ".", "-"):
        if alternative not in separators:
            separators.append(alternative)

    suffixes: list[str] = []
    if not separator:
        suffixes.extend(token_order)
    for candidate_separator in separators:
        suffixes.extend(f"{candidate_separator}{token}" for token in token_order)

    candidates: list[str] = []
    seen: set[str] = set()
    for suffix in suffixes:
        candidate = _join_path(parent, f"{prefix}{suffix}{extension}")
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


def read_counts(paths: Iterable[str]) -> dict[str, int]:
    r1, r2, unknown = 0, 0, 0
    for path in paths or []:
        side = read_side(path)
        if side == "1":
            r1 += 1
        elif side == "2":
            r2 += 1
        else:
            unknown += 1
    return {"r1": r1, "r2": r2, "unknown": unknown}
