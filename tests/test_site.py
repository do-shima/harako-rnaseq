from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

import yaml
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PAGES_PREFIX = "https://do-shima.github.io/harako-rnaseq/"
PAGE_PAIRS = {
    "": "ja/",
    "installation/": "ja/installation/",
    "methods/": "ja/methods/",
    "outputs/": "ja/outputs/",
}
CONTENT_HTML = {
    f"{path}index.html" for pair in PAGE_PAIRS.items() for path in pair
}
EXPECTED_HTML = CONTENT_HTML | {"404.html"}
SITEMAP_PATHS = {path for pair in PAGE_PAIRS.items() for path in pair}
GITHUB_URL = "https://github.com/do-shima/harako-rnaseq"
JAPANESE_METADATA = {
    "ja/index.html": (
        "Harako-RNAseq | FASTQからDESeq2までのバルクRNA-seq解析ワークフロー",
        "Harako-RNAseqは、FASTQの前処理からSalmon、tximport、DESeq2またはQC-only解析、HTMLレポート作成までを実行するDockerベースのバルクRNA-seq解析GUIです。",
    ),
    "ja/installation/index.html": (
        "Harako-RNAseq | Windows・Linuxへの導入方法",
        "Harako-RNAseqをWindows Docker DesktopまたはUbuntu/Linuxへ導入する方法、必要なCPU・メモリ・ディスク容量、Dockerイメージの利用方法を説明します。",
    ),
    "ja/methods/index.html": (
        "Harako-RNAseq | 解析手法と適用上の制約",
        "fastp、Salmon、tximport、DESeq2によるHarako-RNAseqの解析フロー、カウント値とTPMの役割、最小サンプル数要件、QC-onlyモード、参照情報を説明します。",
    ),
    "ja/outputs/index.html": (
        "Harako-RNAseq | 出力ファイルとHTMLレポート",
        "fastp QC、Salmon quant.sf、遺伝子レベルのカウント値とTPM、DESeq2の解析状態、保存されたRun情報、自己完結型HTMLレポートを説明します。",
    ),
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
SCREENSHOTS = {
    "assets/screenshots/gui-samples-en.webp",
    "assets/screenshots/gui-summary-en.webp",
    "assets/screenshots/gui-samples-ja.webp",
    "assets/screenshots/gui-summary-ja.webp",
}
AI_CONSULT_SCRIPT = SITE / "assets" / "ai-consult.js"


class ScreenshotParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.figures: list[dict[str, object]] = []
        self.current: dict[str, object] | None = None
        self.in_caption = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = values.get("class", "").split()
        if tag == "figure" and "screenshot-card" in classes:
            self.current = {"link": {}, "image": {}, "caption": ""}
        elif self.current is not None and tag == "a":
            self.current["link"] = values
        elif self.current is not None and tag == "img":
            self.current["image"] = values
        elif self.current is not None and tag == "figcaption":
            self.in_caption = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "figcaption":
            self.in_caption = False
        elif tag == "figure" and self.current is not None:
            self.figures.append(self.current)
            self.current = None

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.in_caption:
            self.current["caption"] = str(self.current["caption"]) + data


def screenshot_figures(relative: str) -> list[dict[str, object]]:
    parser = ScreenshotParser()
    parser.feed((SITE / relative).read_text(encoding="utf-8"))
    return parser.figures


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
        self.lang = ""
        self.in_header = False
        self.in_footer = False
        self.footer_parts: list[str] = []
        self.current_anchor: dict[str, str] | None = None
        self.header_links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "html":
            self.lang = values.get("lang", "")
        elif tag == "header":
            self.in_header = True
        elif tag == "footer":
            self.in_footer = True
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            self.meta.append(values)
        elif tag == "a":
            link = {"tag": tag, "text": "", **values}
            self.links.append(link)
            self.current_anchor = link
            if self.in_header:
                self.header_links.append(link)
        elif tag == "link":
            self.links.append({"tag": tag, **values})
        elif tag == "script":
            self.scripts.append(values)
            self.current_script_is_jsonld = values.get("type") == "application/ld+json"

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "a":
            self.current_anchor = None
        elif tag == "header":
            self.in_header = False
        elif tag == "footer":
            self.in_footer = False
        elif tag == "script":
            self.current_script_is_jsonld = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.current_anchor is not None:
            self.current_anchor["text"] += data
        if self.in_footer:
            self.footer_parts.append(data)
        if self.current_script_is_jsonld:
            self.script_parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self.title_parts).strip()

    @property
    def footer_text(self) -> str:
        return " ".join("".join(self.footer_parts).split())

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


