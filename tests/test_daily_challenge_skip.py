import unittest
from unittest.mock import patch

from src.leetcode_api import LeetCodeAPI


class DailyChallengeSolvedDateTests(unittest.TestCase):
    def setUp(self):
        # The method under test only needs get_submission_list; avoid creating
        # a real HTTP session or requiring LeetCode credentials.
        self.client = object.__new__(LeetCodeAPI)

    def test_old_accepted_submission_does_not_skip_today(self):
        self.client.get_submission_list = lambda slug, limit=5: [
            {"statusDisplay": "Accepted", "timestamp": "1735689600"}
        ]
        self.assertFalse(self.client.is_already_solved("example-problem", "2026-11-12"))

    def test_accepted_submission_on_challenge_date_skips(self):
        # 2026-11-12 12:00:00 UTC
        self.client.get_submission_list = lambda slug, limit=5: [
            {"statusDisplay": "Accepted", "timestamp": "1794484800"}
        ]
        self.assertTrue(self.client.is_already_solved("example-problem", "2026-11-12"))

    def test_non_accepted_submission_does_not_skip(self):
        self.client.get_submission_list = lambda slug, limit=5: [
            {"statusDisplay": "Wrong Answer", "timestamp": "1794484800"}
        ]
        self.assertFalse(self.client.is_already_solved("example-problem", "2026-11-12"))

    def test_missing_timestamp_does_not_skip(self):
        self.client.get_submission_list = lambda slug, limit=5: [
            {"statusDisplay": "Accepted"}
        ]
        self.assertFalse(self.client.is_already_solved("example-problem", "2026-11-12"))


if __name__ == "__main__":
    unittest.main()
