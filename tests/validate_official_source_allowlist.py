#!/usr/bin/env python3
"""Validate and exercise the official-source URL allowlist."""

import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/official-source-allowlist.json"
CASES = ROOT / "tests/fixtures/official-source-url-cases.json"


def classify(url, config):
    parsed = urlparse(url)
    if config.get("require_https") and parsed.scheme != "https":
        return None
    if parsed.username or parsed.password or not parsed.hostname:
        return None
    host = parsed.hostname.rstrip(".").lower()
    path = parsed.path or "/"
    for source in config["sources"]:
        matched = any(
            host == domain or (source.get("allow_subdomains") and host.endswith("." + domain))
            for domain in source["domains"]
        )
        if not matched:
            continue
        prefixes = source.get("allowed_path_prefixes")
        if prefixes and not any(path.startswith(prefix) for prefix in prefixes):
            continue
        return source["id"]
    return None


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    ids = [source["id"] for source in config["sources"]]
    assert len(ids) == len(set(ids)), "source ids must be unique"
    for source in config["sources"]:
        assert source["domains"] and source["allowed_uses"] and source["limitations"]
    for case in cases:
        actual = classify(case["url"], config)
        assert bool(actual) == case["allowed"], (case["url"], actual)
        if case.get("source_id"):
            assert actual == case["source_id"], (case["url"], actual)
    print(f"official source allowlist: OK ({len(config['sources'])} sources, {len(cases)} URL cases)")


if __name__ == "__main__":
    main()
