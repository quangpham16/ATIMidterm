import json
import os
import unittest
from unittest.mock import patch

import httpx
import pytest

from app.schemas import TestCase as Case
from app.services.api_tests import build_api_pytest_code


class ApiRunnerTests(unittest.TestCase):
    def run_case(self, data=None, endpoint="/users/{id}", method="GET", spec=None, env=None, response=200):
        case = Case(id="API-USER-001", title="User request", api_method=method, endpoint=endpoint,
                    request_data=data or {}, expected_result="Returns the expected status", expected_status_code=200)
        code = build_api_pytest_code([case], spec or {})
        namespace = {}
        exec(compile(code, "test_generated.py", "exec"), namespace)
        self.requests = []
        client_type = httpx.Client
        def respond(request):
            self.requests.append(request)
            return httpx.Response(response, json={"ok": True})
        configured = {"API_BASE_URL": "https://staging.example.test/api/v1", **(env or {})}
        with patch.dict(os.environ, configured, clear=True), patch.object(httpx, "Client", side_effect=lambda **kw: client_type(transport=httpx.MockTransport(respond), **kw)):
            namespace["test_api_api_user_001"]()
        return self.requests[0]

    def test_structured_inputs_reach_the_right_parts_of_the_http_request(self):
        request = self.run_case({"path_params": {"id": "a/b"}, "query_params": {"active": "yes"},
                                 "headers": {"X-Test": "value"}, "body": {"name": "Ada"}}, method="PATCH", env={"API_ALLOW_MUTATIONS": "true"})
        self.assertIn(b"/api/v1/users/a%2Fb?active=yes", request.url.raw_path)
        self.assertEqual(request.headers["x-test"], "value")
        self.assertEqual(json.loads(request.content), {"name": "Ada"})

    def test_flat_legacy_inputs_are_split_using_spec_parameters(self):
        spec = {"paths": {"/users/{id}": {"parameters": [{"name": "id", "in": "path"}], "patch": {"parameters": [{"name": "version", "in": "query"}, {"name": "X-Trace", "in": "header"}]}}}}
        request = self.run_case({"id": 7, "version": 2, "X-Trace": "abc", "name": "Ada"}, method="PATCH", spec=spec, env={"API_ALLOW_MUTATIONS": "true"})
        self.assertEqual(str(request.url), "https://staging.example.test/api/v1/users/7?version=2")
        self.assertEqual(request.headers["x-trace"], "abc")
        self.assertEqual(json.loads(request.content), {"name": "Ada"})

    def test_configured_credentials_are_removed_for_missing_auth_cases(self):
        spec = {"components": {"securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}}}
        request = self.run_case({"auth_mode": "missing"}, spec=spec,
                                env={"API_BEARER_TOKEN": "secret-token", "API_HEADERS_JSON": '{"X-API-Key":"secret-key"}'})
        self.assertNotIn("authorization", request.headers)
        self.assertNotIn("x-api-key", request.headers)

    def test_invalid_auth_overrides_real_credentials(self):
        request = self.run_case({"auth_mode": "invalid"}, env={"API_BEARER_TOKEN": "secret-token"})
        self.assertEqual(request.headers["authorization"], "Bearer invalid-generated-token")

    def test_write_requests_need_explicit_opt_in(self):
        with self.assertRaises(pytest.skip.Exception):
            self.run_case(method="DELETE")
        self.assertEqual(self.requests, [])

    def test_runner_rejects_bad_config_without_sending_requests(self):
        for env in [{"API_BASE_URL": ""}, {"API_BASE_URL": "https://user:password@example.test"},
                    {"API_HEADERS_JSON": "[]"}, {"API_TIMEOUT_SECONDS": "0"}]:
            with self.subTest(env=env), self.assertRaises(pytest.fail.Exception):
                self.run_case(env=env)
            self.assertEqual(self.requests, [])

    def test_actual_status_mismatch_fails(self):
        with self.assertRaisesRegex(AssertionError, "received 500"):
            self.run_case(response=500)

    def test_redirects_are_not_followed(self):
        with self.assertRaisesRegex(AssertionError, "received 302"):
            self.run_case(response=302)
        self.assertEqual(len(self.requests), 1)

    def test_absolute_endpoints_cannot_override_the_configured_server(self):
        for endpoint in ["https://other.test/users", "//other.test/users"]:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                self.run_case(endpoint=endpoint)

    def test_nested_date_placeholders_are_resolved(self):
        request = self.run_case({"body": {"date": "{{today+30d}}", "items": ["{{today-1d}}"]}}, method="POST", env={"API_ALLOW_MUTATIONS": "true"})
        body = json.loads(request.content)
        self.assertRegex(body["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertNotIn("{{", body["items"][0])

    def test_case_ids_that_normalize_to_the_same_name_do_not_drop_tests(self):
        cases = [Case(id=value, title="Health", api_method="GET", endpoint="/health", expected_result="OK", expected_status_code=200)
                 for value in ["A-B", "A_B_2", "A_B", "A_B"]]
        namespace = {}
        exec(build_api_pytest_code(cases, {}), namespace)
        self.assertEqual(len([name for name in namespace if name.startswith("test_api_")]), 4)
