import { createHmac, randomBytes, randomUUID } from "node:crypto";
import { getStore } from "@edgeone/pages-blob";

const STORE_NAME = "life-science-workbench";
const SESSION_COOKIE = "lsrw_session";
const SOURCE_LIMIT = 12;
const FINISHED = new Set(["completed", "partial", "failed", "cancelled"]);
const STAGES = ["理解研究主题", "检索与筛选资料", "建立证据库", "生成并核验"];

function response(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      ...extraHeaders
    }
  });
}

function env(context) {
  return {
    deepseekKey: context.env?.DEEPSEEK_API_KEY || process.env.DEEPSEEK_API_KEY || "",
    deepseekBase: context.env?.DEEPSEEK_BASE_URL || process.env.DEEPSEEK_BASE_URL || "https://api.deepseek.com",
    deepseekModel: context.env?.DEEPSEEK_MODEL || process.env.DEEPSEEK_MODEL || "deepseek-flash",
    taskSecret: context.env?.TASK_ACCESS_TOKEN_SECRET || process.env.TASK_ACCESS_TOKEN_SECRET || ""
  };
}

function store() {
  return getStore({ name: STORE_NAME, consistency: "strong" });
}

function cookies(request) {
  const output = {};
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const index = part.indexOf("=");
    if (index > 0) output[part.slice(0, index).trim()] = part.slice(index + 1).trim();
  }
  return output;
}

function session(request, settings, create = false) {
  let token = cookies(request)[SESSION_COOKIE] || "";
  let created = false;
  if (!token && create) {
    token = randomBytes(32).toString("base64url");
    created = true;
  }
  const owner = token && settings.taskSecret
    ? createHmac("sha256", settings.taskSecret).update(token).digest("hex")
    : "";
  return { token, owner, created };
}

function sessionHeader(token) {
  return `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=604800`;
}

function jobKey(owner, id) {
  return `jobs/${owner}/${id}.json`;
}

async function readJob(blob, owner, id) {
  if (!owner || !/^[A-Za-z0-9_-]{10,80}$/.test(id)) return null;
  return blob.get(jobKey(owner, id), { type: "json", consistency: "strong" });
}

async function writeJob(blob, owner, job) {
  job.updated_at = new Date().toISOString();
  await blob.setJSON(jobKey(owner, job.id), job);
  return job;
}

function publicJob(job) {
  return {
    id: job.id,
    topic: job.topic,
    search_query: job.search_query || null,
    status: job.status,
    stage: job.stage,
    stages: STAGES,
    message: job.message,
    report: job.report || null,
    error: job.error || null,
    usage: job.usage,
    sources: (job.sources || []).map(({ abstract, ...source }) => source),
    patent_status: "EPO OPS 账号等待管理员审批，当前任务未执行专利检索",
    created_at: job.created_at,
    updated_at: job.updated_at
  };
}

async function readJson(request) {
  const size = Number(request.headers.get("content-length") || 0);
  if (size > 16_384) throw new Error("请求过大");
  return request.json();
}

