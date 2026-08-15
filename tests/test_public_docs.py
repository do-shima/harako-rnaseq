from __future__ import annotations

import re
from html.parser import HTMLParser
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


class ReadmeImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_link: str | None = None
        self.images: list[tuple[dict[str, str | None], str | None]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "a":
            self.current_link = attributes.get("href")
        elif tag == "img":
            self.images.append((attributes, self.current_link))

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.current_link = None


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


def test_readmes_show_localized_gui_summary_previews():
    previews = (
        {
            "readme": ROOT / "README.md",
            "heading": "## GUI preview",
            "overview": "## Overview",
            "asset": "site/assets/screenshots/gui-summary-en.webp",
            "other_locale": "site/assets/screenshots/gui-summary-ja.webp",
            "alt": (
                "Harako-RNAseq Summary page showing a synthetic four-sample "
                "workflow and the Save, Validate, Dry run, and Run actions"
            ),
            "caption": (
                "Representative Harako-RNAseq interface using synthetic "
                "demonstration data.\n  No real biological data are shown."
            ),
        },
        {
            "readme": ROOT / "README.ja.md",
            "heading": "## GUI画面",
            "overview": "## 概要",
            "asset": "site/assets/screenshots/gui-summary-ja.webp",
            "other_locale": "site/assets/screenshots/gui-summary-en.webp",
            "alt": (
                "合成4サンプルの解析設定と、保存、検証、ドライラン、実行の操作を"
                "表示したHarako-RNAseqのまとめ画面"
            ),
            "caption": (
                "合成デモデータを用いたHarako-RNAseqの画面です。\n  "
                "実際の生物学的データは含まれていません。"
            ),
        },
    )

    for preview in previews:
        text = read(preview["readme"])
        asset = preview["asset"]
        parser = ReadmeImageParser()
        parser.feed(text)
        matching_images = [
            (attributes, link)
            for attributes, link in parser.images
            if attributes.get("src") == asset
        ]

        assert (ROOT / asset).is_file()
        assert preview["other_locale"] not in text
        assert preview["caption"] in text
        assert len(matching_images) == 1
        attributes, link = matching_images[0]
        assert attributes.get("alt") == preview["alt"]
        assert link == asset
        assert text.index("icon/Harako-logo.png") < text.index(preview["heading"])
        assert text.index(preview["heading"]) < text.index(preview["overview"])


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


def test_public_docs_make_the_exact_published_image_the_primary_path():
    public_paths = (
        *READMES,
        ROOT / "docs" / "installation.md",
        ROOT / "site" / "installation" / "index.html",
        ROOT / "site" / "ja" / "installation" / "index.html",
    )
    public_text = "\n".join(read(path) for path in public_paths)
    assert "ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.2" in public_text
    assert "ghcr.io/do-shima/harako-rnaseq:beta" in public_text
    assert "127.0.0.1:8501:8501" in public_text
    assert "dst=/input,readonly" in public_text
    assert "dst=/output" in public_text
    assert "streamlit run app/ui/app_ui.py" in public_text

    all_current_docs = public_text + read(ROOT / "docs" / "container-image.md")
    assert "IMAGE=ghcr.io" not in all_current_docs
    assert '$env:IMAGE = "ghcr.io' not in all_current_docs
    assert "No public prebuilt image is claimed" not in all_current_docs


def test_readmes_and_provenance_explain_the_adopted_harako_backronym():
    expansion = "Human-Auditable, Reproducible Analysis Kit and Orchestrator"
    english = read(ROOT / "README.md")
    japanese = read(ROOT / "README.ja.md")
    provenance = read(ROOT / "docs" / "provenance.md")

    assert english.count(expansion) == 1
    assert japanese.count(expansion) == 1
    assert "*harako*—salmon roe" in english
    assert "はらこ（鮭の卵）" in japanese
    assert "backronym" in english
    assert "backronymとしても位置づけています" in japanese
    assert "did not precede the Japanese name historically" in english
    assert "後から採用した" in japanese
    assert "not the original chronological naming process" in provenance
    assert "independently implemented" in provenance
    assert "not an official successor" in provenance

    current_text = "\n".join((english, japanese, provenance))
    forbidden = (
        "HARAKO originally stood for",
        "HARAKOは本来",
        "automatic scientific auditing",
        "guaranteed reproducibility",
        "完全な再現性を保証",
    )
    assert not {phrase for phrase in forbidden if phrase in current_text}
