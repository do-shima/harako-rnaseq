#!/usr/bin/env python3
"""Audit Git-reachable history without printing sensitive values."""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import pathlib
import re
import subprocess
import sys
from collections import Counter
from typing import BinaryIO, Iterable


SECRET_PATTERNS = {
    "private_key": re.compile(
        (r"-----BEGIN (?:RSA |EC |OPENSSH )?" + r"PRIVATE KEY-----").encode()
    ),
    "github_token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "aws_access_key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "credential_assignment": re.compile(
        rb"(?i)\b(?:password|passwd|api[_-]?key|authorization)\b\s*[:=]\s*"
        rb"(?:basic |bearer )?[\"']?[A-Za-z0-9+/=_-]{12,}"
    ),
    "credential_url": re.compile(rb"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
}
PRIVATE_PATH_PATTERNS = {
    "windows_user_path": re.compile(rb"(?i)\b[A-Z]:\\Users\\([^\\\r\n]+)\\"),
    "unix_home_path": re.compile(rb"(?m)(?<![A-Za-z0-9_])/(?:home|Users)/([^/\r\n]+)/"),
    "unc_path": re.compile(rb"(?i)\\\\(?!server\\share)[A-Za-z0-9._-]+\\[A-Za-z0-9$._-]+\\"),
}
SECRET_FILENAMES = re.compile(
    r"(?i)(^|/)(?:\.env(?:\..*)?|id_(?:rsa|dsa|ecdsa|ed25519)|"
    r"docker-config\.json|credentials(?:\.json)?|.*private.*\.pem)$"
)
BIOLOGICAL_EXTENSIONS = {
    ".fastq",
    ".fq",
    ".bam",
    ".cram",
    ".sam",
    ".vcf",
    ".bcf",
    ".fasta",
    ".fa",
    ".gtf",
    ".gff",
    ".gff3",
}
GENERATED_PARTS = {
    ".snakemake",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "output",
    "data_out",
    "ui_sessions",
    "refs_cache",
}
TEXT_EXTENSIONS = {
    ".cfg",
    ".cff",
    ".csv",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".r",
    ".rmd",
    ".sh",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
MAX_TEXT_SCAN = 2 * 1024 * 1024
LARGE_BLOB = 1024 * 1024
REVIEW_BLOB = 10 * 1024 * 1024
BLOCK_BLOB = 50 * 1024 * 1024


def _git(repo: pathlib.Path, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _masked_identity(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _classification_for_path(path: str, size: int) -> tuple[str, str]:
    normalized = path.replace("\\", "/")
    lower = normalized.lower()
    suffix = pathlib.PurePosixPath(lower).suffix
    parts = set(pathlib.PurePosixPath(lower).parts)
    fixture = lower.startswith("tests/") and size < REVIEW_BLOB
    if SECRET_FILENAMES.search(lower):
        return "public-release blocker", "credential-bearing filename"
    if suffix in BIOLOGICAL_EXTENSIONS:
        if fixture:
            return "expected fixture/example", "small biological test fixture"
        if size >= BLOCK_BLOB:
            return "public-release blocker", "large biological-data blob"
        return "requires maintainer review", "biological-data filename"
    if parts & GENERATED_PARTS or suffix in {".log", ".pyc"}:
        return "requires maintainer review", "generated/internal file"
    if re.search(r"(?i)(patient|clinical|subject[_ -]?id|phi)", normalized):
        return "requires maintainer review", "potential confidential-data filename"
    if size >= BLOCK_BLOB:
        return "public-release blocker", "blob is at least 50 MiB"
    if size >= REVIEW_BLOB:
        return "requires maintainer review", "blob is at least 10 MiB"
    if size >= LARGE_BLOB:
        return "requires maintainer review", "blob is at least 1 MiB"
    return "clean", ""


def _scan_content(path: str, data: bytes) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for category, pattern in SECRET_PATTERNS.items():
        if pattern.search(data):
            findings.append(
                {
                    "category": category,
                    "classification": "public-release blocker",
                    "detail": "credential-like content; value redacted",
                }
            )
    generic_users = {b"user", b"username", b"example", b"alice", b"bob"}
    for category, pattern in PRIVATE_PATH_PATTERNS.items():
        match = pattern.search(data)
        if match and (not match.groups() or match.group(1).lower() not in generic_users):
            findings.append(
                {
                    "category": category,
                    "classification": "requires maintainer review",
                    "detail": "user-specific local path; value redacted",
                }
            )
    if pathlib.PurePosixPath(path.lower()).name.startswith(".env") and data.strip():
        findings.append(
            {
                "category": "environment_file",
                "classification": "public-release blocker",
                "detail": "non-empty environment file; content redacted",
            }
        )
    return findings


def _blob_is_text(path: str, data: bytes) -> bool:
    if pathlib.PurePosixPath(path.lower()).suffix in TEXT_EXTENSIONS:
        return b"\x00" not in data[:8192]
    return b"\x00" not in data[:8192] and bool(data[:8192].strip())


def _read_blob(repo: pathlib.Path, oid: str, size: int) -> bytes:
    if size > MAX_TEXT_SCAN:
        return b""
    result = _git(repo, "cat-file", "blob", oid)
    return result.stdout if result.returncode == 0 else b""


def _first_introducing_commit(repo: pathlib.Path, path: str, oid: str) -> str:
    result = _git(
        repo,
        "log",
        "--all",
        "--reverse",
        "--format=%H",
        f"--find-object={oid}",
        "--",
        path,
    )
    lines = _decode(result.stdout).splitlines()
    return lines[0] if lines else ""


def _current_tree_contains(repo: pathlib.Path, path: str, oid: str) -> bool:
    result = _git(repo, "rev-parse", f"HEAD:{path}")
    return result.returncode == 0 and _decode(result.stdout).strip() == oid


def _reachable_objects(repo: pathlib.Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    revision_stream = subprocess.Popen(
        ["git", "rev-list", "--objects", "--all"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert revision_stream.stdout is not None
    batch = subprocess.Popen(
        ["git", "cat-file", "--batch-check=%(objectname)\t%(objecttype)\t%(objectsize)"],
        cwd=repo,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert batch.stdin is not None and batch.stdout is not None

    seen: set[str] = set()
    findings: list[dict[str, object]] = []
    largest: list[tuple[int, str, str]] = []
    object_counts: Counter[str] = Counter()
    blob_bytes = 0

    for raw in revision_stream.stdout:
        line = _decode(raw).rstrip("\n")
        oid, _, path = line.partition(" ")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        batch.stdin.write((oid + "\n").encode())
        batch.stdin.flush()
        header = _decode(batch.stdout.readline()).rstrip("\n").split("\t")
        if len(header) != 3:
            continue
        _, object_type, size_text = header
        object_counts[object_type] += 1
        if object_type != "blob":
            continue
        size = int(size_text)
        blob_bytes += size
        heapq.heappush(largest, (size, oid, path))
        if len(largest) > 50:
            heapq.heappop(largest)
        classification, detail = _classification_for_path(path, size)
        if classification != "clean":
            findings.append(
                {
                    "object": oid,
                    "path": path,
                    "size": size,
                    "category": "filename_or_size",
                    "classification": classification,
                    "detail": detail,
                }
            )
        data = _read_blob(repo, oid, size)
        if data and _blob_is_text(path, data):
            for content_finding in _scan_content(path, data):
                findings.append({"object": oid, "path": path, "size": size, **content_finding})

    batch.stdin.close()
    batch.wait()
    _, revision_stderr = revision_stream.communicate()
    if revision_stream.returncode:
        raise RuntimeError(_decode(revision_stderr))

    largest_rows = []
    for size, oid, path in sorted(largest, reverse=True):
        largest_rows.append(
            {
                "object": oid,
                "path": path,
                "size": size,
                "first_introducing_commit": _first_introducing_commit(repo, path, oid)
                if size >= LARGE_BLOB
                else "",
                "present_in_head": _current_tree_contains(repo, path, oid),
                "classification": _classification_for_path(path, size)[0],
            }
        )
    summary = {
        "reachable_object_count": len(seen),
        "reachable_object_types": dict(sorted(object_counts.items())),
        "reachable_blob_bytes": blob_bytes,
        "largest_blobs": largest_rows,
    }
    return summary, findings


def _commit_and_identity_audit(
    repo: pathlib.Path,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, str]]]:
    format_string = "%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%G?%x1f%B%x1e"
    result = _git(repo, "log", "--all", f"--format={format_string}")
    if result.returncode:
        raise RuntimeError(_decode(result.stderr))
    identity_rows: dict[tuple[str, ...], dict[str, str]] = {}
    findings: list[dict[str, object]] = []
    commits = 0
    signature_counts: Counter[str] = Counter()
    for record in _decode(result.stdout).split("\x1e"):
        fields = record.strip().split("\x1f", 6)
        if len(fields) != 7:
            continue
        oid, author, author_email, committer, committer_email, signature, message = fields
        commits += 1
        signature_counts[signature] += 1
        key = (author, author_email, committer, committer_email, signature)
        identity_rows[key] = {
            "author_name": author,
            "author_email": author_email,
            "committer_name": committer,
            "committer_email": committer_email,
            "signature_status": signature,
        }
        for content_finding in _scan_content("commit-message", message.encode()):
            findings.append(
                {
                    "commit": oid,
                    "path": "",
                    "size": len(message),
                    **content_finding,
                }
            )
    sanitized = []
    for row in identity_rows.values():
        email_values = {row["author_email"], row["committer_email"]}
        kind = (
            "github_noreply"
            if all(value.endswith("@users.noreply.github.com") or value == "noreply@github.com" for value in email_values)
            else "public but personally identifying metadata"
        )
        sanitized.append(
            {
                "identity_id": _masked_identity("|".join(row.values())),
                "classification": kind,
                "signature_status": row["signature_status"],
            }
        )
    return (
        {
            "commit_count": commits,
            "unique_identity_count": len(identity_rows),
            "signature_status_counts": dict(sorted(signature_counts.items())),
            "identities": sanitized,
        },
        findings,
        sorted(identity_rows.values(), key=lambda row: tuple(row.values())),
    )


def _refs(repo: pathlib.Path) -> list[dict[str, str]]:
    result = _git(
        repo,
        "for-each-ref",
        "--format=%(refname)%09%(objecttype)%09%(objectname)%09%(subject)",
    )
    rows = []
    for line in _decode(result.stdout).splitlines():
        ref, object_type, oid, subject = (line.split("\t", 3) + ["", "", "", ""])[:4]
        rows.append({"ref": ref, "object_type": object_type, "object": oid, "subject": subject})
    return rows


def audit_repository(repo: pathlib.Path) -> tuple[dict[str, object], list[dict[str, str]]]:
    repo = repo.resolve()
    if _git(repo, "rev-parse", "--is-inside-work-tree").returncode:
        raise ValueError(f"not a Git repository: {repo}")
    reachable, findings = _reachable_objects(repo)
    identities, commit_findings, raw_identities = _commit_and_identity_audit(repo)
    findings.extend(commit_findings)
    deduplicated: dict[tuple[object, ...], dict[str, object]] = {}
    for finding in findings:
        key = (
            finding.get("object"),
            finding.get("commit"),
            finding.get("path"),
            finding.get("category"),
            finding.get("classification"),
        )
        deduplicated[key] = finding
    findings = sorted(
        deduplicated.values(),
        key=lambda item: (
            str(item.get("classification")),
            str(item.get("path")),
            str(item.get("category")),
        ),
    )
    counts = Counter(str(item["classification"]) for item in findings)
    blockers = counts["public-release blocker"]
    payload: dict[str, object] = {
        "schema_version": 1,
        "scope": "objects reachable from git rev-list --objects --all",
        "network_used": False,
        "git_mutated": False,
        "status": "blocked" if blockers else "clean_with_review" if findings else "clean",
        "classification_counts": dict(sorted(counts.items())),
        "refs": _refs(repo),
        "reachable": reachable,
        "identity_summary": identities,
        "findings": findings,
        "limitations": [
            "Content heuristics cannot guarantee the absence of protected health information.",
            "Unreachable and reflog-only objects are excluded from the public-reachability result.",
            "Secret patterns are intentionally conservative and require human review.",
        ],
    }
    return payload, raw_identities


def _write_identity_tsv(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _write_text(path: pathlib.Path, payload: dict[str, object]) -> None:
    reachable = payload["reachable"]
    assert isinstance(reachable, dict)
    lines = [
        "Harako-RNAseq reachable Git history audit",
        f"Status: {payload['status']}",
        f"Reachable objects: {reachable['reachable_object_count']}",
        f"Reachable blob bytes: {reachable['reachable_blob_bytes']}",
        f"Unique identities: {payload['identity_summary']['unique_identity_count']}",
        "Classification counts:",
    ]
    counts = payload["classification_counts"]
    assert isinstance(counts, dict)
    lines.extend(f"- {name}: {count}" for name, count in counts.items())
    lines.append("Sensitive values and raw identity addresses are omitted from this summary.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--json-report", type=pathlib.Path, required=True)
    parser.add_argument("--text-report", type=pathlib.Path, required=True)
    parser.add_argument("--identity-report", type=pathlib.Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    payload, identities = audit_repository(args.repo)
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    _write_text(args.text_report, payload)
    identity_path = args.identity_report or args.json_report.with_name("git-identities.tsv")
    if identities:
        _write_identity_tsv(identity_path, identities)
    print(
        f"status={payload['status']} reachable={payload['reachable']['reachable_object_count']} "
        f"findings={len(payload['findings'])}"
    )
    return 1 if args.strict and payload["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