async function deepseek(settings, messages, maxTokens) {
  if (!settings.deepseekKey) throw new Error("生产环境未配置 DEEPSEEK_API_KEY");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 90_000);
  try {
    const result = await fetch(`${settings.deepseekBase.replace(/\/$/, "")}/chat/completions`, {
      method: "POST",
      signal: controller.signal,
      headers: {
        "Authorization": `Bearer ${settings.deepseekKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model: settings.deepseekModel,
        messages,
        temperature: 0.1,
        max_tokens: maxTokens,
        stream: false,
        thinking: { type: "disabled" },
        reasoning_effort: "none"
      })
    });
    if (!result.ok) throw new Error(`DeepSeek 返回 ${result.status}`);
    const data = await result.json();
    const text = data.choices?.[0]?.message?.content?.trim();
    if (!text) throw new Error("DeepSeek 未返回正文");
    return { text, usage: data.usage || {} };
  } finally {
    clearTimeout(timeout);
  }
}

function addUsage(job, apiUsage) {
  const input = Number(apiUsage.prompt_tokens || 0);
  const output = Number(apiUsage.completion_tokens || 0);
  job.usage.input_tokens += input;
  job.usage.output_tokens += output;
  job.usage.estimated_cost_cny += input * 2 / 1_000_000 + output * 8 / 1_000_000;
  job.usage.estimated_cost_cny = Number(job.usage.estimated_cost_cny.toFixed(6));
  if (job.usage.estimated_cost_cny >= 1) throw new Error("任务达到 1 元模型费用硬停止线");
}

function fallbackQuery(topic) {
  const terms = {
    "肿瘤": "cancer", "早筛": "early detection", "液体活检": "liquid biopsy",
    "分子诊断": "molecular diagnostics", "药物递送": "drug delivery",
    "单细胞测序": "single-cell sequencing", "肿瘤微环境": "tumor microenvironment",
    "肠道微生物": "gut microbiome", "衰老": "aging", "合成生物学": "synthetic biology",
    "发酵": "fermentation", "关键限制": "limitations", "技术路线": "technology approaches"
  };
  const translated = Object.entries(terms).filter(([key]) => topic.includes(key)).map(([, value]) => value);
  const latin = topic.match(/[A-Za-z][A-Za-z0-9+-]{1,30}/g) || [];
  return [...new Set([...latin, ...translated])].join(" ") || topic;
}

async function pubmed(query) {
  async function search(term) {
    const searchUrl = new URL("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi");
    searchUrl.search = new URLSearchParams({ db: "pubmed", term, retmax: "6", sort: "relevance", retmode: "json" });
    const result = await fetch(searchUrl, { headers: { "User-Agent": "LifeScienceResearchWorkbench/0.2" } });
    if (!result.ok) throw new Error(`PubMed 检索返回 ${result.status}`);
    return (await result.json()).esearchresult?.idlist || [];
  }
  let ids = await search(query);
  if (!ids.length) {
    const stop = new Set(["main", "technical", "routes", "route", "approaches", "current", "key", "limitations", "challenges", "and", "the", "of", "in"]);
    const relaxed = (query.match(/[A-Za-z0-9+-]+/g) || []).filter((word) => !stop.has(word.toLowerCase())).join(" ");
    if (relaxed && relaxed !== query) ids = await search(relaxed);
  }
  if (!ids.length) return [];
  const summaryUrl = new URL("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi");
  summaryUrl.search = new URLSearchParams({ db: "pubmed", id: ids.join(","), retmode: "json" });
  const summary = await fetch(summaryUrl, { headers: { "User-Agent": "LifeScienceResearchWorkbench/0.2" } });
  if (!summary.ok) throw new Error(`PubMed 详情返回 ${summary.status}`);
  const data = (await summary.json()).result || {};
  return (data.uids || []).map((id) => {
    const row = data[id] || {};
    const doi = (row.articleids || []).find((item) => item.idtype === "doi")?.value || "";
    return {
      provider: "PubMed", title: cleanText(row.title || "Untitled"), url: `https://pubmed.ncbi.nlm.nih.gov/${id}/`,
      doi, abstract: "", published: row.pubdate || "", read_scope: "bibliographic_record",
      crossref_validated: false
    };
  });
}

function cleanText(value) {
  return String(value)
    .replace(/<[^>]*>/g, "")
    .replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&amp;", "&")
    .replaceAll("&quot;", "\"").replaceAll("&#39;", "'").replace(/\s+/g, " ").trim();
}

async function europePmc(query) {
  const url = new URL("https://www.ebi.ac.uk/europepmc/webservices/rest/search");
  url.search = new URLSearchParams({ query, format: "json", pageSize: "8", resultType: "core" });
  const result = await fetch(url, { headers: { "User-Agent": "LifeScienceResearchWorkbench/0.2" } });
  if (!result.ok) throw new Error(`Europe PMC 返回 ${result.status}`);
  const data = await result.json();
  return (data.resultList?.result || []).map((row) => {
    const id = row.pmid || row.pmcid || row.id || "";
    return {
      provider: "Europe PMC", title: cleanText(row.title || "Untitled"),
      url: `https://europepmc.org/article/${row.source || "MED"}/${id}`,
      doi: row.doi || "", abstract: row.abstractText || "", published: String(row.pubYear || ""),
      read_scope: row.isOpenAccess === "Y" ? "abstract_and_open_access_signal" : "bibliographic_and_abstract",
      crossref_validated: false
    };
  });
}

