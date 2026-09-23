const form = document.querySelector("#research-form");
const topic = document.querySelector("#topic");
const count = document.querySelector("#topic-count");
const error = document.querySelector("#topic-error");
const submit = document.querySelector("#submit-button");
const workspace = document.querySelector("#workspace");
const workspaceTopic = document.querySelector("#workspace-topic");
const jobStatus = document.querySelector("#job-status");
const jobMessage = document.querySelector("#job-message");
const jobSteps = document.querySelectorAll("#job-steps li");
const emptyReport = document.querySelector("#empty-report");
const report = document.querySelector("#report");
const sourceList = document.querySelector("#source-list");
const cancelButton = document.querySelector("#cancel-job");
const usage = document.querySelector("#usage");
let activeJobId = sessionStorage.getItem("activeResearchJob");
let pollTimer;

function normalizedTopic() {
  return topic.value.trim().replace(/\s+/g, " ");
}

function validateTopic() {
  const value = normalizedTopic();
  if (!value) return "请输入一个生命科学研究主题。";
  if (value.length < 4) return "主题太短，请补充研究对象或技术方向。";
  if (value.length > 120) return "主题最多 120 个字。";
  return "";
}

topic.addEventListener("input", () => {
  count.textContent = String(topic.value.length);
  error.textContent = "";
  topic.removeAttribute("aria-invalid");
});

document.querySelectorAll("[data-topic]").forEach((button) => {
  button.addEventListener("click", () => {
    topic.value = button.dataset.topic;
    topic.dispatchEvent(new Event("input"));
    topic.focus();
  });
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = validateTopic();
  if (message) {
    error.textContent = message;
    topic.setAttribute("aria-invalid", "true");
    topic.focus();
    return;
  }

  createJob(normalizedTopic());
});

function idempotencyKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(18));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

async function createJob(value) {
  submit.disabled = true;
  error.textContent = "";
  try {
    const response = await fetch("/api/research-jobs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: value, idempotency_key: idempotencyKey() }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "任务创建失败");
    activeJobId = data.id;
    sessionStorage.setItem("activeResearchJob", activeJobId);
    workspaceTopic.textContent = value;
    workspace.hidden = false;
    cancelButton.hidden = false;
    workspace.scrollIntoView({ behavior: "smooth", block: "start" });
    await pollJob();
  } catch (problem) {
    error.textContent = problem.message;
  } finally {
    submit.disabled = false;
  }
}

function renderPlainMarkdown(markdown) {
  report.textContent = markdown;
}

function renderJob(job) {
  workspaceTopic.textContent = job.topic;
  jobStatus.textContent = ({ queued: "排队中", running: "调研进行中", completed: "已核验", partial: "部分完成", failed: "未完成", cancelled: "已取消" })[job.status] || job.status;
  jobStatus.className = `demo-badge status-${job.status}`;
  const sourceNotice = job.source_status?.pubmed === "fallback_via_europe_pmc"
    ? "PubMed 直连不可用，本次通过 Europe PMC 的 MED 备用通道读取 PubMed 索引记录。"
    : "";
  jobMessage.textContent = job.error
    ? `${job.message}：${job.error}`
    : `${job.message}。${sourceNotice}${job.patent_status}`;
  jobSteps.forEach((step, index) => {
    step.classList.toggle("active", index === job.stage && job.status === "running");
    step.classList.toggle("done", index < job.stage || job.status === "completed");
    const note = step.querySelector("small");
    if (index === job.stage) note.textContent = job.message;
  });
  usage.textContent = `模型用量：${job.usage.input_tokens + job.usage.output_tokens} tokens · 费用上界估算 ¥${job.usage.estimated_cost_cny.toFixed(4)}`;
  if (job.report) {
    emptyReport.hidden = true; report.hidden = false;
    renderPlainMarkdown(job.report);
  }
  if (job.sources.length) {
    sourceList.hidden = false;
    const list = sourceList.querySelector("ol"); list.replaceChildren();
    job.sources.forEach((source) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.textContent = `[${source.source_id}] ${source.title}`;
      const meta = document.createElement("span");
      meta.textContent = `${source.provider} · ${source.published || "日期未知"} · ${source.read_scope}${source.crossref_validated ? " · DOI 已核对" : ""}`;
      item.append(link, meta); list.append(item);
    });
  }
  const ended = ["completed", "partial", "failed", "cancelled"].includes(job.status);
  cancelButton.hidden = ended;
  if (ended) { clearTimeout(pollTimer); sessionStorage.removeItem("activeResearchJob"); }
  return ended;
}

async function pollJob() {
  if (!activeJobId) return;
  try {
    const response = await fetch(`/api/research-jobs/${encodeURIComponent(activeJobId)}`);
    if (!response.ok) throw new Error("无法读取任务状态");
    const job = await response.json();
    workspace.hidden = false;
    if (!renderJob(job)) {
      const advance = await fetch(`/api/research-jobs/${encodeURIComponent(activeJobId)}/advance`, { method: "POST" });
      if (!advance.ok) {
        const details = await advance.json().catch(() => ({}));
        throw new Error(details.error || "无法继续调研步骤");
      }
      renderJob(await advance.json());
      pollTimer = window.setTimeout(pollJob, 700);
    }
  } catch (problem) {
    jobMessage.textContent = `${problem.message}，正在重试。`;
    pollTimer = window.setTimeout(pollJob, 3000);
  }
}

cancelButton.addEventListener("click", async () => {
  if (!activeJobId) return;
  cancelButton.disabled = true;
  try { await fetch(`/api/research-jobs/${encodeURIComponent(activeJobId)}/cancel`, { method: "POST" }); }
  finally { cancelButton.disabled = false; pollJob(); }
});

if (activeJobId) pollJob();
