import unittest
from unittest.mock import Mock
from src.validation import validate_solution_syntax
from src.dashboard import build_dashboard
from src.leetcode_api import LeetCodeAPI
from src.solver import SolutionGenerator
from src.main import DailySolverPipeline


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

    def test_rejects_itertools_izip(self):
        code = "\n".join([
            "import itertools",
            "class Solution:",
            "    def solve(self, arrival, load):",
            "        return list(itertools.izip(arrival, load))",
        ])
        with self.assertRaisesRegex(ValueError, "use the built-in zip"):
            validate_solution_syntax(code)

    def test_rejects_from_itertools_import_izip(self):
        code = "\n".join(["from itertools import izip", "class Solution: pass"])
        with self.assertRaisesRegex(ValueError, "use the built-in zip"):
            validate_solution_syntax(code)

    def test_accepts_python3_zip(self):
        code = "\n".join([
            "class Solution:",
            "    def solve(self, arrival, load):",
            "        return list(zip(arrival, load))",
        ])
        validate_solution_syntax(code)


class LanguageGenerationTests(unittest.TestCase):
    def setUp(self):
        self.generator = SolutionGenerator.__new__(SolutionGenerator)

    def test_cpp_prompt_uses_cpp_template_and_language(self):
        prompt = self.generator._build_prompt(
            problem_description="Find the sum.",
            code_template="class Solution { public: int sum(int a, int b) { return 0; } };",
            difficulty="Easy",
            topic_tags=[],
            hints=[],
            sample_tests="1 2",
            lang_slug="cpp",
        )
        self.assertIn("C++17 solution", prompt)
        self.assertIn("C++17 code", prompt)
        self.assertNotIn("Python code", prompt)

    def test_extract_cpp_code_fence(self):
        code = self.generator._extract_code_from_response(
            "```cpp\nclass Solution {};\n```"
        )
        self.assertEqual(code, "class Solution {};")


class FallbackValidationTests(unittest.TestCase):
    def test_successful_fallback_marks_sample_validation_as_complete(self):
        pipeline = DailySolverPipeline.__new__(DailySolverPipeline)
        pipeline.lang = "python3"
        pipeline.attempted_languages = ["python3"]
        pipeline.solver = Mock()
        pipeline.solver.generate_solution.return_value = (
            "class Solution { public: int solve() { return 1; } };",
            {},
        )
        pipeline.browser = Mock()
        pipeline.browser.run_code.return_value = {"status_msg": "Accepted"}
        detail = {"codeSnippets": [{"langSlug": "cpp", "code": "class Solution {};"}]}

        language, code, metadata = pipeline._next_runtime_fallback(
            detail, "sample-problem", "123", "1"
        )

        self.assertEqual(language, "cpp")
        self.assertIn("class Solution", code)
        self.assertTrue(metadata["sample_validation_passed"])
        pipeline.browser.run_code.assert_called_once_with(
            "sample-problem", "123", code, "1", "cpp"
        )

    def test_rate_limit_stops_language_fallback_chain(self):
        pipeline = DailySolverPipeline.__new__(DailySolverPipeline)
        pipeline.lang = "python3"
        pipeline.attempted_languages = ["python3"]
        pipeline.solver = Mock()
        pipeline.solver.generate_solution.return_value = ("class Solution {};", {})
        pipeline.browser = Mock()
        pipeline.browser.run_code.side_effect = RuntimeError(
            "LeetCode run endpoint returned non-JSON HTTP 429"
        )
        detail = {
            "codeSnippets": [
                {"langSlug": "cpp", "code": "class Solution {};"},
                {"langSlug": "java", "code": "class Solution {}"},
            ]
        }

        with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
            pipeline._next_runtime_fallback(detail, "sample-problem", "123", "1")
        self.assertEqual(pipeline.solver.generate_solution.call_count, 1)
        pipeline.browser.run_code.assert_called_once()


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
