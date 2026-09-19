#!/usr/bin/env python3
"""Validate DeepSeek budget caps against the recorded price snapshot."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/deepseek-budget.json"
FINAL_RUN = ROOT / "artifacts/prompt-eval/20260919T154210/summary.json"


def estimate(input_tokens, output_tokens, prices):
    return input_tokens / 1_000_000 * prices["cache_miss_input"] + output_tokens / 1_000_000 * prices["output"]


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    peak = config["price_snapshot_per_million_tokens"]["peak"]
    off_peak = config["price_snapshot_per_million_tokens"]["off_peak"]
    per_task = config["per_task"]
    per_day = config["per_day"]
    task_worst = estimate(per_task["max_input_tokens"], per_task["max_output_tokens"], peak)
    day_worst = estimate(per_day["max_input_tokens"], per_day["max_output_tokens"], peak)
    assert task_worst <= per_task["hard_stop_cny"]
    assert day_worst <= per_day["hard_stop_cny"]
    run = json.loads(FINAL_RUN.read_text(encoding="utf-8"))["totals"]
    final_range = {
        "off_peak_cny": round(estimate(run["prompt_tokens"], run["completion_tokens"], off_peak), 6),
        "peak_cny": round(estimate(run["prompt_tokens"], run["completion_tokens"], peak), 6),
    }
    print(json.dumps({"budget_policy": "OK", "task_worst_cny": task_worst, "day_worst_cny": day_worst, "final_eval_estimate": final_range}, ensure_ascii=False))


if __name__ == "__main__":
    main()
