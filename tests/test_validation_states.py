"""Unit tests for strict sample-validation classification."""
import unittest

from src.validation import classify_validation_result, ValidationStatus


class ValidationStateTests(unittest.TestCase):
    def test_accepted_sample_is_passed(self):
        result = classify_validation_result({"state": "SUCCESS", "status_msg": "Accepted"})
        self.assertEqual(result.status, ValidationStatus.PASSED)

    def test_wrong_answer_is_code_failure(self):
        result = classify_validation_result({"state": "SUCCESS", "status_msg": "Wrong Answer"})
        self.assertEqual(result.status, ValidationStatus.CODE_FAILED)

    def test_http_403_is_auth_rejected(self):
        result = classify_validation_result(exception=RuntimeError("Run returned 403"))
        self.assertEqual(result.status, ValidationStatus.AUTH_REJECTED)
        self.assertEqual(result.http_code, 403)

    def test_429_and_timeout_are_inconclusive(self):
        for error in ("HTTP 429", "HTTP 503", "request timed out"):
            result = classify_validation_result(exception=RuntimeError(error))
            self.assertEqual(result.status, ValidationStatus.INFRA_INCONCLUSIVE)

    def test_non_terminal_response_is_not_a_pass(self):
        result = classify_validation_result({"state": "PENDING"})
        self.assertEqual(result.status, ValidationStatus.INFRA_INCONCLUSIVE)


if __name__ == "__main__":
    unittest.main()
