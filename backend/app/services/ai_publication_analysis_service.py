import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.ai_publication_analysis import AIPublicationAnalysisResponse
from app.services.prompt_builder import build_publication_analysis_prompt


PUBLICATION_ANALYSIS_SYSTEM_PROMPT = (
    "You extract metadata from scientific publication text. "
    "Return only valid JSON that matches the requested schema. "
    "Do not invent data that is not present in the text."
)


def _extract_json_object(raw_response: str) -> dict[str, Any] | None:
    response = raw_response.strip()
    response = re.sub(r"^```(?:json)?\s*", "", response, flags=re.IGNORECASE)
    response = re.sub(r"\s*```$", "", response)

    start = response.find("{")
    end = response.rfind("}")

    if start == -1 or end == -1 or end <= start:
        return None

    try:
        data = json.loads(response[start:end + 1])
    except json.JSONDecodeError:
        return None

    return data if isinstance(data, dict) else None


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, dict):
        for key in ("value", "title", "name", "text", "evidence"):
            nested_value = value.get(key)

            if nested_value is None:
                continue

            nested_text = _as_str_or_none(nested_value)

            if nested_text:
                return nested_text

        return None

    if isinstance(value, list):
        return None

    value = str(value).strip()
    return value or None


def _as_int_or_none(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("value", "year", "text", "evidence"):
            year = _as_int_or_none(value.get(key))

            if year is not None:
                return year

        return None

    if value is None or value == "":
        return None

    try:
        year = int(value)
    except (TypeError, ValueError):
        return None

    if 1800 <= year <= 2100:
        return year

    return None


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, dict):
        for key in ("value", "items", "values", "names", "evidence"):
            nested_value = value.get(key)

            if nested_value is None:
                continue

            nested_items = _as_str_list(nested_value)

            if nested_items:
                return nested_items

        return []

    if isinstance(value, str):
        value = [value]

    if not isinstance(value, list):
        return []

    result: list[str] = []
    seen: set[str] = set()

    for item in value:
        text = _as_str_or_none(item)

        if not text:
            continue

        key = text.lower()

        if key in seen:
            continue

        seen.add(key)
        result.append(text)

    return result


def _as_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None

    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None

    if confidence > 1:
        confidence = confidence / 100

    if confidence < 0:
        return 0

    if confidence > 1:
        return 1

    return confidence


def _as_page_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None

    try:
        page = int(value)
    except (TypeError, ValueError):
        return None

    return page if page >= 1 else None


def _normalize_field_metadata(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_metadata = data.get("field_metadata") or data.get("metadata") or {}

    if not isinstance(raw_metadata, dict):
        return {}

    allowed_fields = {
        "title",
        "authors",
        "year",
        "doi",
        "keywords",
    }
    result: dict[str, dict[str, Any]] = {}

    for field_name, raw_value in raw_metadata.items():
        if field_name not in allowed_fields:
            continue

        if isinstance(raw_value, dict):
            raw_confidence = raw_value.get("confidence")
            raw_evidence = raw_value.get("evidence")
            raw_page = raw_value.get("page")
        else:
            raw_confidence = raw_value
            raw_evidence = None
            raw_page = None

        evidence = _as_str_or_none(raw_evidence)

        if evidence is not None and len(evidence) > 500:
            evidence = evidence[:500].rstrip()

        result[field_name] = {
            "confidence": _as_confidence(raw_confidence),
            "evidence": evidence,
            "page": _as_page_or_none(raw_page),
        }

    return result


def _normalize_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _as_str_or_none(data.get("title")),
        "authors": _as_str_list(data.get("authors")),
        "year": _as_int_or_none(data.get("year")),
        "doi": _as_str_or_none(data.get("doi")),
        "keywords": _as_str_list(data.get("keywords")),
        "field_metadata": _normalize_field_metadata(data),
    }


class AIPublicationAnalysisService:
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.ai_publication_analysis_timeout_seconds

    def analyze_text(
        self,
        text: str,
        *,
        filename: str | None = None,
    ) -> AIPublicationAnalysisResponse | None:
        if not settings.ai_publication_analysis_enabled:
            return None

        if not text.strip():
            return None

        prompt = build_publication_analysis_prompt(text, filename=filename)
        raw_response = self._request_ollama(prompt)
        payload = _extract_json_object(raw_response)

        if payload is None:
            return None

        try:
            return AIPublicationAnalysisResponse.model_validate(
                _normalize_payload(payload)
            )
        except ValidationError:
            return None

    def _request_ollama(self, prompt: str) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": PUBLICATION_ANALYSIS_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "options": {
                "temperature": 0,
                "top_p": 0.8,
                "repeat_penalty": 1.05,
            },
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

        data = response.json()
        return str(data.get("message", {}).get("content", ""))


def analyze_publication_text(
    text: str,
    *,
    filename: str | None = None,
) -> AIPublicationAnalysisResponse | None:
    try:
        return AIPublicationAnalysisService().analyze_text(
            text,
            filename=filename,
        )
    except (httpx.HTTPError, RuntimeError, ValueError):
        return None