function mergeSources(...groups) {
  const seen = new Set();
  const output = [];
  for (const source of groups.flat()) {
    const key = (source.doi || source.title.toLowerCase().replace(/\W/g, "").slice(0, 100)).toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    source.source_id = `S${output.length + 1}`;
    output.push(source);
    if (output.length >= SOURCE_LIMIT) break;
  }
  return output;
}

async function validateCrossref(sources) {
  let checked = 0;
  for (const source of sources) {
    if (!source.doi || checked >= 4) continue;
    try {
      const result = await fetch(`https://api.crossref.org/works/${encodeURIComponent(source.doi)}`, {
        headers: { "User-Agent": "LifeScienceResearchWorkbench/0.2" }
      });
      source.crossref_validated = result.ok;
    } catch {
      source.crossref_validated = false;
    }
    checked += 1;
  }
}

function evidence(job) {
  return job.sources.map((source) =>
    `[${source.source_id}] ${source.title}\nProvider: ${source.provider}; Year: ${source.published || "unknown"}; DOI: ${source.doi || "none"}; Read scope: ${source.read_scope}\nAbstract: ${(source.abstract || "Abstract unavailable") .slice(0, 1800)}`
  ).join("\n\n");
}

async function advanceJob(blob, owner, job, settings) {
  if (job.cancel_requested) {
    job.status = "cancelled";
    job.message = "任务已取消";
    return writeJob(blob, owner, job);
  }
  job.status = "running";
  try {
    if (job.stage === 0 && !job.search_query) {
      job.message = "正在生成中英文检索式";
      await writeJob(blob, owner, job);
      try {
        const result = await deepseek(settings, [
          { role: "system", content: "Convert the user's life-science topic into one concise English literature search query. Output only the query; do not invent identifiers or citations." },
          { role: "user", content: job.topic }
        ], 180);
        job.search_query = result.text.replace(/\s+/g, " ").slice(0, 300);
        addUsage(job, result.usage);
      } catch {
        job.search_query = fallbackQuery(job.topic);
        job.message = "模型检索式生成失败，已使用本地保守关键词";
      }
      job.stage = 1;
    } else if (job.stage === 1) {
      job.message = "正在检索 PubMed 与 Europe PMC";
      await writeJob(blob, owner, job);
      const results = await Promise.allSettled([pubmed(job.search_query), europePmc(job.search_query)]);
      const pubmedRows = results[0].status === "fulfilled" ? results[0].value : [];
      const epmcRows = results[1].status === "fulfilled" ? results[1].value : [];
      job.sources = mergeSources(pubmedRows, epmcRows);
      if (!job.sources.length) throw new Error("论文接口未返回可用资料");
      job.stage = 2;
      job.message = `已保存 ${job.sources.length} 条去重资料`;
    } else if (job.stage === 2) {
      job.message = "正在核对 DOI 并生成技术摘要";
      await writeJob(blob, owner, job);
      await validateCrossref(job.sources);
      const result = await deepseek(settings, [
        { role: "system", content: "Write a conservative Chinese life-science research summary using only the supplied evidence. Cite every material factual claim with [S#]. Never invent papers, numbers, efficacy, approval status, patent results or full-text access. Explicitly distinguish bibliographic-only and abstract evidence. State that EPO patent retrieval is pending. Output Markdown." },
        { role: "user", content: `Topic: ${job.topic}\nSearch query: ${job.search_query}\n\nEvidence:\n${evidence(job)}\n\nWrite: scope, current technical routes, representative findings, limitations, evidence gaps, and a source list.` }
      ], 2200);
      job.draft = result.text;
      addUsage(job, result.usage);
      job.stage = 3;
    } else if (job.stage === 3) {
      job.message = "正在核验引用并修订不支持结论";
      await writeJob(blob, owner, job);
      const result = await deepseek(settings, [
        { role: "system", content: "Audit the draft strictly against the evidence. Remove or weaken unsupported claims and invalid source IDs. Preserve useful structure. Every important factual claim needs a valid [S#]. Explicitly disclose abstract-only reading and unavailable EPO patent retrieval. Output only corrected Markdown." },
        { role: "user", content: `Evidence:\n${evidence(job)}\n\nDraft:\n${job.draft}` }
      ], 2200);
      addUsage(job, result.usage);
      let final = result.text;
      if (!final.includes("EPO")) final += "\n\n> 专利检索状态：EPO OPS 账号仍在等待管理员审批，本报告未执行专利检索，不代表不存在相关专利。";
      const valid = new Set(job.sources.map((source) => source.source_id));
      const used = [...final.matchAll(/\[(S\d+)\]/g)].map((match) => match[1]);
      if (!used.length || used.some((id) => !valid.has(id))) throw new Error("引用核验失败：报告包含缺失或无效的来源编号");
      job.report = final;
      delete job.draft;
      job.status = "completed";
      job.message = "技术摘要已完成引用核验";
    }
    return writeJob(blob, owner, job);
  } catch (error) {
    job.status = job.sources?.length ? "partial" : "failed";
    job.message = job.sources?.length ? "已保留可用资料，报告未完成" : "任务未完成";
    job.error = error instanceof Error ? error.message.slice(0, 500) : "未知错误";
    return writeJob(blob, owner, job);
  }
}