def public_url(relative: str) -> str:
    if relative == "index.html":
        return PAGES_PREFIX
    if relative.endswith("index.html"):
        return PAGES_PREFIX + relative.removesuffix("index.html")
    return PAGES_PREFIX + relative


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
    assert len(CONTENT_HTML) == 8
    expected = {
        *EXPECTED_HTML,
        *SCREENSHOTS,
        "assets/ai-consult.js",
        "assets/site.css",
        "assets/harako-logo.png",
        "robots.txt",
        "sitemap.xml",
        ".nojekyll",
    }
    assert not [relative for relative in sorted(expected) if not (SITE / relative).is_file()]


def test_every_public_page_loads_the_shared_ai_consult_launcher() -> None:
    for relative in CONTENT_HTML:
        source = SITE / relative
        scripts = [script for script in parse_page(relative).scripts if script.get("src")]
        assert len(scripts) == 1, relative
        script = scripts[0]
        assert "defer" in script, relative
        assert local_target(source, script["src"]) == AI_CONSULT_SCRIPT.resolve()


def test_ai_consult_launcher_is_localized_and_provider_neutral() -> None:
    script = AI_CONSULT_SCRIPT.read_text(encoding="utf-8")
    required_labels = (
        'launcher: "Ask an AI"',
        'launcher: "AIに相談"',
        "Check whether my environment can run Harako",
        "Discuss whether Harako fits my experimental design",
        "Discuss analysis of SRR/ENA data",
        "Draft a Methods description",
        "Organize likely causes of an error",
        "導入できる環境か確認したい",
        "実験計画への適用を相談したい",
        "SRR/ENAデータの解析を相談したい",
        "論文Methodsの記載を作りたい",
        "エラーの原因を整理したい",
    )
    assert not {label for label in required_labels if label not in script}

    providers = {
        "ChatGPT": "https://chatgpt.com/",
        "Gemini": "https://gemini.google.com/",
        "Claude": "https://claude.ai/",
        "Perplexity": "https://www.perplexity.ai/",
    }
    for name, landing_page in providers.items():
        assert f'{name}: "{landing_page}"' in script
        assert "?" not in landing_page

    required_accessibility = (
        'aria-haspopup": "dialog"',
        '"aria-controls": "ai-consult-dialog"',
        '"aria-labelledby": "ai-consult-title"',
        'role: "status"',
        '"aria-live": "polite"',
        'attributes: { for: "ai-consult-topic" }',
        'attributes: { for: "ai-consult-question" }',
        'event.key === "Escape"',
        'dialog.showModal()',
    )
    assert not {token for token in required_accessibility if token not in script}

    css = (SITE / "assets" / "site.css").read_text(encoding="utf-8")
    assert ".ai-consult-launcher:focus-visible" in css
    assert "min-height: 44px" in css
    assert "@media (max-width: 520px)" in css
    assert ".ai-consult-provider-grid {\n    grid-template-columns: 1fr;" in css


