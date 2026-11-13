"""Preflight checks and explicit result classification for LeetCode validation."""

import ast
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class ValidationStatus(str, Enum):
    PASSED = "passed"
    CODE_FAILED = "code_failed"
    AUTH_REJECTED = "auth_rejected"
    INFRA_INCONCLUSIVE = "inconclusive"


@dataclass
class ValidationResult:
    status: ValidationStatus
    http_code: Optional[int]
    reason: str
    actual_output: str = ""
    expected_output: str = ""


def classify_validation_result(
    response: Optional[dict] = None,
    exception: Optional[BaseException] = None,
) -> ValidationResult:
    """Classify validation without treating an unavailable service as a pass."""
    if exception is not None:
        reason = str(exception) or type(exception).__name__
        match = re.search(r"(?:HTTP\s+|returned\s+)(\d{3})", reason, re.IGNORECASE)
        code = int(match.group(1)) if match else None
        if code in (401, 403):
            return ValidationResult(
                ValidationStatus.AUTH_REJECTED, code,
                "LeetCode rejected validation authentication (HTTP %s)." % code,
            )
        if code == 429 or (code is not None and code >= 500) or any(
            marker in reason.lower()
            for marker in ("timeout", "timed out", "non-json", "connection", "cloudflare")
        ):
            return ValidationResult(
                ValidationStatus.INFRA_INCONCLUSIVE, code,
                "Validation service unavailable; no submission is permitted: " + reason[:300],
            )
        return ValidationResult(
            ValidationStatus.INFRA_INCONCLUSIVE, code,
            "Validation could not be verified; no submission is permitted: " + reason[:300],
        )

    result = response if isinstance(response, dict) else {}
    state = result.get("state")
    status_msg = str(result.get("status_msg") or "")
    if state == "SUCCESS" and status_msg == "Accepted":
        return ValidationResult(ValidationStatus.PASSED, 200, "Sample tests passed.")
    if state == "SUCCESS" and status_msg:
        return ValidationResult(
            ValidationStatus.CODE_FAILED, 200,
            "Candidate failed sample validation: " + status_msg,
            actual_output=str(result.get("code_output") or ""),
            expected_output=str(result.get("expected_output") or ""),
        )
    return ValidationResult(
        ValidationStatus.INFRA_INCONCLUSIVE, None,
        "Validation response did not contain a terminal successful judge result.",
    )



def validate_solution_syntax(code: str, language: str = "python3") -> None:
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Solution is empty.")

    if language == "python3":
        compile(code, "<leetcode-solution>", "exec")
        tree = ast.parse(code, filename="<leetcode-solution>")

        if not any(
            isinstance(node, ast.ClassDef) and node.name == "Solution"
            for node in ast.walk(tree)
        ):
            raise ValueError("Python solution must define class Solution.")

        # itertools.izip and importing izip are Python 2 APIs.
        itertools_aliases = {"itertools"}
        imported_izip = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "itertools":
                        itertools_aliases.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "itertools":
                if any(alias.name == "izip" for alias in node.names):
                    imported_izip = True
            elif (
                isinstance(node, ast.Attribute)
                and node.attr == "izip"
                and isinstance(node.value, ast.Name)
                and node.value.id in itertools_aliases
            ):
                imported_izip = True

        if imported_izip:
            raise ValueError(
                "Python 2 API itertools.izip is not available in Python 3; "
                "use the built-in zip() instead."
            )
