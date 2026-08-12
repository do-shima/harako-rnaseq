from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_launcher_guides_users_through_the_main_ui_actions() -> None:
    source = (ROOT / "app" / "ui" / "launcher_ui.py").read_text(encoding="utf-8")
    assert "Save → Validate → Dry run → Run" in source
    assert "validate-out" not in source
    assert "run-out" not in source
