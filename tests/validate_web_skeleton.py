#!/usr/bin/env python3
"""Static acceptance checks for the dependency-free website skeleton."""

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids = set()
        self.links = []
        self.scripts = []
        self.lang = None
        self.title_seen = False
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "html": self.lang = values.get("lang")
        if tag == "title": self._in_title = True
        if values.get("id"): self.ids.add(values["id"])
        if tag == "a" and values.get("href"): self.links.append(values["href"])
        if tag == "script" and values.get("src"): self.scripts.append(values["src"])

    def handle_endtag(self, tag):
        if tag == "title": self._in_title = False

    def handle_data(self, data):
        if self._in_title and data.strip(): self.title_seen = True


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def parse(name):
    parser = PageParser()
    parser.feed((WEB / name).read_text(encoding="utf-8"))
    return parser


def main():
    for name in ("index.html", "creator.html", "styles.css", "app.js"):
        require((WEB / name).is_file(), f"missing {name}")

    index = parse("index.html")
    creator = parse("creator.html")
    require(index.lang == "zh-CN" and creator.lang == "zh-CN", "pages must declare zh-CN")
    require(index.title_seen and creator.title_seen, "pages must have titles")
    require({"topic", "research-form", "workspace"} <= index.ids, "research form or workspace is incomplete")
    require("./creator.html" in index.links, "creator entry is missing")
    require("./app.js" in index.scripts, "client behavior is missing")

    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    require("未连接检索" in html, "prototype must disclose that real retrieval is disconnected")
    require("maxlength=\"120\"" in html, "topic length must be constrained")
    require("preventDefault" in js and "submit.disabled = true" in js, "duplicate submission guard is missing")
    require("innerHTML" not in js, "prototype must avoid unsafe HTML injection")
    print("web skeleton validation: PASS")


if __name__ == "__main__":
    main()
