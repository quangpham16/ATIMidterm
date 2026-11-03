import json
import re
import time
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import (
    GEMINI_API_KEY,
    GEMINI_API_URL,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
    GEMINI_TIMEOUT_SECONDS,
)
from app.schemas import TestCase


# Keep the model's output contract in sync with the cases the generator accepts.
_CASE_SCHEMA = TestCase.model_json_schema()
_CASE_SCHEMA["required"] = list(_CASE_SCHEMA["properties"])
TEST_SUITE_SCHEMA = {
    "type": "object",
    "properties": {
        "api_test_cases": {"type": "array", "items": _CASE_SCHEMA},
        "unit_test_cases": {"type": "array", "items": _CASE_SCHEMA},
        "unit_test_code": {"type": "string", "description": "Runnable unit tests for the provided source code, or an empty string when no source was provided."},
    },
    "required": ["api_test_cases", "unit_test_cases", "unit_test_code"],
}


class _InvalidGeneration(RuntimeError):
    """A missing, malformed, or truncated answer that can be generated again."""


class GeminiClient:
    def __init__(
        self,
        api_key: str = GEMINI_API_KEY,
        model: str = GEMINI_MODEL,
        max_output_tokens: int = GEMINI_MAX_OUTPUT_TOKENS,
    ):
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens

    def generate_json(self, prompt: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": TEST_SUITE_SCHEMA,
                "maxOutputTokens": self.max_output_tokens,
            },
        }
        # Bound Gemini 2.5's reasoning so it leaves room for the JSON answer.
        # Other model families have different thinking configuration support.
        if self.model.startswith("gemini-2.5-"):
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 1024}

        for attempt in range(2):
            body = self._request(payload)
            try:
                return _parse_generation(body)
            except _InvalidGeneration:
                if attempt == 1:
                    raise
                # Regenerate a complete answer; never save a salvaged partial suite.
                payload["contents"][0]["parts"].append({
                    "text": (
                        "The previous attempt did not produce a complete test-suite JSON object. "
                        "Generate it again from the supplied specification and code. "
                        "Keep titles, steps and descriptions concise, avoid duplicate cases, "
                        "and finish both api_test_cases and unit_test_cases arrays within the "
                        "output budget. Return only the complete JSON object."
                    )
                })

    def _request(self, payload: dict[str, Any]) -> Any:
        url = GEMINI_API_URL.format(model=quote(self.model, safe=""))
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=GEMINI_TIMEOUT_SECONDS) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:1000]
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"Gemini API returned HTTP {exc.code}: {detail}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"Could not connect to Gemini API: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError("Gemini returned invalid JSON") from exc


def _parse_generation(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise _InvalidGeneration("Gemini returned an invalid response. Please try generating again.")
    feedback = body.get("promptFeedback") or {}
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        raise RuntimeError(f"Gemini blocked this request ({feedback['blockReason']}). Review the supplied input.")
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise _InvalidGeneration("Gemini returned no response candidates. Please try generating again.")
    candidate = candidates[0]
    finish_reason = candidate.get("finishReason")
    if finish_reason == "MAX_TOKENS":
        raise _InvalidGeneration(
            "Gemini reached its output limit before completing the test suite. "
            "Generate fewer operations at a time or increase GEMINI_MAX_OUTPUT_TOKENS."
        )
    if finish_reason not in (None, "STOP", "FINISH_REASON_UNSPECIFIED"):
        raise RuntimeError(f"Gemini could not complete the test suite ({finish_reason}). Review the supplied input and try again.")
    content = candidate.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise _InvalidGeneration("Gemini returned no generated text. Please try generating again.")
    # Responses may contain a thought summary before the answer, and the JSON
    # answer itself may span several text parts.
    text = "".join(
        part["text"] for part in parts
        if isinstance(part, dict) and not part.get("thought") and isinstance(part.get("text"), str)
    )
    if not text.strip():
        raise _InvalidGeneration("Gemini returned no generated text. Please try generating again.")
    try:
        result = _extract_json_object(text)
    except ValueError as exc:
        raise _InvalidGeneration("Gemini returned malformed test-suite JSON after generation. Please try generating again.") from exc
    if not any(isinstance(result.get(key), list) for key in ("api_test_cases", "unit_test_cases", "test_cases")):
        raise _InvalidGeneration("Gemini returned JSON without test-case arrays. Please try generating again.")
    return result


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse JSON even when the model adds a markdown fence or short preface."""
    cleaned = text.strip().lstrip("\ufeff").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Decode only the first root object, rather than greedily consuming
        # braces in commentary or accidentally accepting an inner object from
        # an incomplete response. Never repair or truncate test-case data.
        start = cleaned.find("{")
        if start < 0 or "[" in cleaned[:start]:
            raise ValueError("No JSON object found in Gemini response") from None
        try:
            parsed, _ = json.JSONDecoder().raw_decode(cleaned, start)
        except json.JSONDecodeError as exc:
            raise ValueError("Incomplete or malformed JSON object in Gemini response") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Gemini response must be a JSON object")
    return parsed
