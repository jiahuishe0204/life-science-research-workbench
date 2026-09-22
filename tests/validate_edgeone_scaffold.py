#!/usr/bin/env python3
"""Validate the deployable EdgeOne Makers scaffold without network access."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


edgeone = json.loads((ROOT / "edgeone.json").read_text(encoding="utf-8"))
package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
health = (ROOT / "cloud-functions/api/health.js").read_text(encoding="utf-8")

require(edgeone["outputDirectory"] == "./web", "Static output must remain web/")
require(edgeone["cloudFunctions"]["nodejs"]["maxDuration"] == 120, "Cloud Function duration must be 120s")
require(edgeone["cloudFunctions"]["overseasRegions"] == ["ap-singapore"], "Use one overseas region")
require(package["dependencies"]["@edgeone/pages-blob"] == "0.0.16", "Blob SDK must be pinned")
require("consistency: \"strong\"" in health, "Health storage check must use strong consistency")
require("configured" in health and "DEEPSEEK_API_KEY" in health, "Health endpoint must report names only")
require("context.env?.DEEPSEEK_API_KEY" in health, "Direct Makers context access is missing")
require("process.env.DEEPSEEK_API_KEY" in health, "Direct Node runtime fallback is missing")

print("edgeone scaffold validation: PASS")