def test_ai_consult_prompt_is_reviewable_private_and_curated() -> None:
    script = AI_CONSULT_SCRIPT.read_text(encoding="utf-8")
    required_privacy_and_safety = (
        "Harako does not send the prompt, question, page text, page URL, or user input to an AI provider.",
        "The provider's own privacy terms apply",
        "FASTQ data, patient information, credentials, unpublished sample identifiers, or private absolute paths",
        "HarakoからAIサービスへ、プロンプト、質問、ページ本文、ページURL、入力内容を送信することはありません。",
        "送信後は各サービスのプライバシー条件が適用されます。",
        "FASTQデータ、患者情報、認証情報、未公開のサンプル識別子、非公開の絶対パス",
        "Prioritize official Harako documentation",
        "Do not infer biological conditions, controls, or biological independence",
        "Do not request FASTQ data or confidential data",
        "Present unknown or uncertain facts as confirmation items",
        "Keep the Harako citation distinct from citations for underlying tools",
        "Harakoの公式ドキュメントを優先",
        "生物学的条件、対照群、生物学的独立性を推測せず",
        "FASTQデータや機密情報の提供を求めないでください",
        "不明または不確かな事実は、仮定せず確認事項",
        "Harakoの引用と、fastp、Salmon、tximport、DESeq2など基盤ツールの引用を区別",
    )
    assert not {phrase for phrase in required_privacy_and_safety if phrase not in script}

    required_curated_inputs = (
        "document.title.trim()",
        "meta[name=\"description\"]",
        "link[rel=\"canonical\"]",
        "topicSelect.value",
        "question.value.trim()",
    )
    assert not {value for value in required_curated_inputs if value not in script}
    assert not any(
        unsafe in script
        for unsafe in (
            "document.body.textContent",
            "document.body.innerText",
            "document.documentElement.innerHTML",
            ".outerHTML",
            "querySelectorAll(",
        )
    )

    lowered = script.lower()
    assert not any(
        forbidden in lowered
        for forbidden in (
            "api.openai.com",
            "generativelanguage.googleapis.com",
            "api.anthropic.com",
            "api.perplexity.ai",
            "api_key",
            "api-key",
            "authorization:",
            "bearer ",
            "fetch(",
            "xmlhttprequest",
            "sendbeacon",
            "urlsearchparams",
        )
    )
    assert not re.search(r"[?&](?:prompt|q|query|text|message)=", script, re.IGNORECASE)
    assert "navigator.clipboard.writeText(text)" in script
    assert 'document.execCommand("copy")' in script
    assert "window.open(\n        PROVIDERS[name]" in script
    assert '"noopener,noreferrer"' in script


def test_localized_homepage_screenshot_galleries_are_accessible_and_complete() -> None:
    expected_by_page = {
        "index.html": [
            "assets/screenshots/gui-samples-en.webp",
            "assets/screenshots/gui-summary-en.webp",
        ],
        "ja/index.html": [
            "../assets/screenshots/gui-samples-ja.webp",
            "../assets/screenshots/gui-summary-ja.webp",
        ],
    }
    for relative, expected_sources in expected_by_page.items():
        source = SITE / relative
        figures = screenshot_figures(relative)
        assert len(figures) == 2
        assert [figure["image"]["src"] for figure in figures] == expected_sources
        for figure in figures:
            image_attrs = figure["image"]
            link_attrs = figure["link"]
            caption = str(figure["caption"]).strip()
            assert image_attrs["alt"].strip()
            assert caption
            assert image_attrs["loading"] == "lazy"
            assert image_attrs["decoding"] == "async"
            assert link_attrs["aria-label"].strip()
            assert link_attrs["href"] == image_attrs["src"]
            assert not urlsplit(image_attrs["src"]).scheme
            target = local_target(source, image_attrs["src"])
            assert target is not None and target.is_file()
            with Image.open(target) as screenshot:
                assert screenshot.format == "WEBP"
                assert screenshot.size == (
                    int(image_attrs["width"]),
                    int(image_attrs["height"]),
                ) == (1440, 900)

    english_sources = {
        figure["image"]["src"] for figure in screenshot_figures("index.html")
    }
    japanese_sources = {
        figure["image"]["src"] for figure in screenshot_figures("ja/index.html")
    }
    assert all("-en.webp" in source for source in english_sources)
    assert all("-ja.webp" in source for source in japanese_sources)


