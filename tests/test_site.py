from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

import yaml


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PAGES_PREFIX = "https://do-shima.github.io/harako-rnaseq/"
EXPECTED_HTML = {
    "index.html",
    "ja/index.html",
    "installation/index.html",
    "methods/index.html",
    "outputs/index.html",
    "404.html",
}
SITEMAP_PATHS = {
    "",
    "ja/",
    "installation/",
    "methods/",
    "outputs/",
}
EXPECTED_REFERENCE_SHA256 = {
    "34f848e2dd9c2a4e30d6ff2c7918a3e06c51fe1716c1e955e71e0c36ce28d5ad",
    "d8c3af0094a7bba6125763bad779ec18a81483c739c6ed122094bdf86c187b92",
    "62f1709b40e083ce9d4cdc64a86b5ffec2c5d5371434bb7095c74dc89079c466",
    "eafd274cdf83d440432ce6d2eccc34571b00cd966bcd5f84bd1fe17bbb8e54ae",
    "c661d19cfdbbee7ffbafa9bffb44581c6306480b9fef7b70e1d9c173782d370f",
    "b9fb3539f9883ae1c4b38a4e26d61e8a5367d59b175edf74fb2dadf0866840cf",
    "2947b18c23ca387ca5509a298c8feaa09b719c0110852851892e973da60ff655",
    "285bc481d583ab65b13d91853bf743acf950710afb3302264a4b4f116b6049c1",
    "8321415404aaf788c7da79774488ff227ac006d09a57ce6c616573a510338f64",
    "379c3ad238f12169fd397398c77aaff5435ec23bca74324bb8a886bd26511b09",
    "9e0cd229e1f0bc3c93e104c394a17ded4d30ef8acf30e6e4f6692a04c8160920",
    "402aefe269ecccba845a8a03137304af4356455c83b77453f799001974b4eb7c",
}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.script_parts: list[str] = []
        self.current_script_is_jsonld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            self.meta.append(values)
        elif tag in {"a", "link"}:
            self.links.append({"tag": tag, **values})
        elif tag == "script":
            self.scripts.append(values)
            self.current_script_is_jsonld = values.get("type") == "application/ld+json"

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "script":
            self.current_script_is_jsonld = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.current_script_is_jsonld:
            self.script_parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self.title_parts).strip()

    def named_meta(self, name: str) -> str:
        return next((item.get("content", "") for item in self.meta if item.get("name") == name), "")

    def linked(self, rel: str, **expected: str) -> list[dict[str, str]]:
        return [
            link
            for link in self.links
            if rel in link.get("rel", "").split()
            and all(link.get(key) == value for key, value in expected.items())
        ]


def parse_page(relative: str) -> PageParser:
    parser = PageParser()
    parser.feed((SITE / relative).read_text(encoding="utf-8"))
    return parser


def site_path_for_url(url: str) -> Path | None:
    if not url.startswith(PAGES_PREFIX):
        return None
    relative = unquote(url.removeprefix(PAGES_PREFIX))
    target = SITE / relative
    return target / "index.html" if relative.endswith("/") or not relative else target


def local_target(source: Path, href: str) -> Path | None:
    split = urlsplit(href)
    if split.scheme or split.netloc or href.startswith("#"):
        return site_path_for_url(href)
    relative = unquote(split.path)
    if not relative:
        return None
    target = (source.parent / relative).resolve()
    if relative.endswith("/"):
        target /= "index.html"
    return target


def test_expected_site_files_exist() -> None:
    expected = {
        *EXPECTED_HTML,
        "assets/site.css",
        "assets/harako-logo.png",
        "robots.txt",
        "sitemap.xml",
        ".nojekyll",
    }
    assert not [relative for relative in sorted(expected) if not (SITE / relative).is_file()]


def test_homepages_use_prescribed_search_snippets_and_visible_headings() -> None:
    expected = {
        "index.html": (
            "Harako-RNAseq | Graphical Bulk RNA-seq Pipeline",
            "Harako-RNAseq is a reproducible Docker-based bulk RNA-seq GUI for Windows and Linux using fastp, Salmon, tximport, DESeq2, QC-only mode, and self-contained HTML reports.",
        ),
        "ja/index.html": (
            "Harako-RNAseq | Dockerで動くバルクRNA-seq解析GUI",
            "Harako-RNAseqは、fastp、Salmon、tximport、DESeq2を統合し、WindowsとLinuxで再現可能に動作するバルクRNA-seq解析GUIです。",
        ),
    }
    for relative, (title, description) in expected.items():
        page = parse_page(relative)
        text = (SITE / relative).read_text(encoding="utf-8")
        assert page.title == title
        assert page.named_meta("description") == description
        assert "<h1>Harako-RNAseq</h1>" in text


def test_site_uses_clear_scientific_language() -> None:
    html = "\n".join(path.read_text(encoding="utf-8") for path in SITE.rglob("*.html"))
    old_phrases = {
        "The Docker RNA-seq analysis path",
        "Designed for honest local analysis",
        "fabricated p-values",
        "解析結果を過大に見せない設計",
        "構造上有効な設計",
        "p値や調整p値を作りません",
        "記述的TPM",
        "参照配列と注釈の由来",
    }
    assert not {phrase for phrase in old_phrases if phrase in html}

    required_phrases = {
        "The Docker-based RNA-seq workflow",
        "Designed to avoid unsupported inference",
        "without reporting p-values or adjusted p-values",
        "gene-level TPM",
        "遺伝子発現変動解析",
        "発現変動解析",
        "解析条件に応じた統計処理",
        "最小反復条件",
        "p値や調整p値は算出・出力しません",
        "発現量指標としてのTPM",
        "アノテーションの由来情報",
    }
    assert not {phrase for phrase in required_phrases if phrase not in html}
    assert (
        "minimum analysis requirements" in html
        or "minimum replication requirements" in html
    )