async function createJob(context, blob, settings) {
  if (!settings.taskSecret) return response({ error: "生产环境未配置 TASK_ACCESS_TOKEN_SECRET" }, 503);
  const data = await readJson(context.request);
  const topic = String(data.topic || "").trim().replace(/\s+/g, " ");
  const idempotency = String(data.idempotency_key || "");
  if (topic.length < 4 || topic.length > 120) return response({ error: "主题长度应为 4—120 个字" }, 400);
  if (!/^[A-Za-z0-9_-]{16,100}$/.test(idempotency)) return response({ error: "无效的重复提交标识" }, 400);
  const identity = session(context.request, settings, true);
  const idemKey = `idempotency/${identity.owner}/${idempotency}.json`;
  const previous = await blob.get(idemKey, { type: "json", consistency: "strong" });
  if (previous) {
    const existing = await readJob(blob, identity.owner, previous.id);
    if (existing?.topic !== topic) return response({ error: "同一提交标识不能用于不同主题" }, 409);
    return response(publicJob(existing), 200, identity.created ? { "Set-Cookie": sessionHeader(identity.token) } : {});
  }
  const timestamp = new Date().toISOString();
  const job = {
    id: randomUUID().replaceAll("-", ""), topic, status: "queued", stage: 0,
    message: "任务已创建", search_query: null, sources: [], report: null, error: null,
    cancel_requested: false, usage: { input_tokens: 0, output_tokens: 0, estimated_cost_cny: 0 },
    created_at: timestamp, updated_at: timestamp, expires_at: new Date(Date.now() + 7 * 86400_000).toISOString()
  };
  await blob.setJSON(idemKey, { id: job.id, created_at: timestamp }, { onlyIfNew: true });
  await writeJob(blob, identity.owner, job);
  return response({ id: job.id, status: job.status }, 202, { "Set-Cookie": sessionHeader(identity.token) });
}

export async function onRequest(context) {
  const settings = env(context);
  const blob = store();
  const url = new URL(context.request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  try {
    if (path === "/api/research-jobs" && context.request.method === "POST") {
      return await createJob(context, blob, settings);
    }
    const match = path.match(/^\/api\/research-jobs\/([A-Za-z0-9_-]+)(?:\/(advance|cancel))?$/);
    if (!match) return response({ error: "接口不存在" }, 404);
    if (!settings.taskSecret) return response({ error: "生产环境未配置 TASK_ACCESS_TOKEN_SECRET" }, 503);
    const identity = session(context.request, settings);
    const job = await readJob(blob, identity.owner, match[1]);
    if (!job) return response({ error: "任务不存在或无权访问" }, 404);
    if (!match[2] && context.request.method === "GET") return response(publicJob(job));
    if (match[2] === "cancel" && context.request.method === "POST") {
      if (FINISHED.has(job.status)) return response({ error: "任务已结束" }, 409);
      job.cancel_requested = true;
      job.message = "将在当前步骤结束后停止";
      await writeJob(blob, identity.owner, job);
      return response({ status: "cancelling" }, 202);
    }
    if (match[2] === "advance" && context.request.method === "POST") {
      if (FINISHED.has(job.status)) return response(publicJob(job));
      const advanced = await advanceJob(blob, identity.owner, job, settings);
      return response(publicJob(advanced));
    }
    return response({ error: "请求方法不支持" }, 405);
  } catch (error) {
    return response({ error: error instanceof Error ? error.message.slice(0, 300) : "服务器处理失败" }, 500);
  }
}
