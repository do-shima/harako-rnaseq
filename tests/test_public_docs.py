from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
READMES = (ROOT / "README.md", ROOT / "README.ja.md")
REQUIRED_PUBLIC_FILES = (
    ROOT / "LICENSE",
    ROOT / "CITATION.cff",
    ROOT / "SUPPORT.md",
    ROOT / "SECURITY.md",
    ROOT / "COMMERCIAL_LICENSE.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    ROOT / "docs" / "index.md",
    ROOT / "docs" / "installation.md",
    ROOT / "docs" / "usage.md",
    ROOT / "docs" / "sra-ena.md",
    ROOT / "docs" / "troubleshooting.md",
    ROOT / "docs" / "advanced-usage.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "support-matrix.md",
)
PUBLIC_MARKDOWN = (
    *READMES,
    ROOT / "CONTRIBUTING.md",
    ROOT / "SUPPORT.md",
    ROOT / "SECURITY.md",
    ROOT / "COMMERCIAL_LICENSE.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    *sorted((ROOT / "docs").glob("*.md")),
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
JUST_COMMAND = re.compile(r"(?<![\w-])just\s+([A-Za-z0-9][A-Za-z0-9_-]*)")
JUST_TARGET = re.compile(r"^([A-Za-z0-9_-]+)(?:\s+[^:]*)?:", re.MULTILINE)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def local_link_target(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().strip("<>")
    if not target or target.startswith("#"):
        return None
    split = urlsplit(target)
    if split.scheme or split.netloc:
        return None
    path_text = unquote(split.path)
    if not path_text:
        return None
    return (source.parent / path_text).resolve()


def test_required_public_files_and_headings_exist():
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_PUBLIC_FILES if not path.is_file()]
    assert not missing
    for readme in READMES:
        assert read(readme).startswith("# Harako-RNAseq\n")
    assert (ROOT / "icon" / "Harako-logo.png").is_file()


def test_readmes_link_required_public_metadata():
    required = {
        "LICENSE",
        "CITATION.cff",
        "docs/index.md",
        "SUPPORT.md",
        "COMMERCIAL_LICENSE.md",
    }
    for readme in READMES:
        text = read(readme)
        targets = {match.group(1).split("#", 1)[0] for match in MARKDOWN_LINK.finditer(text)}
        assert required <= targets, f"{readme.name} missing {sorted(required - targets)}"


def test_repository_relative_public_markdown_links_resolve():
    broken: list[str] = []
    for source in PUBLIC_MARKDOWN:
        for match in MARKDOWN_LINK.finditer(read(source)):
            target = local_link_target(source, match.group(1))
            if target is not None and not target.exists():
                broken.append(
                    f"{source.relative_to(ROOT)} -> {match.group(1)}"
                )
    assert not broken, "\n".join(broken)


def test_documented_just_commands_are_real_targets():
    targets = set(JUST_TARGET.findall(read(ROOT / "justfile")))
    unknown: list[str] = []
    for source in PUBLIC_MARKDOWN:
        for target in JUST_COMMAND.findall(read(source)):
            if target not in targets:
                unknown.append(f"{source.relative_to(ROOT)}: just {target}")
    assert not unknown, "\n".join(sorted(set(unknown)))


def test_readmes_use_current_public_beta_claims():
    banned = (
        "pipeline skeleton",
        "open source",
        "open-source",
        "OSI-approved",
        "<REPLACE_WITH_",
    )
    for readme in READMES:
        text = read(readme)
        lowered = text.lower()
        assert not any(term.lower() in lowered for term in banned)
        assert not re.search(r"[A-Za-z]:\\Users\\[^\\\s]+", text)
        assert "QC-only" in text
        assert "Ensembl" in text
        assert "PolyForm Noncommercial License 1.0.0" in text
    assert "source-available" in read(READMES[0])
    assert "local, single-user" in read(READMES[0])
    assert "source-available" in read(READMES[1])
    assert "ローカル・単一ユーザー" in read(READMES[1])


def test_dockerignore_has_patterns_not_task_prose():
    text = read(ROOT / ".dockerignore")
    lowered = text.lower()
    for phrase in ("codex task", "deliverable:", "current docker build transfers", "commit the .dockerignore"):
        assert phrase not in lowered
    for fixture in (
        "!tests/**/*.fastq.gz",
        "!tests/**/*.fa",
        "!tests/**/*.gtf",
        "!tests/**/*.tsv",
        "!tests/**/*.json",
    ):
        assert fixture in text


def test_documentation_index_links_every_public_doc():
    index = read(ROOT / "docs" / "index.md")
    linked_names = {
        Path(match.group(1).split("#", 1)[0]).name
        for match in MARKDOWN_LINK.finditer(index)
    }
    expected_names = {
        path.name
        for path in (ROOT / "docs").glob("*.md")
        if path.name != "index.md"
    }
    assert expected_names <= linked_names, sorted(expected_names - linked_names)


def test_public_docs_do_not_claim_a_published_prebuilt_image():
    text = "\n".join(read(path) for path in PUBLIC_MARKDOWN)
    lowered = text.lower()
    assert "ghcr.io/do-shima/harako-rnaseq" not in lowered
    assert "image=ghcr.io" not in lowered
    assert "prebuilt image is available" not in lowered
