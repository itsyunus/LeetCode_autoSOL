import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.bulk_downloader import BulkDownloader


class OnlineSolutionLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = BulkDownloader(
            db_dir=Path(self.temp_dir.name) / "solutions_db",
            clone_dir=Path(self.temp_dir.name) / "repos",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("requests.get")
    def test_downloads_and_caches_language_specific_solution(self, get):
        range_response = Mock()
        range_response.status_code = 200
        range_response.json.return_value = [{
            "type": "dir",
            "name": "3693.Climbing Stairs II",
            "url": "https://api.github.com/repos/doocs/leetcode/contents/problem",
        }]
        folder_response = Mock()
        folder_response.status_code = 200
        folder_response.json.return_value = [{
            "type": "file",
            "name": "Solution.cpp",
            "download_url": "https://raw.githubusercontent.com/doocs/leetcode/main/Solution.cpp",
            "html_url": "https://github.com/doocs/leetcode/blob/main/Solution.cpp",
        }]
        code_response = Mock()
        code_response.status_code = 200
        code_response.text = "class Solution { public: int answer() { return 42; } };"
        get.side_effect = [range_response, folder_response, code_response]

        result = self.db.fetch_online_solution(
            "climbing-stairs-ii", "3693", "cpp", "Climbing Stairs II"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "doocs/leetcode")
        self.assertEqual(result["license"], "CC-BY-SA-4.0")
        self.assertIn("Source:", result["code"])
        self.assertIn("License: CC-BY-SA-4.0", result["code"])
        self.assertEqual(
            self.db.get_solution("climbing-stairs-ii", "cpp"), result["code"]
        )
        index_path = Path(self.temp_dir.name) / "solutions_db" / "_master_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(
            index["climbing-stairs-ii"]["languages"]["cpp"]["source"],
            "doocs/leetcode",
        )

    def test_unsupported_language_does_not_make_network_request(self):
        with patch("requests.get") as get:
            self.assertIsNone(
                self.db.fetch_online_solution("two-sum", "1", "unknown")
            )
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
