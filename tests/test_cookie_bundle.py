"""Unit tests for the canonical LeetCode cookie bundle."""
import json
import unittest

from src.cookie_bundle import load_cookie_pair, serialize_cookie_pair


class CookieBundleTests(unittest.TestCase):
    def test_loads_single_bundle_secret(self):
        pair = load_cookie_pair({
            "LEETCODE_COOKIE_BUNDLE": json.dumps({
                "LEETCODE_SESSION": " " + "s" * 80 + " ",
                "LEETCODE_CSRF_TOKEN": " csrf-value ",
            }),
            "LEETCODE_SESSION": "legacy-session",
            "LEETCODE_CSRF_TOKEN": "legacy-csrf",
        })
        self.assertEqual(pair, ("s" * 80, "csrf-value"))

    def test_falls_back_to_legacy_pair(self):
        self.assertEqual(
            load_cookie_pair({
                "LEETCODE_SESSION": "legacy-session",
                "LEETCODE_CSRF_TOKEN": "legacy-csrf",
            }),
            ("legacy-session", "legacy-csrf"),
        )

    def test_rejects_incomplete_bundle(self):
        with self.assertRaises(ValueError):
            load_cookie_pair({"LEETCODE_COOKIE_BUNDLE": '{"LEETCODE_SESSION":"only"}'})

    def test_serializes_pair_as_one_secret_value(self):
        bundle = json.loads(serialize_cookie_pair("s" * 80, "csrf"))
        self.assertEqual(bundle["LEETCODE_SESSION"], "s" * 80)
        self.assertEqual(bundle["LEETCODE_CSRF_TOKEN"], "csrf")

    def test_rejects_short_session(self):
        with self.assertRaises(ValueError):
            serialize_cookie_pair("short", "csrf")


if __name__ == "__main__":
    unittest.main()
