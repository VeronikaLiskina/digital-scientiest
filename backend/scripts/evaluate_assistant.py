"""Repeatable HTTP checks against a running assistant (no model training).

Catalog cases run by default. --include-generation explicitly enables cases
that send questions and retrieved publication excerpts to the configured API.
Only temporary evaluation chats are created and deleted; publications are read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AssistantClient:
    def __init__(self, base_url: str, timeout: float = 240):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict | None = None) -> Any:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(self.base_url + path, data=data, method=method,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=self.timeout) as response:
            body = response.read()
            return json.loads(body) if body else None


def check_response(case: dict, response: dict) -> list[str]:
    """Check routing, evidence IDs and known answer facts; not a semantic judge."""
    failures = []
    if response.get("answer_origin") != case["origin"]:
        failures.append(f"origin: expected {case['origin']}, got {response.get('answer_origin')}")
    catalog = response.get("catalog") or {}
    ids = {item["publication_id"] for item in catalog.get("items", [])}
    sources = response.get("sources", [])
    if case.get("source_publications"):
        ids = {source["publication_id"] for source in sources}
        if not ids.intersection(case["source_publications"]):
            failures.append("expected publication missing from answer citations")
    if not set(case.get("include_publications", [])) <= ids:
        failures.append("expected publication missing from catalog")
    if set(case.get("exclude_publications", [])) & ids:
        failures.append("excluded publication present in catalog")
    if "total" in case and catalog.get("total") != case["total"]:
        failures.append(f"total: expected {case['total']}, got {catalog.get('total')}")
    for item in catalog.get("items", []):
        year = item.get("year")
        if "year_from" in case and (year is None or year < case["year_from"]):
            failures.append("publication outside lower year boundary")
        if "year_to" in case and (year is None or year > case["year_to"]):
            failures.append("publication outside upper year boundary")
        if case.get("descriptions") and not item.get("description"):
            failures.append("description missing")
    answer = response.get("answer", response.get("content", ""))
    for pattern in case.get("answer_patterns", []):
        if not re.search(pattern, answer, re.I):
            failures.append(f"expected fact missing: {pattern}")
    for pattern in case.get("forbidden_patterns", []):
        if re.search(pattern, answer, re.I):
            failures.append(f"unacceptable wording: {pattern}")
    source_ids = {source["source_id"] for source in sources}
    cited = {source_id for block in response.get("answer_blocks", []) for source_id in block.get("source_ids", [])}
    if cited != source_ids:
        failures.append("answer blocks and source list disagree")
    if case.get("no_sources") and sources:
        failures.append("unexpected sources for an unanswerable question")
    if not answer.strip():
        failures.append("empty answer")
    return list(dict.fromkeys(failures))


def run_case(client: AssistantClient, case: dict) -> dict:
    started = time.perf_counter()
    chat_id = None
    mode = case.get("mode", "auto")
    result = {"id": case["id"], "category": case["category"], "question": case["question"]}
    try:
        if case.get("history"):
            chat_id = client.request("POST", "/assistant/chats", {"title": "Проверка ассистента"})["id"]
            for content in case["history"]:
                previous = client.request("POST", f"/assistant/chats/{chat_id}/messages", {"content": content, "mode": mode})["assistant_message"]
            if case.get("count_from_history"):
                case = {**case, "answer_patterns": [rf"\b{previous['catalog']['total']}\b"]}
            response = client.request("POST", f"/assistant/chats/{chat_id}/messages", {"content": case["question"], "mode": mode})["assistant_message"]
        else:
            response = client.request("POST", "/assistant/ask", {"question": case["question"], "mode": mode})
        result.update(response=response, failures=check_response(case, response))
    except HTTPError as exc:
        # Do not persist arbitrary server bodies or prompts from provider errors.
        try:
            code = json.loads(exc.read()).get("detail", {}).get("code", "http_error")
        except (ValueError, AttributeError):
            code = "http_error"
        result["failures"] = [f"HTTP {exc.code}: {code}"]
    except (URLError, TimeoutError, OSError) as exc:
        result["failures"] = [f"connection failed: {type(exc).__name__}"]
    finally:
        if chat_id is not None:
            try:
                client.request("DELETE", f"/assistant/chats/{chat_id}")
            except (HTTPError, URLError, TimeoutError, OSError):
                result.setdefault("failures", []).append(f"temporary chat {chat_id} could not be removed")
    result["seconds"] = round(time.perf_counter() - started, 3)
    result["passed"] = not result["failures"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parents[1] / "evaluation/assistant_cases.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-generation", action="store_true")
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()
    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    selected = [case for case in cases if (args.include_generation or not case.get("generation"))
                and (not args.ids or case["id"] in args.ids)]
    if not selected:
        parser.error("No cases selected")
    client = AssistantClient(args.base_url)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "dataset": str(args.dataset),
              "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
              "include_generation": args.include_generation, "results": []}
    client.request("GET", "/health")
    publications = client.request("GET", "/api/publications")
    report["corpus"] = {"publications": len(publications),
                        "statuses": dict(Counter(row["status"] for row in publications)),
                        "metadata_sha256": hashlib.sha256(json.dumps(publications, sort_keys=True).encode()).hexdigest()}
    for case in selected:
        result = run_case(client, case)
        report["results"].append(result)
        report["summary"] = {"cases": len(report["results"]),
                             "passed": sum(row["passed"] for row in report["results"]),
                             "failures_by_category": dict(Counter(row["category"] for row in report["results"] if not row["passed"]))}
        # Save each result so interrupted long checks remain inspectable.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{'PASS' if result['passed'] else 'FAIL'} {result['id']} {result['seconds']}s "
              + "; ".join(result["failures"]), flush=True)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return int(report["summary"]["passed"] != len(selected))


if __name__ == "__main__":
    raise SystemExit(main())
