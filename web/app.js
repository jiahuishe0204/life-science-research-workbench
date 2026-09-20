const form = document.querySelector("#research-form");
const topic = document.querySelector("#topic");
const count = document.querySelector("#topic-count");
const error = document.querySelector("#topic-error");
const submit = document.querySelector("#submit-button");
const workspace = document.querySelector("#workspace");
const workspaceTopic = document.querySelector("#workspace-topic");

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

  submit.disabled = true;
  workspaceTopic.textContent = normalizedTopic();
  workspace.hidden = false;
  workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => { submit.disabled = false; }, 700);
});