def test_screenshot_assets_are_nonempty_and_within_documented_size_bound() -> None:
    paths = [SITE / relative for relative in sorted(SCREENSHOTS)]
    assert all(path.stat().st_size > 0 for path in paths)
    assert all(path.stat().st_size < 500_000 for path in paths)
    assert sum(path.stat().st_size for path in paths) < 2_000_000


def test_screenshot_sections_follow_workflow_and_precede_detailed_features() -> None:
    expectations = {
        "index.html": ("From reads to results", "See the Harako interface", "Designed to avoid unsupported inference"),
        "ja/index.html": ("前処理からレポートまでを一貫して実行", "Harakoの画面を見る", "解析条件に応じた統計処理"),
    }
    for relative, headings in expectations.items():
        text = (SITE / relative).read_text(encoding="utf-8")
        positions = [text.index(heading) for heading in headings]
        assert positions == sorted(positions)


def test_homepages_use_prescribed_search_snippets_and_visible_headings() -> None:
    expected = {
        "index.html": (
            "Harako-RNAseq | FASTQ-to-DESeq2 Bulk RNA-seq Workflow",
            "Harako-RNAseq is a Docker-based bulk RNA-seq GUI workflow from FASTQ preprocessing through Salmon, tximport, DESeq2 or QC-only analysis, and self-contained HTML reporting.",
        ),
        "ja/index.html": (
            "Harako-RNAseq | FASTQからDESeq2までのバルクRNA-seq解析ワークフロー",
            "Harako-RNAseqは、FASTQの前処理からSalmon、tximport、DESeq2またはQC-only解析、HTMLレポート作成までを実行するDockerベースのバルクRNA-seq解析GUIです。",
        ),
    }
    for relative, (title, description) in expected.items():
        page = parse_page(relative)
        text = (SITE / relative).read_text(encoding="utf-8")
        assert page.title == title
        assert page.named_meta("description") == description
        properties = {item.get("property"): item.get("content", "") for item in page.meta}
        assert properties["og:title"] == title
        assert properties["og:description"] == description
        assert "<h1>Harako-RNAseq</h1>" in text


def test_japanese_pages_use_japanese_language_and_unique_metadata() -> None:
    titles: set[str] = set()
    descriptions: set[str] = set()
    for relative, (title, description) in JAPANESE_METADATA.items():
        page = parse_page(relative)
        assert page.lang == "ja"
        assert page.title == title
        assert page.named_meta("description") == description
        properties = {item.get("property"): item.get("content", "") for item in page.meta}
        assert properties["og:title"] == title
        assert properties["og:description"] == description
        titles.add(page.title)
        descriptions.add(page.named_meta("description"))
    assert len(titles) == len(JAPANESE_METADATA)
    assert len(descriptions) == len(JAPANESE_METADATA)


def test_site_uses_clear_scientific_language() -> None:
    html = "\n".join(path.read_text(encoding="utf-8") for path in SITE.rglob("*.html"))
    old_phrases = {
        "alignment-free",
        "The Docker RNA-seq analysis path",
        "Designed for honest local analysis",
        "fabricated p-values",
        "reviewable results",
        "remains the authority",
        "For real studies",
        "immutable release tag",
        "exact-version",
        "アラインメント不要",
        "差次的発現解析",
        "外部Web資源",
        "解析結果を過大に見せない設計",
        "構造上有効な設計",
        "p値や調整p値を作りません",
        "記述的TPM",
        "参照配列と注釈の由来",
    }
    assert not {phrase for phrase in old_phrases if phrase in html}

    required_phrases = {
        "The Docker-based workflow",
        "Designed to avoid unsupported inference",
        "Transcript-level quantification using the selected Salmon index",
        "gene-level count matrix used as input to DESeq2",
        "does not use TPM as input to DESeq2",
        "minimum threshold enforced by the software",
        "without p-values or adjusted p-values",
        "gene-level TPM",
        "遺伝子発現変動解析",
        "発現変動解析",
        "解析条件に応じた統計処理",
        "最小サンプル数要件",
        "選択したSalmonインデックスを用いた転写産物レベルの定量",
        "DESeq2はカウント値を使用し、TPMは使用しません",
        "ソフトウェアが適用する最小サンプル数要件",
        "p値および調整p値を算出・出力しません",
        "発現量指標としてのTPM",
        "参照データの来歴情報",
    }
    assert not {phrase for phrase in required_phrases if phrase not in html}
    assert (
        "minimum analysis requirements" in html
        or "minimum sample-count requirements" in html
    )


