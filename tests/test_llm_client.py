import copy
import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from app.services.llm_client import GeminiClient, _extract_json_object


SUITE = {
    "api_test_cases": [{
        "id": "API-HEALTH-001", "title": "Health check succeeds", "api_method": "GET",
        "endpoint": "/health", "priority": "high", "test_type": "positive",
        "prerequisites": [], "request_data": {}, "steps": ["GET /health"],
        "expected_result": "Returns a healthy status", "expected_status_code": 200,
    }],
    "unit_test_cases": [],
}


def response_body(text=None, finish_reason="STOP", parts=None):
    if parts is None:
        parts = [{"text": text if text is not None else json.dumps(SUITE)}]
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish_reason}]}


class GeminiResponseTests(unittest.TestCase):
    def setUp(self):
        self.client = GeminiClient(api_key="test-key", model="gemini-2.5-flash", max_output_tokens=32768)
        self.post = self.enterContext(patch.object(self.client, "_request"))

    def test_valid_answer_uses_a_schema_and_explicit_output_budget(self):
        self.post.return_value = response_body()
        self.assertEqual(self.client.generate_json("Generate health tests"), SUITE)
        self.assertEqual(self.post.call_count, 1)
        config = self.post.call_args.args[0]["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["maxOutputTokens"], 32768)
        self.assertEqual(config["responseJsonSchema"]["required"], ["api_test_cases", "unit_test_cases", "unit_test_code"])
        self.assertEqual(config["thinkingConfig"], {"thinkingBudget": 1024})
        self.assertTrue(config["responseJsonSchema"]["properties"]["api_test_cases"]["items"]["properties"]["request_data"]["additionalProperties"])

    def test_other_model_families_do_not_receive_unsupported_thinking_config(self):
        self.client.model = "gemini-2.0-flash"
        self.post.return_value = response_body()
        self.client.generate_json("Generate tests")
        self.assertNotIn("thinkingConfig", self.post.call_args.args[0]["generationConfig"])

    def test_all_answer_parts_are_combined_and_thoughts_are_skipped(self):
        text = json.dumps(SUITE)
        self.post.return_value = response_body(parts=[
            {"text": "Thinking summary, not JSON", "thought": True},
            {"text": text[:30]}, {"inlineData": {}}, {"text": text[30:]},
        ])
        self.assertEqual(self.client.generate_json("Generate tests"), SUITE)
        self.assertEqual(self.post.call_count, 1)

    def test_truncated_generation_is_retried_as_a_complete_suite(self):
        self.post.side_effect = [response_body('{"api_test_cases":[{"id":"API-001"}', "MAX_TOKENS"), response_body()]
        self.assertEqual(self.client.generate_json("Generate tests"), SUITE)
        self.assertEqual(self.post.call_count, 2)
        self.assertIn("complete JSON object", self.post.call_args.args[0]["contents"][0]["parts"][-1]["text"])

    def test_persistent_truncation_has_an_actionable_error_and_no_partial_result(self):
        # Even syntactically valid JSON cannot be trusted when Gemini says it
        # stopped at its output limit: it may omit the remaining test cases.
        self.post.return_value = response_body(finish_reason="MAX_TOKENS")
        with self.assertRaisesRegex(RuntimeError, "output limit.*GEMINI_MAX_OUTPUT_TOKENS"):
            self.client.generate_json("Generate tests")
        self.assertEqual(self.post.call_count, 2)

    def test_malformed_json_is_retried_once(self):
        self.post.side_effect = [response_body('{"api_test_cases": invalid}'), response_body()]
        self.assertEqual(self.client.generate_json("Generate tests"), SUITE)
        self.assertEqual(self.post.call_count, 2)

    def test_missing_response_shapes_retry_without_crashing(self):
        for invalid in [None, [], {}, {"candidates": []}, {"candidates": [None]}, response_body(parts=[]), response_body(parts=[{"text": None}]), response_body(parts=[{"text": "Only a thought", "thought": True}]), response_body('{"message":"No cases"}')]:
            with self.subTest(body=invalid):
                self.post.reset_mock()
                self.post.side_effect = [invalid, response_body()]
                self.assertEqual(self.client.generate_json("Generate tests"), SUITE)
                self.assertEqual(self.post.call_count, 2)

    def test_repeated_malformed_output_has_a_clear_error(self):
        self.post.return_value = response_body("not JSON")
        with self.assertRaisesRegex(RuntimeError, "malformed test-suite JSON"):
            self.client.generate_json("Generate tests")
        self.assertEqual(self.post.call_count, 2)

    def test_blocked_prompts_are_reported_without_retrying(self):
        self.post.return_value = {"promptFeedback": {"blockReason": "SAFETY"}}
        with self.assertRaisesRegex(RuntimeError, "blocked this request.*SAFETY"):
            self.client.generate_json("Generate tests")
        self.assertEqual(self.post.call_count, 1)

    def test_blocked_candidates_are_not_parsed_or_retried(self):
        for reason in ["SAFETY", "RECITATION", "PROHIBITED_CONTENT"]:
            with self.subTest(reason=reason):
                self.post.reset_mock()
                self.post.return_value = response_body(finish_reason=reason)
                with self.assertRaisesRegex(RuntimeError, reason):
                    self.client.generate_json("Generate tests")
                self.assertEqual(self.post.call_count, 1)

    def test_missing_key_does_not_call_the_api(self):
        self.client.api_key = ""
        with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
            self.client.generate_json("Generate tests")
        self.post.assert_not_called()


class JsonExtractionTests(unittest.TestCase):
    def test_json_fences_bom_and_surrounding_text(self):
        encoded = json.dumps(SUITE)
        for text in [encoded, f"```json\n{encoded}\n```", f"\ufeff {encoded}", f"Here are your cases:\n{encoded}\nDone ({{note}})."]:
            with self.subTest(text=text):
                self.assertEqual(_extract_json_object(text), SUITE)

    def test_braces_inside_json_strings_are_preserved(self):
        suite = copy.deepcopy(SUITE)
        suite["api_test_cases"][0]["expected_result"] = 'A value like {"status": "ok"} is returned'
        self.assertEqual(_extract_json_object(json.dumps(suite)), suite)

    def test_truncated_nested_objects_and_non_objects_are_rejected(self):
        for text in ['{"api_test_cases":[{"id":"complete-inner-object"}', '[]', '[{"api_test_cases": []}]', '"text"', 'null', 'not JSON']:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    _extract_json_object(text)


class GeminiTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")
        self.urlopen = self.enterContext(patch("app.services.llm_client.urlopen"))
        self.sleep = self.enterContext(patch("app.services.llm_client.time.sleep"))
        self.response = MagicMock()
        self.response.__enter__.return_value.read.return_value = json.dumps(response_body()).encode()

    def test_api_key_is_in_a_header_and_not_the_url(self):
        self.urlopen.return_value = self.response
        self.assertEqual(self.client.generate_json("Generate tests"), SUITE)
        request = self.urlopen.call_args.args[0]
        self.assertNotIn("test-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        self.assertEqual(json.loads(request.data)["generationConfig"]["responseMimeType"], "application/json")

    def test_transient_http_failures_retry(self):
        failure = HTTPError("https://example.com", 503, "Unavailable", {}, io.BytesIO(b"unavailable"))
        self.urlopen.side_effect = [failure, self.response]
        self.assertEqual(self.client.generate_json("Generate tests"), SUITE)
        self.assertEqual(self.urlopen.call_count, 2)
        self.sleep.assert_called_once_with(1)

    def test_permanent_http_errors_do_not_retry(self):
        self.urlopen.side_effect = HTTPError("https://example.com", 400, "Bad Request", {}, io.BytesIO(b"bad schema"))
        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            self.client.generate_json("Generate tests")
        self.assertEqual(self.urlopen.call_count, 1)

    def test_network_retries_are_bounded(self):
        self.urlopen.side_effect = URLError("connection refused")
        with self.assertRaisesRegex(RuntimeError, "Could not connect"):
            self.client.generate_json("Generate tests")
        self.assertEqual(self.urlopen.call_count, 3)


if __name__ == "__main__":
    unittest.main()
