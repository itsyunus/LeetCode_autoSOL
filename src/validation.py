"""Preflight checks to keep malformed code from reaching LeetCode."""
def validate_solution_syntax(code: str, language: str = "python3") -> None:
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Solution is empty.")
    if language == "python3":
        compile(code, "<leetcode-solution>", "exec")
        if "class Solution" not in code:
            raise ValueError("Python solution must define class Solution.")