def test_content_page_footers_show_development_start_without_personal_name() -> None:
    for relative in CONTENT_HTML:
        page = parse_page(relative)
        text = (SITE / relative).read_text(encoding="utf-8")
        assert "Harako-RNAseq v0.3.0-beta.1" in page.footer_text
        if relative.startswith("ja/"):
            assert "2026年1月より開発" in page.footer_text
            assert "In development since January 2026" not in page.footer_text
        else:
            assert "In development since January 2026" in page.footer_text
            assert "2026年1月より開発" not in page.footer_text
        assert "Created by Daisuke Ohshima" not in page.footer_text
        assert "Daisuke Ohshima" not in page.footer_text
        assert "Public since January 2026" not in text
        assert "Released in January 2026" not in text


def test_english_and_japanese_homepages_keep_equivalent_scientific_claims() -> None:
    homepages = {
        "index.html": (
            "FASTQ → fastp → Salmon → tximport → DESeq2 or QC-only → HTML report",
            "continue in QC-only mode without p-values or adjusted p-values",
            "Transcript-level quantification using the selected Salmon index",
            "at least two conditions and at least two valid samples in every condition",
            "This is the minimum threshold enforced by the software, not a power calculation",
            "without p-values or adjusted p-values",
            "biological independence or experimental-design validity",
            "DESeq2 uses counts, never TPM",
        ),
        "ja/index.html": (
            "FASTQ → fastp → Salmon → tximport → DESeq2／QC-only → HTMLレポート",
            "最小サンプル数要件を満たさない場合はQC-onlyモード",
            "選択したSalmonインデックスを用いた転写産物レベルの定量",
            "2条件以上、かつ各条件に2つ以上の有効なサンプル",
            "ソフトウェアが適用する最小サンプル数要件",
            "統計的検出力の計算、生物学的独立性の証明、実験計画の妥当性確認ではありません",
            "p値および調整p値を算出・出力しません",
            "DESeq2はカウント値を使用し、TPMは使用しません",
        ),
    }
    for relative, claims in homepages.items():
        text = (SITE / relative).read_text(encoding="utf-8")
        assert not {claim for claim in claims if claim not in text}


def test_readmes_link_the_project_website_near_the_top() -> None:
    for name in ("README.md", "README.ja.md"):
        opening = "\n".join((ROOT / name).read_text(encoding="utf-8").splitlines()[:15])
        assert PAGES_PREFIX in opening


def test_google_search_console_verification_is_deployed_from_site_only() -> None:
    filename = "googlecd2ee16aca2b2885.html"
    verification = SITE / filename
    assert verification.read_text(encoding="utf-8").strip() == (
        "google-site-verification: googlecd2ee16aca2b2885.html"
    )
    assert not (ROOT / filename).exists()
    assert not (ROOT / "docs" / filename).exists()


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
        assert canonical[0]["href"] == public_url(relative)
        properties = {item.get("property"): item.get("content", "") for item in page.meta}
        for field in ("og:title", "og:description", "og:type", "og:url", "og:image"):
            assert properties.get(field), f"{relative}: {field}"
        assert properties["og:url"] == canonical[0]["href"]
        assert properties["og:image"] == PAGES_PREFIX + "assets/harako-logo.png"


