import { createHmac, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { getStore } from "@edgeone/pages-blob";
import { argon2id } from "@noble/hashes/argon2.js";
import { utf8ToBytes } from "@noble/hashes/utils.js";

const STORE_NAME = "life-science-workbench";
const COOKIE = "lsrw_creator";
const IDLE_MS = 30 * 60_000;
const ABSOLUTE_MS = 8 * 60 * 60_000;
const FAILURE_WINDOW_MS = 15 * 60_000;
const LOCKOUT_MS = 15 * 60_000;
const MAX_FAILURES = 5;

function json(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), { status, headers: {
    "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", ...headers
  }});
}
function config(context) { return {
  passwordHash: process.env.ADMIN_PASSWORD_HASH || context.env?.ADMIN_PASSWORD_HASH || "",
  sessionSecret: process.env.ADMIN_SESSION_SECRET || context.env?.ADMIN_SESSION_SECRET || "",
  totpSecret: process.env.ADMIN_TOTP_SECRET || context.env?.ADMIN_TOTP_SECRET || ""
}; }
function store() { return getStore({ name: STORE_NAME, consistency: "strong" }); }
function cookies(request) { const out = {}; for (const part of (request.headers.get("cookie") || "").split(";")) { const i = part.indexOf("="); if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim(); } return out; }
function secretBytes(secret) {
  if (typeof secret === "string" || Buffer.isBuffer(secret) || secret instanceof Uint8Array) return secret;
  if (secret && (typeof secret.value === "string" || Buffer.isBuffer(secret.value) || secret.value instanceof Uint8Array)) return secret.value;
  if (secret && typeof secret.value === "function") return secretBytes(secret.value());
  if (secret && typeof secret.getValue === "function") return secretBytes(secret.getValue());
  if (secret && Array.isArray(secret.data)) return Buffer.from(secret.data);
  if (secret && typeof secret.toString === "function") {
    const rendered = secret.toString();
    if (rendered && rendered !== "[object Object]") return rendered;
  }
  const kind = secret?.constructor?.name || typeof secret;
  const keys = secret && typeof secret === "object" ? Object.keys(secret).join(",").slice(0, 80) : "";
  throw new Error(`服务端密钥类型无效 (${kind}:${keys})`);
}
function hmac(secret, value) { return createHmac("sha256", secretBytes(secret)).update(String(value)).digest("base64url"); }
function safeText(a, b) { a = Buffer.from(String(a)); b = Buffer.from(String(b)); return a.length === b.length && timingSafeEqual(a, b); }
function cookie(value, age = 28_800) { return `${COOKIE}=${value}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${age}`; }
function sessionKey(secret, id) { return `creator/sessions/${hmac(secret, id)}.json`; }

