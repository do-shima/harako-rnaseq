import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_report_selfcontained.py"


def _run_check(html_text, extra_args=None):
    extra_args = extra_args or []
    with tempfile.TemporaryDirectory() as tmpdir:
        report = Path(tmpdir) / "report.html"
        report.write_text(html_text, encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT), "--report", str(report)] + list(extra_args)
        return subprocess.run(cmd, capture_output=True, text=True)


def test_license_text_url_is_not_external_load():
    html = """
    <html><body>
      <p>Bootstrap v3.3.5 (http://getbootstrap.com)</p>
      <p>Licensed under https://github.com/twbs/bootstrap/blob/master/LICENSE</p>
      <!-- comment with https://cdn.example/comment.js -->
    </body></html>
    """
    result = _run_check(html)
    assert result.returncode == 0, result.stdout + result.stderr


def test_script_src_external_fails():
    html = '<html><head><script src="https://cdn.example/x.js"></script></head><body></body></html>'
    result = _run_check(html)
    assert result.returncode == 49, result.stdout + result.stderr


def test_anchor_link_only_is_non_strict_by_default_and_strict_when_requested():
    html = '<html><body><a href="https://example.com">external link</a></body></html>'
    non_strict = _run_check(html)
    assert non_strict.returncode == 0, non_strict.stdout + non_strict.stderr

    strict = _run_check(html, ["--strict-links"])
    assert strict.returncode == 49, strict.stdout + strict.stderr


def main():
    test_license_text_url_is_not_external_load()
    test_script_src_external_fails()
    test_anchor_link_only_is_non_strict_by_default_and_strict_when_requested()


if __name__ == "__main__":
    main()
