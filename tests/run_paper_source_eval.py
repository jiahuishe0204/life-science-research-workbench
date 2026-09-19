#!/usr/bin/env python3
"""Run a small, reproducible comparison of PubMed, Europe PMC, and Crossref."""

from __future__ import annotations

import argparse
import http.client
import json
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUERIES = ROOT / "tests/fixtures/paper-source-queries.json"
USER_AGENT = "life-science-research-workbench/0.1 (https://github.com/jiahuishe0204/life-science-research-workbench)"


def request(url: str, *, accept: str, pause: float = 0.4, attempts: int = 4) -> tuple[bytes, dict[str, str], float, int]:
    started = time.perf_counter()
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read()
                headers = {key.lower(): value for key, value in response.headers.items()}
                status = response.status
            time.sleep(pause)
            return body, headers, round(time.perf_counter() - started, 3), status
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts:
                raise RuntimeError(f"HTTP {exc.code} for {url}: {body[:300]!r}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.RemoteDisconnected):
            if attempt == attempts:
                raise
        time.sleep(max(pause, 2 ** (attempt - 1)))
    raise RuntimeError("unreachable")


def first_text(node: ET.Element | None, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(path)
    if found is None:
        return None
    text = "".join(found.itertext()).strip()
    return text or None


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value or None


def normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\W+", "", value, flags=re.UNICODE).lower() or None


def pubmed(query: str, date_from: str, date_to: str, rows: int) -> dict[str, Any]:
    tokens = [token for token in re.findall(r"[A-Za-z0-9-]+", query) if token]
    fielded_query = " AND ".join(f'"{token}"[Title/Abstract]' for token in tokens)
    term = f'({fielded_query}) AND {date_from.replace("-", "/")}:{date_to.replace("-", "/")}[Date - Publication]'
    search_params = urllib.parse.urlencode({
        "db": "pubmed", "term": term, "retmode": "json", "retmax": rows,
        "sort": "relevance", "tool": "life_science_research_workbench",
    })
    search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{search_params}"
    body, headers, search_latency, status = request(search_url, accept="application/json")
    search = json.loads(body)["esearchresult"]
    ids = search.get("idlist", [])
    records: list[dict[str, Any]] = []
    fetch_latency = 0.0
    if ids:
        fetch_params = urllib.parse.urlencode({
            "db": "pubmed", "id": ",".join(ids), "retmode": "xml",
            "rettype": "abstract", "tool": "life_science_research_workbench",
        })
        fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{fetch_params}"
        xml_body, _, fetch_latency, _ = request(fetch_url, accept="application/xml")
        root = ET.fromstring(xml_body)
        for article in root.findall(".//PubmedArticle"):
            medline = article.find("MedlineCitation")
            article_node = article.find(".//Article")
            doi = None
            pmcid = None
            for identifier in article.findall(".//ArticleId"):
                if identifier.attrib.get("IdType") == "doi":
                    doi = normalize_doi(identifier.text)
                elif identifier.attrib.get("IdType") == "pmc":
                    pmcid = identifier.text
            authors = article.findall(".//Author")
            abstract_parts = ["".join(item.itertext()).strip() for item in article.findall(".//AbstractText")]
            pub_date = article.find(".//JournalIssue/PubDate")
            year = first_text(pub_date, "Year") or first_text(pub_date, "MedlineDate")
            pmid = first_text(medline, "PMID")
            records.append({
                "id": pmid,
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "title": first_text(article_node, "ArticleTitle"),
                "abstract": " ".join(part for part in abstract_parts if part) or None,
                "authors_count": len(authors),
                "year": year,
                "journal": first_text(article_node, "Journal/Title"),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            })
    return {
        "source": "pubmed", "status": status, "total_hits": int(search.get("count", 0)),
        "query_translation": search.get("querytranslation"), "latency_seconds": round(search_latency + fetch_latency, 3),
        "response_headers": {k: headers[k] for k in headers if k.startswith("x-rate") or k == "retry-after"},
        "records": records,
    }


def europe_pmc(query: str, date_from: str, date_to: str, rows: int) -> dict[str, Any]:
    tokens = [token for token in re.findall(r"[A-Za-z0-9-]+", query) if token]
    expression = f'({" AND ".join(tokens)}) AND FIRST_PDATE:[{date_from} TO {date_to}]'
    params = urllib.parse.urlencode({
        "query": expression, "format": "json", "pageSize": rows,
        "resultType": "core",
    })
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}"
    body, headers, latency, status = request(url, accept="application/json")
    data = json.loads(body)
    records = []
    for item in data.get("resultList", {}).get("result", []):
        records.append({
            "id": item.get("id"),
            "pmid": item.get("pmid"),
            "pmcid": item.get("pmcid"),
            "doi": normalize_doi(item.get("doi")),
            "title": item.get("title"),
            "abstract": item.get("abstractText"),
            "authors_count": len(item.get("authorList", {}).get("author", [])),
            "year": item.get("pubYear"),
            "journal": item.get("journalTitle") or item.get("journalInfo", {}).get("journal", {}).get("title"),
            "cited_by_count": item.get("citedByCount"),
            "is_open_access": item.get("isOpenAccess") == "Y",
            "has_full_text": item.get("inEPMC") == "Y" or item.get("inPMC") == "Y",
            "url": f"https://europepmc.org/article/{item.get('source')}/{item.get('id')}",
        })
    return {
        "source": "europe_pmc", "status": status, "total_hits": int(data.get("hitCount", 0)),
        "request_query": data.get("request", {}).get("queryString"), "latency_seconds": latency,
        "response_headers": {k: headers[k] for k in headers if k.startswith("x-rate") or k == "retry-after"},
        "records": records,
    }


def crossref(query: str, date_from: str, date_to: str, rows: int) -> dict[str, Any]:
    params = urllib.parse.urlencode({
        "query.bibliographic": query,
        "filter": f"from-pub-date:{date_from},until-pub-date:{date_to},type:journal-article",
        "rows": rows,
        "select": "DOI,title,author,published,container-title,abstract,URL,ISSN,subject,type",
    })
    url = f"https://api.crossref.org/works?{params}"
    body, headers, latency, status = request(url, accept="application/json")
    message = json.loads(body)["message"]
    records = []
    for item in message.get("items", []):
        date_parts = item.get("published", {}).get("date-parts", [[]])
        year = date_parts[0][0] if date_parts and date_parts[0] else None
        title = item.get("title", [])
        container = item.get("container-title", [])
        records.append({
            "id": normalize_doi(item.get("DOI")),
            "doi": normalize_doi(item.get("DOI")),
            "title": title[0] if title else None,
            "abstract": item.get("abstract"),
            "authors_count": len(item.get("author", [])),
            "year": year,
            "journal": container[0] if container else None,
            "url": item.get("URL"),
        })
    return {
        "source": "crossref", "status": status, "total_hits": int(message.get("total-results", 0)),
        "latency_seconds": latency,
        "response_headers": {k: headers[k] for k in headers if k.startswith("x-rate") or k in {"retry-after", "x-concurrency-limit", "x-api-pool"}},
        "records": records,
    }


def metrics(result: dict[str, Any]) -> dict[str, Any]:
    records = result["records"]
    count = len(records)
    field = lambda name: sum(bool(record.get(name)) for record in records)
    dois = [record["doi"] for record in records if record.get("doi")]
    titles = [normalize_title(record.get("title")) for record in records if normalize_title(record.get("title"))]
    return {
        "total_hits": result["total_hits"],
        "returned": count,
        "latency_seconds": result["latency_seconds"],
        "doi_present": field("doi"),
        "abstract_present": field("abstract"),
        "authors_present": sum(record.get("authors_count", 0) > 0 for record in records),
        "year_present": field("year"),
        "journal_present": field("journal"),
        "url_present": field("url"),
        "open_access": sum(record.get("is_open_access", False) for record in records),
        "full_text_signal": sum(record.get("has_full_text", False) for record in records),
        "duplicate_doi": len(dois) - len(set(dois)),
        "duplicate_title": len(titles) - len(set(titles)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.queries.read_text(encoding="utf-8"))
    output = args.output or ROOT / "artifacts/paper-source-eval" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True, exist_ok=True)

    all_results: list[dict[str, Any]] = []
    source_functions = [("pubmed", pubmed), ("europe_pmc", europe_pmc), ("crossref", crossref)]
    for query in config["queries"]:
        query_results: dict[str, Any] = {"query": query, "sources": {}}
        for source_name, function in source_functions:
            result = function(query["query"], config["date_from"], config["date_to"], config["rows"])
            query_results["sources"][source_name] = result
        doi_sets = {
            source: {record["doi"] for record in result["records"] if record.get("doi")}
            for source, result in query_results["sources"].items()
        }
        query_results["top_result_doi_overlap"] = {
            "pubmed_europe_pmc": len(doi_sets["pubmed"] & doi_sets["europe_pmc"]),
            "pubmed_crossref": len(doi_sets["pubmed"] & doi_sets["crossref"]),
            "europe_pmc_crossref": len(doi_sets["europe_pmc"] & doi_sets["crossref"]),
        }
        (output / f"{query['id']}.json").write_text(json.dumps(query_results, ensure_ascii=False, indent=2), encoding="utf-8")
        all_results.append(query_results)

    summary_queries = []
    for result in all_results:
        summary_queries.append({
            "query": result["query"],
            "metrics": {source: metrics(data) for source, data in result["sources"].items()},
            "top_result_doi_overlap": result["top_result_doi_overlap"],
        })
    aggregate: dict[str, Any] = {}
    for source, _ in source_functions:
        source_metrics = [item["metrics"][source] for item in summary_queries]
        aggregate[source] = {
            "queries_ok": sum(item["returned"] > 0 for item in source_metrics),
            "records_returned": sum(item["returned"] for item in source_metrics),
            "median_latency_seconds": round(statistics.median(item["latency_seconds"] for item in source_metrics), 3),
            "doi_present": sum(item["doi_present"] for item in source_metrics),
            "abstract_present": sum(item["abstract_present"] for item in source_metrics),
            "authors_present": sum(item["authors_present"] for item in source_metrics),
            "year_present": sum(item["year_present"] for item in source_metrics),
            "journal_present": sum(item["journal_present"] for item in source_metrics),
            "url_present": sum(item["url_present"] for item in source_metrics),
            "open_access": sum(item["open_access"] for item in source_metrics),
            "full_text_signal": sum(item["full_text_signal"] for item in source_metrics),
            "duplicate_doi": sum(item["duplicate_doi"] for item in source_metrics),
            "duplicate_title": sum(item["duplicate_title"] for item in source_metrics),
        }
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": config,
        "aggregate": aggregate,
        "queries": summary_queries,
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
