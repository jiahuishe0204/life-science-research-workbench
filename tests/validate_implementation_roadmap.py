#!/usr/bin/env python3
"""Validate that remaining work has explicit order, dependencies and evidence gates."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = json.loads((ROOT / "config/implementation-roadmap.json").read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


policy = ROADMAP["execution_policy"]
items = ROADMAP["work_items"]
ids = [item["id"] for item in items]
allowed = set(policy["allowed_statuses"])

require(len(ids) == len(set(ids)), "Roadmap work item IDs must be unique")
require([item["priority"] for item in items] == sorted(item["priority"] for item in items), "Priorities must be ordered")
require(policy["completion_status"] == "runtime_verified", "Completion must require runtime verification")
require(policy["cost_stop_cny_per_research_job"] <= 1.0, "Research-job hard stop must not exceed 1 CNY")
require("chat" in policy["secret_policy"] and "git" in policy["secret_policy"], "Secret policy must forbid chat and Git")

for item in items:
    require(item["status"] in allowed, f"Unknown status for {item['id']}")
    require(item["acceptance"], f"Acceptance criteria missing for {item['id']}")
    require(all(dep in ids for dep in item["depends_on"]), f"Unknown dependency for {item['id']}")
    if item["status"] == "blocked_external":
        require(item.get("blocker"), f"External blocker must be recorded for {item['id']}")

print("implementation roadmap validation: PASS")
