"""Preflight checks to keep malformed code from reaching LeetCode."""

import ast


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