def test_readmes_link_the_project_website_near_the_top() -> None:
    for name in ("README.md", "README.ja.md"):
        opening = "\n".join((ROOT / name).read_text(encoding="utf-8").splitlines()[:15])
        assert PAGES_PREFIX in opening


def test_titles_descriptions_canonicals_and_open_graph_are_complete() -> None:
    titles: set[str] = set()
    descriptions: set[str] = set()
    for relative in EXPECTED_HTML:
        page = parse_page(relative)
        description = page.named_meta("description").strip()
        assert page.title
        assert description
        assert page.title not in titles
        assert description not in descriptions
        titles.add(page.title)
        descriptions.add(description)

        canonical = page.linked("canonical")
        assert len(canonical) == 1
        assert canonical[0]["href"].startswith(PAGES_PREFIX)
        properties = {item.get("property"): item.get("content", "") for item in page.meta}
        for field in ("og:title", "og:description", "og:type", "og:url", "og:image"):
            assert properties.get(field), f"{relative}: {field}"
        assert properties["og:url"] == canonical[0]["href"]
        assert properties["og:image"] == PAGES_PREFIX + "assets/harako-logo.png"


def test_home_hreflang_links_are_reciprocal() -> None:
    expected = {
        "en": PAGES_PREFIX,
        "ja": PAGES_PREFIX + "ja/",
        "x-default": PAGES_PREFIX,
    }
    for relative in ("index.html", "ja/index.html"):
        page = parse_page(relative)
        actual = {
            link["hreflang"]: link["href"]
            for link in page.linked("alternate")
            if "hreflang" in link
        }
        assert actual == expected


def test_local_html_and_asset_links_resolve() -> None:
    broken: list[str] = []
    for relative in EXPECTED_HTML:
        source = SITE / relative
        page = parse_page(relative)
        for link in page.links:
            href = link.get("href", "")
            target = local_target(source, href)
            if target is not None and not target.exists():
                broken.append(f"{relative} -> {href}")
    assert not broken, "\n".join(sorted(broken))


def test_sitemap_matches_existing_index_pages_and_robots_references_it() -> None:
    tree = ElementTree.parse(SITE / "sitemap.xml")
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = {element.text for element in tree.findall("sm:url/sm:loc", namespace)}
    assert urls == {PAGES_PREFIX + path for path in SITEMAP_PATHS}
    assert all(site_path_for_url(url).is_file() for url in urls)

    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    assert re.search(r"(?im)^User-agent:\s*\*$", robots)
    assert re.search(r"(?im)^Allow:\s*/$", robots)
    assert f"Sitemap: {PAGES_PREFIX}sitemap.xml" in robots


def test_pages_are_indexable_and_have_no_external_runtime_dependencies() -> None:
    for relative in EXPECTED_HTML:
        text = (SITE / relative).read_text(encoding="utf-8")
        page = parse_page(relative)
        assert "noindex" not in text.lower()
        assert all(not script.get("src") for script in page.scripts)
        for link in page.linked("stylesheet"):
            assert not urlsplit(link["href"]).scheme

    css = (SITE / "assets" / "site.css").read_text(encoding="utf-8")
    assert "@import" not in css.lower()
    assert not re.search(r"url\(\s*['\"]?https?://", css, re.IGNORECASE)


def test_software_application_jsonld_is_factual() -> None:
    required_pages = EXPECTED_HTML - {"404.html"}
    required = {
        "name": "Harako-RNAseq",
        "alternateName": "Harako RNAseq",
        "softwareVersion": "0.2.0-beta.1",
        "operatingSystem": "Windows and Linux through Docker",
        "applicationSubCategory": "Bioinformatics",
        "codeRepository": "https://github.com/do-shima/harako-rnaseq",
        "downloadUrl": "https://github.com/do-shima/harako-rnaseq/releases/tag/v0.2.0-beta.1",
        "license": "https://polyformproject.org/licenses/noncommercial/1.0.0/",
        "isAccessibleForFree": True,
    }
    for relative in required_pages:
        page = parse_page(relative)
        assert page.script_parts
        payload = json.loads("".join(page.script_parts))
        assert payload["@type"] == "SoftwareApplication"
        assert payload["description"].strip()
        for field, value in required.items():
            assert payload[field] == value
        assert payload["author"] == {"@type": "Person", "name": "Daisuke Ohshima"}
        assert payload["offers"]["price"] == 0
        assert "aggregateRating" not in payload
        assert "review" not in payload


def test_all_twelve_reference_checksums_remain_unchanged() -> None:
    manifest = yaml.safe_load((ROOT / "workflow" / "ref_manifest.yaml").read_text(encoding="utf-8"))
    actual = {
        digest
        for releases in manifest["presets"].values()
        for release in releases.values()
        for digest in release["sha256"].values()
    }
    assert len(actual) == 12
    assert actual == EXPECTED_REFERENCE_SHA256
