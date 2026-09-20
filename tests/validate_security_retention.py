#!/usr/bin/env python3
"""Validate domain, retention, backup and creator-auth safety invariants."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "security-retention.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    domain = config["domain"]
    auth = config["creator_auth"]
    session = auth["session"]
    anonymous = config["anonymous_task_access"]
    backup = config["backup"]
    retention = config["retention"]
    secrets = config["secrets"]

    require(domain["require_https"], "HTTPS must be required")
    require(domain["redirect_http_to_https"], "HTTP must redirect to HTTPS")
    require(domain["cors_policy"] == "deny_by_default", "CORS must default-deny")
    require(domain["api_origin"] == "same_origin", "API must be same-origin for the demo")
    require(not auth["public_signup"], "Creator account must not allow public signup")
    require(auth["password_hash_algorithm"] == "argon2id", "Use Argon2id for password hashes")
    require(auth["totp_required_before_public_trial"], "TOTP is required before public trial")
    require(session["cookie_http_only"] and session["cookie_secure"], "Admin cookie must be HttpOnly and Secure")
    require(session["cookie_same_site"] == "Strict", "Admin cookie must use SameSite=Strict")
    require(session["idle_timeout_minutes"] <= 30, "Admin idle timeout is too long")
    require(session["absolute_timeout_hours"] <= 8, "Admin absolute session is too long")
    require(auth["login_rate_limit"]["max_failures"] <= 5, "Login failure limit is too permissive")
    require(anonymous["opaque_token_bits"] >= 128, "Task access token must have at least 128 random bits")
    require(not anonymous["task_id_alone_grants_access"], "Task ID alone must not grant access")
    require(anonymous["cookie_http_only"] and anonymous["cookie_secure"], "Task cookie must be HttpOnly and Secure")
    require(retention["task_and_report_days"] <= 7, "Raw task retention exceeds the demo window")
    require(not retention["aggregate_metrics_include_raw_user_input"], "Aggregate metrics must exclude raw input")
    require(backup["never_commit_to_git"], "Backups must never enter Git")
    require(backup["deletion_must_cover_backups"], "Deletion must include retained backups")
    require(backup["manifest_hash"] == "sha256", "Backup manifest must use SHA-256")

    env_name = re.compile(r"^[A-Z][A-Z0-9_]+$")
    variables = secrets["required_environment_variables"]
    require(len(variables) == len(set(variables)), "Environment variable names must be unique")
    require(all(env_name.fullmatch(name) for name in variables), "Only environment variable names may appear in config")
    require("git_repository" in secrets["forbidden_locations"], "Git must be a forbidden secret location")
    print("security-retention validation: PASS")


if __name__ == "__main__":
    main()