def test_all_language_pairs_have_reciprocal_hreflang_links() -> None:
    for english_path, japanese_path in PAGE_PAIRS.items():
        english_relative = f"{english_path}index.html"
        japanese_relative = f"{japanese_path}index.html"
        english_url = public_url(english_relative)
        japanese_url = public_url(japanese_relative)
        expected = {
            "en": english_url,
            "ja": japanese_url,
            "x-default": english_url,
        }
        for relative in (english_relative, japanese_relative):
            page = parse_page(relative)
            actual = {
                link["hreflang"]: link["href"]
                for link in page.linked("alternate")
                if "hreflang" in link
            }
            assert actual == expected, relative


def test_header_navigation_preserves_language_and_page_equivalence() -> None:
    japanese_expected = {
        "ja/index.html": {
            "Harako-RNAseq": ("./", "page", ""),
            "導入方法": ("installation/", "", ""),
            "解析手法": ("methods/", "", ""),
            "出力": ("outputs/", "", ""),
            "English": ("../", "", "en"),
            "GitHub": (GITHUB_URL, "", ""),
        },
        "ja/installation/index.html": {
            "Harako-RNAseq": ("../", "", ""),
            "導入方法": ("./", "page", ""),
            "解析手法": ("../methods/", "", ""),
            "出力": ("../outputs/", "", ""),
            "English": ("../../installation/", "", "en"),
            "GitHub": (GITHUB_URL, "", ""),
        },
        "ja/methods/index.html": {
            "Harako-RNAseq": ("../", "", ""),
            "導入方法": ("../installation/", "", ""),
            "解析手法": ("./", "page", ""),
            "出力": ("../outputs/", "", ""),
            "English": ("../../methods/", "", "en"),
            "GitHub": (GITHUB_URL, "", ""),
        },
        "ja/outputs/index.html": {
            "Harako-RNAseq": ("../", "", ""),
            "導入方法": ("../installation/", "", ""),
            "解析手法": ("../methods/", "", ""),
            "出力": ("./", "page", ""),
            "English": ("../../outputs/", "", "en"),
            "GitHub": (GITHUB_URL, "", ""),
        },
    }
    for relative, expected in japanese_expected.items():
        page = parse_page(relative)
        actual = {
            link["text"].strip(): (
                link["href"],
                link.get("aria-current", ""),
                link.get("lang", ""),
            )
            for link in page.header_links
        }
        assert actual == expected, relative
        for label, link in ((link["text"].strip(), link) for link in page.header_links):
            if link["href"] == GITHUB_URL:
                continue
            target = local_target(SITE / relative, link["href"])
            assert target is not None and target.is_file(), f"{relative}: {link['href']}"
            if label != "English":
                target.relative_to(SITE / "ja")

    english_switches = {
        "index.html": "ja/",
        "installation/index.html": "../ja/installation/",
        "methods/index.html": "../ja/methods/",
        "outputs/index.html": "../ja/outputs/",
    }
    for relative, expected_href in english_switches.items():
        page = parse_page(relative)
        switches = [
            link
            for link in page.header_links
            if link["text"].strip() == "日本語"
        ]
        assert len(switches) == 1
        assert switches[0]["href"] == expected_href
        assert switches[0].get("lang") == "ja"
        for link in page.header_links:
            if link is switches[0] or link["href"] == GITHUB_URL:
                continue
            target = local_target(SITE / relative, link["href"])
            assert target is not None and not target.is_relative_to(SITE / "ja")


def test_all_header_links_resolve_or_are_approved_external_links() -> None:
    for relative in EXPECTED_HTML:
        for link in parse_page(relative).header_links:
            href = link["href"]
            if href == GITHUB_URL:
                continue
            target = local_target(SITE / relative, href)
            assert target is not None and target.is_file(), f"{relative} -> {href}"


