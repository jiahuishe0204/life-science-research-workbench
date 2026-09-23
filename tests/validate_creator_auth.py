#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
backend=(ROOT/"cloud-functions/api/creator/[[default]].js").read_text(encoding="utf-8")
frontend=(ROOT/"web/creator.js").read_text(encoding="utf-8")
page=(ROOT/"web/creator.html").read_text(encoding="utf-8")
package=json.loads((ROOT/"package.json").read_text(encoding="utf-8"))
def require(value,message):
    if not value: raise AssertionError(message)
require(package["dependencies"].get("@noble/hashes")=="2.4.0","Argon2 dependency must be pinned")
require("argon2id" in backend and "m < 19456" in backend and "t < 2" in backend,"Argon2id minimums are missing")
require("verifyTotp" in backend and 'createHmac("sha1"' in backend,"TOTP verification is missing")
require("HttpOnly; Secure; SameSite=Strict" in backend,"Cookie flags are incomplete")
require("IDLE_MS = 30" in backend and "ABSOLUTE_MS = 8" in backend,"Session timeouts are incomplete")
require("MAX_FAILURES = 5" in backend and "LOCKOUT_MS = 15" in backend,"Login lockout is incomplete")
require("x-csrf-token" in backend and "csrf_hash" in backend,"CSRF protection is missing")
require("secretBytes" in backend and "typeof secret.value" in backend and "typeof secret.getValue" in backend,"EdgeOne secret wrappers are not normalized")
require("process.env.ADMIN_SESSION_SECRET || context.env?.ADMIN_SESSION_SECRET" in backend,"Node environment string must take precedence")
require("activeSession(context.request, blob, cfg.sessionSecret)" in backend,"Session verification must receive only the signing secret")
require("login_success" in backend and "login_failure" in backend and '"logout"' in backend,"Audit events are incomplete")
require("localStorage" not in frontend and "sessionStorage" not in frontend,"Web Storage must not hold sessions")
require('autocomplete="current-password"' in page and 'autocomplete="one-time-code"' in page,"Login autocomplete semantics are missing")
print("creator auth validation: PASS")
