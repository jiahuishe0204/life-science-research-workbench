import { readFileSync } from "node:fs";
import { classifyOfficialUrl, officialDirectoryEntries } from "../cloud-functions/lib/official-sources.js";

function require(value, message) { if (!value) throw new Error(message); }
const positive = [
  ["https://www.who.int/health-topics", "who"],
  ["https://www.fda.gov/drugs", "us_fda"],
  ["https://clinicaltrials.gov/study/NCT00000000", "clinicaltrials_gov"],
  ["https://www.gov.uk/drug-safety-update/example", "uk_mhra"]
];
for (const [url, id] of positive) require(classifyOfficialUrl(url)?.id === id, `positive URL failed: ${url}`);
for (const url of ["http://www.who.int/", "https://who.int.evil.example/", "https://user:pass@who.int/", "https://who.int:8443/", "https://www.gov.uk/news"]) require(classifyOfficialUrl(url) === null, `negative URL allowed: ${url}`);
require(classifyOfficialUrl("https://www.who.int/") && !classifyOfficialUrl("https://example.com/redirect-target"), "redirect target must be revalidated independently");
const entries = officialDirectoryEntries("药物批准与诊断器械监管");
require(entries.length >= 3 && entries.every((row) => row.read_scope === "official_directory_entry_only" && row.allowed_uses.length && row.limitations), "official directory metadata is incomplete");
const backend = readFileSync(new URL("../cloud-functions/api/[[default]].js", import.meta.url), "utf8");
const frontend = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
require(backend.includes("NOT READ") && backend.includes("must never support factual claims"), "unsupported-claim guard is missing");
require(backend.includes('path === "/api/official-sources/classify"') && backend.includes("redirect_revalidated"), "runtime classification route is missing");
require(frontend.includes("仅为官方入口，未读取页面内容"), "official source disclosure is missing from UI");
console.log("official source runtime validation: PASS");