def test_japanese_internal_links_stay_in_japanese_except_language_switches() -> None:
    homepage_hrefs = {
        link.get("href", "")
        for link in parse_page("ja/index.html").links
        if link["tag"] == "a"
    }
    assert homepage_hrefs.isdisjoint(
        {"../installation/", "../methods/", "../outputs/"}
    )

    for relative in JAPANESE_METADATA:
        source = SITE / relative
        for link in parse_page(relative).links:
            if link["tag"] != "a":
                continue
            target = local_target(source, link.get("href", ""))
            if target is None or not target.is_relative_to(SITE):
                continue
            if target.is_relative_to(SITE / "ja"):
                continue
            if target.suffix.lower() != ".html":
                continue
            assert link.get("lang") == "en", f"{relative} -> {link['href']}"
            assert "English" in link["text"], f"{relative} -> {link['href']}"


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
    url_list = [element.text for element in tree.findall("sm:url/sm:loc", namespace)]
    assert len(url_list) == len(set(url_list))
    assert set(url_list) == {PAGES_PREFIX + path for path in SITEMAP_PATHS}
    assert PAGES_PREFIX + "404.html" not in url_list
    assert all(site_path_for_url(url).is_file() for url in url_list)

    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    assert re.search(r"(?im)^User-agent:\s*\*$", robots)
    assert re.search(r"(?im)^Allow:\s*/$", robots)
    assert f"Sitemap: {PAGES_PREFIX}sitemap.xml" in robots


def test_pages_are_indexable_and_have_no_external_runtime_dependencies() -> None:
    for relative in EXPECTED_HTML:
        source = SITE / relative
        text = (SITE / relative).read_text(encoding="utf-8")
        page = parse_page(relative)
        assert "noindex" not in text.lower()
        for script in (item for item in page.scripts if item.get("src")):
            target = local_target(source, script["src"])
            assert target is not None and target.is_file()
            assert target.is_relative_to(SITE)
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
        "softwareVersion": "0.3.0-beta.1",
        "operatingSystem": "Windows and Linux through Docker",
        "applicationSubCategory": "Bioinformatics",
        "codeRepository": "https://github.com/do-shima/harako-rnaseq",
        "downloadUrl": "https://github.com/do-shima/harako-rnaseq/releases/tag/v0.3.0-beta.1",
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


def test_v03_agent_feature_claims_are_concise_and_equivalent() -> None:
    english = (SITE / "index.html").read_text(encoding="utf-8")
    japanese = (SITE / "ja" / "index.html").read_text(encoding="utf-8")
    assert (
        "v0.3 adds a controlled machine-readable interface for local automation, "
        "with explicit condition mapping and confirmation of the exact approval hash "
        "before execution."
    ) in english
    assert "Harako validates and executes the supported scientific workflow" in english
    assert "does not infer conditions or embed an OpenAI SDK" in english
    assert (
        "v0.3では、条件割り当てを明示し、実行前に承認ハッシュの完全一致を確認する、"
        "ローカル自動化向けの機械可読インターフェースを追加しました。"
    ) in japanese
    assert "対応している解析処理の検証と実行はHarakoが担い" in japanese
    assert "条件を自動推測せず、OpenAI SDK" in japanese


def test_homepages_explain_the_harako_name_without_renaming_the_product() -> None:
    expansion = "Human-Auditable, Reproducible Analysis Kit and Orchestrator"
    english = (SITE / "index.html").read_text(encoding="utf-8")
    japanese = (SITE / "ja" / "index.html").read_text(encoding="utf-8")

    for homepage in (english, japanese):
        assert homepage.count(expansion) == 1
        assert "Harako-RNAseq" in homepage
        assert "https://github.com/yyoshiaki/ikra" in homepage
        assert "HARAKO originally stood for" not in homepage
        assert "HARAKOは本来" not in homepage
        assert "guaranteed reproducibility" not in homepage.lower()

    assert '<abbr title="' + expansion + '">HARAKO</abbr>' in english
    assert "harako</em>—salmon roe" in english
    assert "does not automatically certify scientific validity" in english
    assert "はらこ（鮭の卵）" in japanese
    assert "後付けの頭字語（backronym）としても位置づけています" in japanese
    assert "科学的妥当性を自動的に認定するものではありません" in japanese


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
