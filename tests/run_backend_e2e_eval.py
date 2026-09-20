#!/usr/bin/env python3
"""Run five real end-to-end topics against the local backend and save evidence."""

import concurrent.futures
import http.cookiejar
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("WORKBENCH_URL", "http://127.0.0.1:4173")
TOPICS = [
    "CRISPR分子诊断的主要技术路线与关键限制",
    "mRNA药物递送系统的主要技术路线与关键限制",
    "肠道微生物与衰老研究的主要证据和局限",
    "单细胞测序在肿瘤微环境研究中的应用",
    "合成生物学发酵的主要技术路线与产业化限制",
]


def json_request(opener, url, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"} if data else {}
    with opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=30) as response:
        return json.loads(response.read().decode())


def run_one(index, topic):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
    created = json_request(opener, BASE + "/api/research-jobs", {
        "topic": topic, "idempotency_key": f"e2e_20260920_{index:02d}_{int(time.time())}"
    })
    job_id = created["id"]
    deadline = time.time() + 360
    while time.time() < deadline:
        job = json_request(opener, f"{BASE}/api/research-jobs/{job_id}")
        if job["status"] in {"completed", "partial", "failed", "cancelled"}:
            break
        time.sleep(1.5)
    else:
        raise RuntimeError(f"{topic}: timeout")

    valid_ids = {source["source_id"] for source in job["sources"]}
    used_ids = set(re.findall(r"\[(S\d+)\]", job.get("report") or ""))
    checks = {
        "ended": job["status"] in {"completed", "partial", "failed", "cancelled"},
        "completed": job["status"] == "completed",
        "source_count_valid": 0 < len(job["sources"]) < 20,
        "has_pubmed": any(x["provider"] == "PubMed" for x in job["sources"]),
        "has_europe_pmc": any(x["provider"] == "Europe PMC" for x in job["sources"]),
        "citation_ids_valid": bool(used_ids) and used_ids <= valid_ids,
        "patent_gap_disclosed": "EPO" in (job.get("report") or "") and "等待管理员审批" in job["patent_status"],
        "under_task_budget": job["usage"]["estimated_cost_cny"] < 1.0,
    }
    return {"topic": topic, "job": job, "checks": checks, "passed": all(checks.values())}


def main():
    started = datetime.now(timezone.utc)
    topics = TOPICS
    selected = os.getenv("WORKBENCH_TOPIC_INDEX", "").strip()
    if selected:
        position = int(selected)
        topics = [TOPICS[position - 1]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda pair: run_one(*pair), enumerate(topics, 1)))
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "artifacts" / "backend-e2e" / run_id
    output.mkdir(parents=True, exist_ok=True)
    for index, result in enumerate(results, 1):
        (output / f"T{index:02d}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "run_id": run_id, "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
        "topic_count": len(results), "passed": sum(x["passed"] for x in results),
        "completed": sum(x["job"]["status"] == "completed" for x in results),
        "total_estimated_cost_cny": round(sum(x["job"]["usage"]["estimated_cost_cny"] for x in results), 4),
        "results": [{"topic": x["topic"], "status": x["job"]["status"], "source_count": len(x["job"]["sources"]), "providers": sorted({s["provider"] for s in x["job"]["sources"]}), "estimated_cost_cny": x["job"]["usage"]["estimated_cost_cny"], "passed": x["passed"], "checks": x["checks"]} for x in results],
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), **summary}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary["passed"] == len(results) else 1)


if __name__ == "__main__":
    main()
