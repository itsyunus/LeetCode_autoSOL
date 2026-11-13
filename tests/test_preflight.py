"""Unit tests for fail-closed LeetCode preflight classification."""
import unittest
from unittest.mock import Mock, patch

from src.preflight import run_preflight


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.session = "s" * 80
        self.csrf = "csrf-value"

    @patch("src.preflight.requests.Session")
    def test_cloudflare_403_stops_before_graphql(self, session_factory):
        client = Mock()
        page = Mock(status_code=403, text="<html>Access denied</html>")
        page.headers = {"content-type": "text/html"}
        client.get.return_value = page
        session_factory.return_value = client

        ok, status, reason = run_preflight(self.session, self.csrf)
        self.assertFalse(ok)
        self.assertEqual(status, "cloudflare_challenged")
        self.assertIn("Manual session push required", reason)
        client.post.assert_not_called()

    @patch("src.preflight.requests.Session")
    def test_signed_out_session_is_rejected(self, session_factory):
        client = Mock()
        page = Mock(status_code=200, text="<html>problem</html>")
        page.headers = {"content-type": "text/html"}
        graphql = Mock(status_code=200)
        graphql.headers = {"content-type": "application/json"}
        graphql.json.return_value = {"data": {"userStatus": {"isSignedIn": False}}}
        client.get.return_value = page
        client.post.return_value = graphql
        session_factory.return_value = client

        ok, status, _ = run_preflight(self.session, self.csrf)
        self.assertFalse(ok)
        self.assertEqual(status, "auth_rejected")

    @patch("src.preflight.requests.Session")
    def test_valid_session_passes(self, session_factory):
        client = Mock()
        page = Mock(status_code=200, text="<html>problem</html>")
        page.headers = {"content-type": "text/html"}
        graphql = Mock(status_code=200)
        graphql.headers = {"content-type": "application/json"}
        graphql.json.return_value = {
            "data": {"userStatus": {"isSignedIn": True, "username": "sample-user"}}
        }
        client.get.return_value = page
        client.post.return_value = graphql
        session_factory.return_value = client

        ok, status, reason = run_preflight(self.session, self.csrf)
        self.assertTrue(ok)
        self.assertEqual(status, "valid")
        self.assertIn("sample-user", reason)


if __name__ == "__main__":
    unittest.main()
