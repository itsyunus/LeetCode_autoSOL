import unittest
from src.validation import validate_solution_syntax
from src.dashboard import build_dashboard


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