function parsePhc(value) {
  const match = value.match(/^\$argon2id\$v=19\$m=(\d+),t=(\d+),p=(\d+)\$([A-Za-z0-9+/]+={0,2})\$([A-Za-z0-9+/]+={0,2})$/);
  if (!match) throw new Error("ADMIN_PASSWORD_HASH 格式无效");
  return { m: +match[1], t: +match[2], p: +match[3], salt: Uint8Array.from(Buffer.from(match[4], "base64")), hash: Uint8Array.from(Buffer.from(match[5], "base64")) };
}
function verifyPassword(password, encoded) {
  const value = parsePhc(encoded);
  if (value.m < 19456 || value.t < 2 || value.p < 1 || value.hash.length < 32) return false;
  const candidate = argon2id(utf8ToBytes(password), value.salt, { m: value.m, t: value.t, p: value.p, dkLen: value.hash.length, maxmem: 256 * 1024 * 1024 });
  return candidate.length === value.hash.length && timingSafeEqual(Buffer.from(candidate), Buffer.from(value.hash));
}
function base32(value) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"; let bits = "";
  for (const char of value.toUpperCase().replace(/=+$/g, "").replace(/\s+/g, "")) { const i = alphabet.indexOf(char); if (i < 0) throw new Error("ADMIN_TOTP_SECRET 格式无效"); bits += i.toString(2).padStart(5, "0"); }
  const bytes = []; for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2)); return Buffer.from(bytes);
}
function totpAt(secret, counter) { const message = Buffer.alloc(8); message.writeBigUInt64BE(BigInt(counter)); const digest = createHmac("sha1", base32(secret)).update(message).digest(); const offset = digest.at(-1) & 15; return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0"); }
function verifyTotp(code, secret, now) { if (!/^\d{6}$/.test(code)) return false; const counter = Math.floor(now / 30_000); return [-1, 0, 1].some((delta) => safeText(code, totpAt(secret, counter + delta))); }
function clientKey(request, secret) { const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || request.headers.get("cf-connecting-ip") || "unknown"; return hmac(secret, `creator|${ip}`); }
async function audit(blob, event, details = {}) { const timestamp = new Date().toISOString(); await blob.setJSON(`creator/audit/${timestamp.slice(0, 10)}/${timestamp}-${randomUUID()}.json`, { event, timestamp, ...details }); }
async function body(request) { if (Number(request.headers.get("content-length") || 0) > 4096) throw new Error("请求过大"); return request.json(); }

async function activeSession(request, blob, secret) {
  const [id, signature] = (cookies(request)[COOKIE] || "").split(".");
  if (!id || !signature || !safeText(signature, hmac(secret, id))) return null;
  const key = sessionKey(secret, id); const record = await blob.get(key, { type: "json", consistency: "strong" }); if (!record) return null;
  const now = Date.now();
  if (record.revoked_at || now - record.last_active_at > IDLE_MS || now - record.created_at > ABSOLUTE_MS) { await blob.setJSON(key, { ...record, revoked_at: now }); return null; }
  record.last_active_at = now; await blob.setJSON(key, record); return { id, key, record };
}
async function login(context, blob, cfg) {
  const client = clientKey(context.request, cfg.sessionSecret); const key = `creator/rate/${client}.json`; const now = Date.now();
  let rate = await blob.get(key, { type: "json", consistency: "strong" }) || { failures: 0, window_started_at: now, locked_until: 0 };
  if (rate.locked_until > now) return json({ error: "登录尝试过多，请稍后重试" }, 429, { "Retry-After": String(Math.ceil((rate.locked_until - now) / 1000)) });
  if (now - rate.window_started_at > FAILURE_WINDOW_MS) rate = { failures: 0, window_started_at: now, locked_until: 0 };
  const input = await body(context.request); const password = String(input.password || ""); const code = String(input.totp || "").trim(); let valid = false;
  if (password.length >= 12 && password.length <= 256) { try { valid = verifyPassword(password, cfg.passwordHash) && verifyTotp(code, cfg.totpSecret, now); } catch { valid = false; } }
  if (!valid) { rate.failures += 1; if (rate.failures >= MAX_FAILURES) rate.locked_until = now + LOCKOUT_MS; await blob.setJSON(key, rate); await audit(blob, "login_failure", { client_key: client, locked: rate.locked_until > now }); return json({ error: "密码或动态验证码不正确" }, 401); }
  await blob.setJSON(key, { failures: 0, window_started_at: now, locked_until: 0 });
  const id = randomBytes(32).toString("base64url"); const csrf = randomBytes(32).toString("base64url"); const record = { created_at: now, last_active_at: now, csrf_hash: hmac(cfg.sessionSecret, csrf), revoked_at: null };
  await blob.setJSON(sessionKey(cfg.sessionSecret, id), record); await audit(blob, "login_success", { session_key: hmac(cfg.sessionSecret, id) });
  return json({ authenticated: true, csrf, expires_in_seconds: 28_800 }, 200, { "Set-Cookie": cookie(`${id}.${hmac(cfg.sessionSecret, id)}`) });
}

export async function onRequest(context) {
  const cfg = config(context); if (!cfg.passwordHash || !cfg.sessionSecret || !cfg.totpSecret) return json({ error: "创建者鉴权尚未配置" }, 503);
  const blob = store(); const path = new URL(context.request.url).pathname.replace(/\/+$/, "");
  try {
    if (path === "/api/creator/login" && context.request.method === "POST") return await login(context, blob, cfg);
    const active = await activeSession(context.request, blob, cfg.sessionSecret); if (!active) return json({ error: "未登录或会话已过期" }, 401, { "Set-Cookie": cookie("", 0) });
    if (path === "/api/creator/session" && context.request.method === "GET") { const csrf = randomBytes(32).toString("base64url"); active.record.csrf_hash = hmac(cfg.sessionSecret, csrf); await blob.setJSON(active.key, active.record); return json({ authenticated: true, csrf, idle_timeout_minutes: 30, absolute_timeout_hours: 8 }); }
    if (path === "/api/creator/logout" && context.request.method === "POST") { const csrf = context.request.headers.get("x-csrf-token") || ""; if (!safeText(hmac(cfg.sessionSecret, csrf), active.record.csrf_hash)) return json({ error: "CSRF 校验失败" }, 403); active.record.revoked_at = Date.now(); await blob.setJSON(active.key, active.record); await audit(blob, "logout", { session_key: hmac(cfg.sessionSecret, active.id) }); return json({ authenticated: false }, 200, { "Set-Cookie": cookie("", 0) }); }
    if (path === "/api/creator/summary" && context.request.method === "GET") return json({ authenticated: true, status: "creator_dashboard_ready", patent_integration: "pending_epo_approval" });
    return json({ error: "接口不存在" }, 404);
  } catch (error) { return json({ error: error instanceof Error ? error.message.slice(0, 200) : "服务器处理失败" }, 500); }
}
