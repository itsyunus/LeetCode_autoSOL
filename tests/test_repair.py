import unittest
from unittest.mock import Mock
from src.validation import validate_solution_syntax
from src.dashboard import build_dashboard
from src.leetcode_api import LeetCodeAPI


class LeetCodeResponseTests(unittest.TestCase):
    def test_non_json_response_has_actionable_diagnostic(self):
        response = Mock()
        response.json.side_effect = ValueError("not JSON")
        response.headers = {"Content-Type": "text/html"}
        response.status_code = 403
        with self.assertRaisesRegex(RuntimeError, "non-JSON response.*HTTP 403"):
            LeetCodeAPI._response_json(response, "LeetCode GraphQL")

    def test_json_response_must_be_an_object(self):
        response = Mock()
        response.json.return_value = ["unexpected"]
        with self.assertRaisesRegex(RuntimeError, "unexpected JSON payload"):
            LeetCodeAPI._response_json(response, "LeetCode API")

    def test_valid_json_response(self):
        response = Mock()
        response.json.return_value = {"ok": True}
        self.assertEqual(LeetCodeAPI._response_json(response, "LeetCode API"), {"ok": True})

class ValidationTests(unittest.TestCase):
    def test_valid_solution(self):
        validate_solution_syntax("class Solution:\n    def solve(self):\n        return 1")

    def test_empty_solution(self):
        with self.assertRaises(ValueError):
            validate_solution_syntax("")

    def test_syntax_error(self):
        with self.assertRaises(SyntaxError):
            validate_solution_syntax("class Solution\n    pass")

    def test_missing_solution_class(self):
        with self.assertRaises(ValueError):
            validate_solution_syntax("def solve(): return 1")


class DashboardTests(unittest.TestCase):
    def test_escaped_title_and_metrics(self):
        page = build_dashboard([{
            "date": "2026-11-09", "status": "accepted",
            "problem": {"id": "1606", "title": "<script>alert(1)</script>",
                        "slug": "find-servers-that-handled-most-number-of-requests",
                        "difficulty": "Hard"}
        }])
        self.assertIn("100%", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_empty_dashboard(self):
        self.assertIn("No run history yet", build_dashboard([]))


if __name__ == "__main__":
    unittest.main()
