import argparse
import re
from html.parser import HTMLParser
from pathlib import Path


_HTTP_RE = re.compile(r"^https?://", flags=re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?(https?://[^'\"\)\s]+)", flags=re.IGNORECASE)
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", flags=re.DOTALL)
_LOAD_ATTRS = {"src", "href", "poster", "data", "action"}


def _is_external_url(value):
    return bool(value and _HTTP_RE.match(value.strip()))


def _extract_css_urls(css_text):
    if not css_text:
        return []
    cleaned = _CSS_COMMENT_RE.sub("", css_text)
    return [match.group(1).strip() for match in _CSS_URL_RE.finditer(cleaned)]


class ExternalRefParser(HTMLParser):
    def __init__(self, strict_links=False):
        super().__init__(convert_charrefs=True)
        self.strict_links = strict_links
        self.in_style = False
        self.refs = []

    def _add_ref(self, tag, attr, url):
        self.refs.append((tag, attr, url))

    def handle_starttag(self, tag, attrs):
        tag_name = (tag or "").lower()
        if tag_name == "style":
            self.in_style = True

        for attr, value in attrs:
            attr_name = (attr or "").lower()
            if attr_name == "style":
                for url in _extract_css_urls(value or ""):
                    self._add_ref(tag_name, "style", url)
                continue
            if attr_name not in _LOAD_ATTRS:
                continue
            if attr_name == "href" and tag_name == "a" and not self.strict_links:
                continue
            if _is_external_url(value):
                self._add_ref(tag_name, attr_name, value.strip())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if (tag or "").lower() == "style":
            self.in_style = False

    def handle_data(self, data):
        if not self.in_style:
            return
        for url in _extract_css_urls(data):
            self._add_ref("style", "text", url)


def _parse_args():
    parser = argparse.ArgumentParser(description="Check whether an HTML report is self-contained.")
    parser.add_argument("--report", required=True, help="Path to report.html")
    parser.add_argument("--print-externals", action="store_true", help="Print matched external load refs.")
    parser.add_argument("--warn-only", action="store_true", help="Warn on external refs but exit 0.")
    parser.add_argument(
        "--strict-links",
        action="store_true",
        help="Treat <a href='http(s)://...'> as external (default: ignored).",
    )
    return parser.parse_args()


def _dedupe_refs(refs):
    seen = set()
    ordered = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        ordered.append(ref)
    return ordered


def main() -> int:
    args = _parse_args()
    path = Path(args.report)
    if not path.exists():
        print(f"report not found: {path}")
        return 2

    text = path.read_text(encoding="utf-8", errors="ignore")
    parser = ExternalRefParser(strict_links=args.strict_links)
    parser.feed(text)
    refs = _dedupe_refs(parser.refs)

    if refs:
        if args.warn_only:
            print("WARN: external references detected")
        else:
            print("FAIL: external references detected")
        if args.print_externals or args.warn_only:
            for tag, attr, url in refs:
                print(f"tag={tag} attr={attr} url={url}")
        else:
            print(f"- {len(refs)} external load reference(s)")
        return 0 if args.warn_only else 49

    if "data:image/" in text:
        print("INFO: data:image/ found")
    print("PASS: report appears self-contained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
