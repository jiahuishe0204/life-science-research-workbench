const RULES = [
  ["cn_nmpa", "国家药品监督管理局", "regulator", ["nmpa.gov.cn"], ["approval_status", "safety_notice", "recall", "regulatory_guidance"], "仅证明中国监管范围内的官方公开状态，不替代论文证据。"],
  ["cn_nhc", "中华人民共和国国家卫生健康委员会", "public_health_authority", ["nhc.gov.cn"], ["official_standard", "public_health_guidance", "policy", "statistics"], "须区分正式标准、政策和一般新闻。"],
  ["cn_cdc", "中国疾病预防控制中心", "public_health_authority", ["chinacdc.cn"], ["surveillance", "public_health_guidance", "risk_assessment"], "机构动态只作线索，科学结论须回到报告或论文。"],
  ["who", "World Health Organization", "public_health_authority", ["who.int"], ["fact_sheet", "guideline", "disease_outbreak", "global_health_statistics", "policy"], "全球建议不自动等同于本地监管要求。"],
  ["us_fda", "U.S. Food and Drug Administration", "regulator", ["fda.gov"], ["approval_status", "label", "safety_notice", "recall", "regulatory_guidance"], "仅代表美国监管范围。"],
  ["eu_ema", "European Medicines Agency", "regulator", ["ema.europa.eu"], ["evaluation_status", "medicine_information", "safety_notice", "regulatory_guidance"], "成员国批准仍须查看国家登记。"],
  ["eu_health", "European Commission Health", "regulator", ["health.ec.europa.eu"], ["union_register", "legislation", "regulatory_policy"], "须区分法规、决定、提案和新闻。"],
  ["jp_pmda", "Pharmaceuticals and Medical Devices Agency", "regulator", ["pmda.go.jp"], ["review_report", "safety_notice", "label", "regulatory_guidance"], "英文页面可能不是最新完整版本。"],
  ["us_cdc", "U.S. Centers for Disease Control and Prevention", "public_health_authority", ["cdc.gov"], ["surveillance", "outbreak", "public_health_guidance", "statistics"], "美国建议不自动适用于其他地区。"],
  ["eu_ecdc", "European Centre for Disease Prevention and Control", "public_health_authority", ["ecdc.europa.eu"], ["surveillance", "threat_assessment", "public_health_guidance", "statistics"], "适用范围以欧盟／欧洲经济区说明为准。"],
  ["clinicaltrials_gov", "ClinicalTrials.gov", "registry", ["clinicaltrials.gov"], ["trial_registration", "trial_status", "posted_results"], "登记、完成或发布结果均不等于结果可靠或产品获批。"],
  ["us_nih", "U.S. National Institutes of Health", "research_institution", ["nih.gov"], ["institutional_update", "research_program", "funding_announcement"], "科研新闻只作为线索或机构声明。"],
  ["cn_cas", "中国科学院", "research_institution", ["cas.cn"], ["institutional_update", "research_program", "research_discovery"], "科研进展新闻只作线索，结论须回到论文或数据。"]
].map(([id, name, tier, domains, allowed_uses, limitations]) => ({ id, name, tier, domains, allowed_uses, limitations, allow_subdomains: true }));
RULES.push({ id: "uk_mhra", name: "UK MHRA", tier: "regulator", domains: ["gov.uk"], allow_subdomains: true, allowed_path_prefixes: ["/government/organisations/medicines-and-healthcare-products-regulatory-agency", "/drug-safety-update", "/guidance/find-product-information-about-medicines"], allowed_uses: ["approval_status", "safety_notice", "recall", "regulatory_guidance"], limitations: "gov.uk 仅放行列出的 MHRA 路径。" });

export function classifyOfficialUrl(value) {
  let url; try { url = new URL(value); } catch { return null; }
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) return null;
  const host = url.hostname.toLowerCase().replace(/\.$/, ""), path = url.pathname || "/";
  for (const rule of RULES) {
    const hostMatch = rule.domains.some((domain) => host === domain || (rule.allow_subdomains && host.endsWith(`.${domain}`)));
    if (!hostMatch || (rule.allowed_path_prefixes && !rule.allowed_path_prefixes.some((prefix) => path.startsWith(prefix)))) continue;
    return { id: rule.id, name: rule.name, tier: rule.tier, allowed_uses: rule.allowed_uses, limitations: rule.limitations };
  }
  return null;
}

export function officialDirectoryEntries(topic) {
  const ids = new Set(["who", "clinicaltrials_gov"]);
  if (/监管|批准|上市|药物|器械|诊断|regulat|approv|drug|device/i.test(topic)) ["cn_nmpa", "us_fda", "eu_ema"].forEach((id) => ids.add(id));
  if (/疫情|公共卫生|流行病|传染|outbreak|public health|epidemi/i.test(topic)) ["cn_nhc", "cn_cdc", "us_cdc", "eu_ecdc"].forEach((id) => ids.add(id));
  return RULES.filter((rule) => ids.has(rule.id)).slice(0, 5).map((rule) => ({
    provider: rule.name, title: `${rule.name} 官方资料入口`, url: `https://www.${rule.domains[0]}/`, doi: "", abstract: "",
    published: "", read_scope: "official_directory_entry_only", source_type: rule.tier,
    allowed_uses: rule.allowed_uses, limitations: rule.limitations, official_source_id: rule.id,
    crossref_validated: false
  }));
}
