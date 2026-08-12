from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGLISH_PUBLIC = (
    ROOT / "README.md",
    ROOT / "SUPPORT.md",
    ROOT / "docs" / "limitations.md",
    ROOT / "docs" / "usage.md",
    ROOT / "docs" / "installation.md",
    ROOT / "docs" / "scientific-methods.md",
    ROOT / "docs" / "agent-workflow.md",
    ROOT / "docs" / "agent-assisted-analysis.md",
    ROOT / "docs" / "advanced-usage.md",
    ROOT / "docs" / "troubleshooting.md",
    *(ROOT / "site").glob("*.html"),
    *(ROOT / "site" / "methods").glob("*.html"),
    *(ROOT / "site" / "outputs").glob("*.html"),
)
JAPANESE_PUBLIC = (
    ROOT / "README.ja.md",
    *(ROOT / "site" / "ja").glob("*.html"),
    *(ROOT / "site" / "ja" / "installation").glob("*.html"),
    *(ROOT / "site" / "ja" / "methods").glob("*.html"),
    *(ROOT / "site" / "ja" / "outputs").glob("*.html"),
)


def _public_prose(paths: tuple[Path, ...]) -> str:
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"<(?:code|pre)\b[^>]*>.*?</(?:code|pre)>", "", text, flags=re.DOTALL)
    return text


def test_active_public_copy_uses_approved_terminology() -> None:
    english = _public_prose(ENGLISH_PUBLIC)
    japanese = _public_prose(JAPANESE_PUBLIC)

    for phrase in (
        "differential-expression analysis",
        "minimum replicate gate",
        "scientific execution authority",
        "preferred ordinary-user path",
        "fabricated inferential statistics",
    ):
        assert phrase not in english

    for phrase in (
        "Validate 出力",
        "予行",
        "推測統計を作",
        "記述的TPM",
        "科学計算の実行主体",
        "最低反復条件",
        "最小反復条件",
    ):
        assert phrase not in japanese

    assert "differential expression analysis" in english
    assert "minimum sample-count requirements" in english
    assert "gene-level TPM as an abundance measure" in english
    assert "遺伝子発現変動解析" in japanese
    assert "最小サンプル数要件" in japanese
    assert "承認ハッシュ" in japanese


def test_visible_ui_actions_and_labels_are_language_consistent() -> None:
    locale_dir = ROOT / "app" / "ui" / "locales"
    en = json.loads((locale_dir / "en.json").read_text(encoding="utf-8"))
    ja = json.loads((locale_dir / "ja.json").read_text(encoding="utf-8"))

    assert [en[f"action.{key}.label"] for key in ("save", "validate", "trial", "run")] == [
        "1. Save", "2. Validate", "3. Dry run", "4. Run"
    ]
    assert [ja[f"action.{key}.label"] for key in ("save", "validate", "trial", "run")] == [
        "1. 保存", "2. 検証", "3. ドライラン", "4. 実行"
    ]
    assert ja["label.validate_output"] == "検証結果"
    assert ja["label.dryrun_output"] == "ドライランの結果"
    assert ja["label.threads"] == "スレッド数"
    assert "生物種=" in ja["label.run_config_summary"]
    assert "参照プリセット=" in ja["label.run_config_summary"]
    assert en["label.validate_output"] == "Validation results"
    assert en["label.dryrun_output"] == "Dry-run results"
    assert en["label.threads"] == "Threads"
    assert "予行" not in "\n".join(ja.values())
