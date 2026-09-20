#!/usr/bin/env python3
"""Dependency-free local API for the life-science research workbench."""

from __future__ import annotations

import hashlib
import http.cookies
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = ROOT / "data" / "private"
DB_PATH = DATA / "workbench.sqlite3"
ENV_PATH = ROOT / ".env"
MAX_TOPIC = 120
SESSION_COOKIE = "lsrw_session"
SOURCE_LIMIT = 12
STAGES = ["理解研究主题", "检索与筛选资料", "建立证据库", "生成技术摘要", "核验引用"]


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as connection:
        connection.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL,
          topic TEXT NOT NULL, search_query TEXT, status TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0,
          message TEXT NOT NULL, report TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
          input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
          estimated_cost_cny REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(owner_hash, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS sources (
          job_id TEXT NOT NULL, source_id TEXT NOT NULL, provider TEXT NOT NULL, title TEXT NOT NULL,
          url TEXT NOT NULL, doi TEXT, abstract TEXT, published TEXT, read_scope TEXT NOT NULL,
          crossref_validated INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job_id, source_id)
        );
        """)
        cutoff = datetime.fromtimestamp(time.time() - 7 * 86400, timezone.utc).isoformat()
        connection.execute("UPDATE jobs SET status='failed', message='服务重启后任务已安全结束', error='可重新提交任务', updated_at=? WHERE status IN ('queued','running')", (now(),))
        connection.execute("DELETE FROM sources WHERE job_id IN (SELECT id FROM jobs WHERE created_at < ?)", (cutoff,))
        connection.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))


def update_job(job_id: str, **fields) -> None:
    fields["updated_at"] = now()
    with db() as connection:
        connection.execute(
            f"UPDATE jobs SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
            [*fields.values(), job_id],
        )


def cancelled(job_id: str) -> bool:
    with db() as connection:
        row = connection.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
    return not row or bool(row[0])


def request_json(url: str, *, method="GET", payload=None, headers=None, timeout=25):
    body = None if payload is None else json.dumps(payload).encode()
    request_headers = {"User-Agent": "LifeScienceResearchWorkbench/0.1 (research demo)", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def call_deepseek(messages, max_tokens: int, timeout: int = 180):
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("本地未配置 DEEPSEEK_API_KEY")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    data = request_json(
        f"{base}/chat/completions", method="POST", timeout=timeout,
        headers={"Authorization": f"Bearer {key}"},
        payload={"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens,
                 "stream": False, "thinking": {"type": "disabled"}, "reasoning_effort": "none"},
    )
    usage = data.get("usage") or {}
    text = data["choices"][0]["message"]["content"].strip()
    if not text:
        raise RuntimeError("模型返回空正文")
    return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def pubmed_sources(query: str) -> list[dict]:
    def search(term):
        params = urllib.parse.urlencode({"db": "pubmed", "term": term, "retmax": 6, "sort": "relevance", "retmode": "json"})
        result = request_json(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}")
        return result.get("esearchresult", {}).get("idlist", [])

    ids = search(query)
    if not ids:
        stop = {"main", "technical", "routes", "route", "approaches", "current", "key", "limitations", "challenges", "and", "the", "of", "in"}
        relaxed = " ".join(word for word in re.findall(r"[A-Za-z0-9+-]+", query) if word.lower() not in stop)
        ids = search(relaxed)
    if not ids:
        return []
    fetch = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    req = urllib.request.Request(
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{fetch}",
        headers={"User-Agent": "LifeScienceResearchWorkbench/0.1"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        root = ET.fromstring(response.read())
    items = []
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//PMID", "")
        title_node = article.find(".//ArticleTitle")
        title = "".join(title_node.itertext()).strip() if title_node is not None else "Untitled"
        abstracts = ["".join(node.itertext()).strip() for node in article.findall(".//Abstract/AbstractText")]
        doi = ""
        for node in article.findall(".//ArticleId"):
            if node.attrib.get("IdType") == "doi": doi = (node.text or "").strip()
        date = article.findtext(".//PubDate/Year") or article.findtext(".//PubDate/MedlineDate") or ""
        items.append({"provider": "PubMed", "title": title, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "doi": doi, "abstract": " ".join(abstracts), "published": date, "read_scope": "bibliographic_and_abstract"})
    return items


def europe_pmc_sources(query: str) -> list[dict]:
    params = urllib.parse.urlencode({"query": query, "format": "json", "pageSize": 6, "resultType": "core"})
    data = request_json(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}")
    items = []
    for row in data.get("resultList", {}).get("result", []):
        identifier = row.get("pmid") or row.get("pmcid") or row.get("id", "")
        items.append({
            "provider": "Europe PMC", "title": row.get("title") or "Untitled",
            "url": f"https://europepmc.org/article/{row.get('source', 'MED')}/{identifier}",
            "doi": row.get("doi") or "", "abstract": row.get("abstractText") or "",
            "published": str(row.get("pubYear") or ""),
            "read_scope": "open_full_text_signal" if row.get("isOpenAccess") == "Y" else "bibliographic_and_abstract",
        })
    return items


def merge_sources(*groups) -> list[dict]:
    seen, output = set(), []
    for item in sum(groups, []):
        key = (item.get("doi") or re.sub(r"\W", "", item["title"].lower())[:100]).lower()
        if not key or key in seen: continue
        seen.add(key); output.append(item)
        if len(output) >= SOURCE_LIMIT: break
    return output


def validate_crossref(items: list[dict]) -> None:
    checked = 0
    for item in items:
        if not item.get("doi") or checked >= 4: continue
        try:
            encoded = urllib.parse.quote(item["doi"], safe="")
            data = request_json(f"https://api.crossref.org/works/{encoded}", timeout=15)
            item["crossref_validated"] = data.get("status") == "ok"
        except Exception:
            item["crossref_validated"] = False
        checked += 1


def add_usage(job_id: str, input_tokens: int, output_tokens: int) -> None:
    # Worst-case peak/cache-miss pricing from config: CNY 2/M input, 8/M output.
    added = input_tokens * 2 / 1_000_000 + output_tokens * 8 / 1_000_000
    with db() as connection:
        connection.execute("""UPDATE jobs SET input_tokens=input_tokens+?, output_tokens=output_tokens+?,
          estimated_cost_cny=estimated_cost_cny+?, updated_at=? WHERE id=?""",
          (input_tokens, output_tokens, added, now(), job_id))
        cost = connection.execute("SELECT estimated_cost_cny FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    if cost >= 1.0:
        raise RuntimeError("任务达到 1 元模型费用硬停止线")


def fallback_query(topic: str) -> str:
    translations = {
        "肿瘤": "cancer", "早筛": "early detection", "液体活检": "liquid biopsy",
        "分子诊断": "molecular diagnostics", "药物递送": "drug delivery", "递送系统": "delivery system",
        "单细胞测序": "single-cell sequencing", "肿瘤微环境": "tumor microenvironment",
        "肠道微生物": "gut microbiome", "衰老": "aging", "合成生物学": "synthetic biology",
        "发酵": "fermentation", "关键限制": "limitations", "技术路线": "technology approaches",
    }
    terms = [english for chinese, english in translations.items() if chinese in topic]
    latin = re.findall(r"[A-Za-z][A-Za-z0-9+-]{1,30}", topic)
    return " ".join(dict.fromkeys([*latin, *terms])) or topic


def run_job(job_id: str) -> None:
    try:
        with db() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        update_job(job_id, status="running", stage=0, message="正在生成中英文检索式")
        try:
            query, p, c = call_deepseek([
                {"role": "system", "content": "Convert the user's life-science topic into one concise English literature search query. Output only the query; do not invent identifiers or citations."},
                {"role": "user", "content": job["topic"]},
            ], 180, timeout=60)
            add_usage(job_id, p, c)
        except Exception:
            query = fallback_query(job["topic"])
            update_job(job_id, message="模型检索式生成超时，已使用本地保守关键词继续")
        query = query.replace("\n", " ")[:300]
        update_job(job_id, search_query=query)
        if cancelled(job_id): raise InterruptedError()

        update_job(job_id, stage=1, message="正在检索 PubMed 与 Europe PMC")
        errors = []
        try: pubmed = pubmed_sources(query)
        except Exception as exc: pubmed, errors = [], [f"PubMed: {type(exc).__name__}"]
        try: epmc = europe_pmc_sources(query)
        except Exception as exc: epmc, errors = [], [*errors, f"Europe PMC: {type(exc).__name__}"]
        sources = merge_sources(pubmed, epmc)
        if not sources:
            raise RuntimeError("论文接口未返回可用资料；" + "；".join(errors))
        if cancelled(job_id): raise InterruptedError()

        update_job(job_id, stage=2, message="正在去重并用 Crossref 核对 DOI")
        validate_crossref(sources)
        with db() as connection:
            for index, item in enumerate(sources, 1):
                item["source_id"] = f"S{index}"
                connection.execute("""INSERT OR REPLACE INTO sources
                  (job_id,source_id,provider,title,url,doi,abstract,published,read_scope,crossref_validated)
                  VALUES (?,?,?,?,?,?,?,?,?,?)""", (job_id, item["source_id"], item["provider"], item["title"], item["url"],
                  item.get("doi", ""), item.get("abstract", ""), item.get("published", ""), item["read_scope"], int(item.get("crossref_validated", False))))
        if cancelled(job_id): raise InterruptedError()

        evidence = "\n\n".join(
            f"[{x['source_id']}] {x['title']}\nProvider: {x['provider']}; Year: {x.get('published')}; DOI: {x.get('doi') or 'none'}; Read scope: {x['read_scope']}\nAbstract: {(x.get('abstract') or 'Abstract unavailable')[:1800]}"
            for x in sources
        )
        update_job(job_id, stage=3, message="正在根据已读取证据生成技术摘要")
        report, p, c = call_deepseek([
            {"role": "system", "content": "You write conservative Chinese life-science research summaries. Use only supplied evidence. Cite every material factual claim with [S#]. Never invent papers, numbers, efficacy, approval status, patent results or full-text access. Clearly distinguish abstract-only evidence and state that EPO patent retrieval is pending. Output Markdown."},
            {"role": "user", "content": f"Topic: {job['topic']}\nSearch query: {query}\n\nEvidence:\n{evidence}\n\nWrite: scope, current technical routes, representative findings, limitations, evidence gaps, and a source list."},
        ], 2600)
        add_usage(job_id, p, c)
        if cancelled(job_id): raise InterruptedError()

        update_job(job_id, stage=4, message="正在核验引用并修订不支持结论")
        final, p, c = call_deepseek([
            {"role": "system", "content": "Audit the draft strictly against the evidence. Remove or weaken unsupported claims and invalid source IDs. Preserve useful structure. Every important factual claim needs a valid [S#]. Explicitly disclose abstract-only reading and unavailable patent retrieval. Output only corrected Markdown."},
            {"role": "user", "content": f"Evidence:\n{evidence}\n\nDraft:\n{report}"},
        ], 2600)
        add_usage(job_id, p, c)
        if "EPO" not in final:
            final += "\n\n> 专利检索状态：EPO OPS 账号仍在等待管理员审批，本报告未执行专利检索，不代表不存在相关专利。"
        valid = {x["source_id"] for x in sources}
        used = set(re.findall(r"\[(S\d+)\]", final))
        if not used or not used <= valid:
            raise RuntimeError("引用核验失败：报告包含缺失或无效的来源编号")
        update_job(job_id, status="completed", stage=4, message="技术摘要已完成引用核验", report=final, error=None)
    except InterruptedError:
        update_job(job_id, status="cancelled", message="任务已取消；已停止后续步骤")
    except Exception as exc:
        with db() as connection:
            count = connection.execute("SELECT COUNT(*) FROM sources WHERE job_id=?", (job_id,)).fetchone()[0]
        update_job(job_id, status="partial" if count else "failed", message="已保留可用资料，报告未完成" if count else "任务未完成", error=str(exc)[:500])


def public_job(row, sources=None):
    return {
        "id": row["id"], "topic": row["topic"], "search_query": row["search_query"],
        "status": row["status"], "stage": row["stage"], "stages": STAGES,
        "message": row["message"], "report": row["report"], "error": row["error"],
        "usage": {"input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"], "estimated_cost_cny": round(row["estimated_cost_cny"], 4)},
        "sources": [dict(x) for x in (sources or [])],
        "patent_status": "EPO OPS 账号等待管理员审批，当前任务未执行专利检索",
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):
        # Do not log URLs because they may include user task identifiers.
        print(f"[{self.log_date_time_string()}] {args[1] if len(args)>1 else ''}")

    def json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 16_384: raise ValueError("请求过大")
        return json.loads(self.rfile.read(length) or b"{}")

    def session(self, create=False):
        cookie = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get(SESSION_COOKIE).value if cookie.get(SESSION_COOKIE) else ""
        created = False
        if create and not token:
            token, created = secrets.token_urlsafe(32), True
        return token, created

    def send_json(self, status, payload, session_token=None):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        if session_token:
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={session_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800{secure}")
        self.end_headers(); self.wfile.write(body)

    def owned_job(self, job_id):
        token, _ = self.session()
        if not token: return None
        with db() as connection:
            return connection.execute("SELECT * FROM jobs WHERE id=? AND owner_hash=?", (job_id, owner_hash(token))).fetchone()

    def do_POST(self):
        try:
            if self.path == "/api/research-jobs":
                data = self.json_body(); topic = re.sub(r"\s+", " ", str(data.get("topic", "")).strip())
                idem = str(data.get("idempotency_key", ""))
                if len(topic) < 4 or len(topic) > MAX_TOPIC: return self.send_json(400, {"error": "主题长度应为 4—120 个字"})
                if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", idem): return self.send_json(400, {"error": "无效的重复提交标识"})
                token, created = self.session(create=True); hashed = owner_hash(token)
                with db() as connection:
                    existing = connection.execute("SELECT * FROM jobs WHERE owner_hash=? AND idempotency_key=?", (hashed, idem)).fetchone()
                    if existing:
                        if existing["topic"] != topic: return self.send_json(409, {"error": "同一提交标识不能用于不同主题"})
                        return self.send_json(200, public_job(existing), token if created else None)
                    job_id = secrets.token_urlsafe(18); timestamp = now()
                    connection.execute("""INSERT INTO jobs (id,owner_hash,idempotency_key,topic,status,stage,message,created_at,updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?)""", (job_id, hashed, idem, topic, "queued", 0, "任务已创建", timestamp, timestamp))
                threading.Thread(target=run_job, args=(job_id,), daemon=True).start()
                return self.send_json(202, {"id": job_id, "status": "queued"}, token if created else None)
            match = re.fullmatch(r"/api/research-jobs/([A-Za-z0-9_-]+)/cancel", self.path)
            if match:
                job = self.owned_job(match.group(1))
                if not job: return self.send_json(404, {"error": "任务不存在或无权访问"})
                if job["status"] in ("completed", "failed", "cancelled"): return self.send_json(409, {"error": "任务已结束"})
                update_job(job["id"], cancel_requested=1, message="正在停止后续步骤")
                return self.send_json(202, {"status": "cancelling"})
            return self.send_json(404, {"error": "接口不存在"})
        except (ValueError, json.JSONDecodeError) as exc: self.send_json(400, {"error": str(exc)})
        except Exception: self.send_json(500, {"error": "服务器处理失败"})

    def do_GET(self):
        match = re.fullmatch(r"/api/research-jobs/([A-Za-z0-9_-]+)", self.path)
        if match:
            job = self.owned_job(match.group(1))
            if not job: return self.send_json(404, {"error": "任务不存在或无权访问"})
            with db() as connection:
                sources = connection.execute("SELECT source_id,provider,title,url,doi,published,read_scope,crossref_validated FROM sources WHERE job_id=? ORDER BY source_id", (job["id"],)).fetchall()
            return self.send_json(200, public_job(job, sources))
        return super().do_GET()


if __name__ == "__main__":
    load_env(); init_db()
    port = int(os.getenv("PORT", "4173"))
    print(f"Workbench running at http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
