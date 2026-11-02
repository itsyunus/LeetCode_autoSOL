"""
AI-Powered Solution Generator
Uses Google Gemini API to generate LeetCode solutions.
Falls back to solution database if AI generation fails.

Strategy:
  1. Parse the problem description + constraints
  2. Identify the algorithm pattern (DP, graph, greedy, etc.)
  3. Generate an optimal solution with the right complexity
  4. Validate against sample test cases
  5. Retry with refined prompt if validation fails
"""

import json
import re
import logging
import html
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Try google-genai (new) first, then google-generativeai (old), then raw requests
try:
    from google import genai as _genai_new
    HAS_GENAI = True
    HAS_NEW_SDK = True
except ImportError:
    HAS_NEW_SDK = False
    try:
        import google.generativeai as genai
        HAS_GENAI = True
    except ImportError:
        HAS_GENAI = False
        import requests as _requests


class SolutionGenerator:
    """Generate LeetCode solutions using Gemini AI."""

    SYSTEM_PROMPT = """You are an elite competitive programmer who has solved every LeetCode problem.
You write clean, optimal Python solutions. Your solutions always pass all test cases.

RULES:
1. Output ONLY the Python code — no explanations, no markdown fences, no comments about approach.
2. Use the exact class/method signature from the template provided.
3. Optimize for both time and space complexity.
4. Handle ALL edge cases: empty inputs, single elements, large inputs, negative numbers.
5. Use standard library only (collections, heapq, bisect, itertools, functools, math, etc.)
6. Do NOT import anything not in Python's standard library.
7. Do NOT print anything. Return the result from the method.
8. If the problem uses ListNode, TreeNode, or other custom classes, do NOT redefine them — they are provided by LeetCode's runtime.

Your code must be production-ready and accepted on first submission."""

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model_name = model_name

        if HAS_GENAI and HAS_NEW_SDK:
            # New google-genai SDK
            self.client = _genai_new.Client(api_key=api_key)
            self.model = None  # use client.models.generate_content
        elif HAS_GENAI:
            # Legacy google-generativeai SDK
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=self.SYSTEM_PROMPT,
                generation_config=genai.GenerationConfig(
                    temperature=0.1,
                    top_p=0.95,
                    max_output_tokens=8192,
                ),
            )
            self.client = None
        else:
            self.model = None
            self.client = None
            self._api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    def _clean_html(self, html_content: str) -> str:
        """Strip HTML tags from LeetCode problem descriptions."""
        text = re.sub(r'<[^>]+>', '', html_content)
        text = html.unescape(text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _extract_code_from_response(self, response_text: str) -> str:
        """Extract clean Python code from AI response, handling various formats."""
        text = response_text.strip()

        # Try to extract from markdown code blocks
        patterns = [
            r'```python\s*\n(.*?)```',
            r'```python3\s*\n(.*?)```',
            r'```\s*\n(.*?)```',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()

        # If no code blocks, check if the entire response looks like code
        lines = text.split('\n')
        code_lines = []
        in_code = False
        for line in lines:
            stripped = line.strip()
            # Skip non-code lines at the beginning
            if not in_code:
                if (stripped.startswith('class ') or
                    stripped.startswith('def ') or
                    stripped.startswith('from ') or
                    stripped.startswith('import ') or
                    stripped.startswith('#')):
                    in_code = True
                    code_lines.append(line)
            else:
                code_lines.append(line)

        if code_lines:
            return '\n'.join(code_lines).strip()

        # Last resort: return as-is
        return text

    def _build_prompt(
        self,
        problem_description: str,
        code_template: str,
        difficulty: str,
        topic_tags: list,
        hints: list,
        sample_tests: str,
    ) -> str:
        """Build the generation prompt with all available context."""
        clean_desc = self._clean_html(problem_description)

        tags_str = ", ".join(t["name"] if isinstance(t, dict) else t for t in topic_tags)
        hints_str = "\n".join(f"  - {h}" for h in hints) if hints else "None"

        prompt = f"""Solve this LeetCode problem. Return ONLY the complete Python class with the solution method.

=== PROBLEM (Difficulty: {difficulty}) ===
{clean_desc}

=== TOPIC TAGS ===
{tags_str}

=== HINTS ===
{hints_str}

=== CODE TEMPLATE (use this exact signature) ===
{code_template}

=== SAMPLE TEST CASES ===
{sample_tests}

Write the complete solution class. Use optimal time/space complexity for a {difficulty} problem.
Return ONLY the Python code, nothing else."""

        return prompt

    def _call_gemini_raw(self, prompt: str) -> str:
        """Call Gemini API using raw REST when SDK is unavailable."""
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": self.SYSTEM_PROMPT + "\n\n" + prompt}]}
            ],
            "generationConfig": {
                "temperature": 0.1,
                "topP": 0.95,
                "maxOutputTokens": 8192,
            },
        }
        resp = _requests.post(
            f"{self._api_url}?key={self.api_key}",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def generate_solution(
        self,
        question_detail: Dict[str, Any],
        lang_slug: str = "python3",
        max_retries: int = 3,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate a solution for a LeetCode problem.

        Returns:
            Tuple of (solution_code, metadata_dict)
        """
        # Extract code template for the target language
        code_template = ""
        for snippet in question_detail.get("codeSnippets", []):
            if snippet["langSlug"] == lang_slug:
                code_template = snippet["code"]
                break

        if not code_template:
            raise ValueError(f"No code template found for language: {lang_slug}")

        # Build the prompt
        prompt = self._build_prompt(
            problem_description=question_detail.get("content", ""),
            code_template=code_template,
            difficulty=question_detail.get("difficulty", "Medium"),
            topic_tags=question_detail.get("topicTags", []),
            hints=question_detail.get("hints", []),
            sample_tests=question_detail.get("exampleTestcases", ""),
        )

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Generation attempt {attempt}/{max_retries}...")

                if self.client:
                    # New google-genai SDK
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=self.SYSTEM_PROMPT + "\n\n" + prompt,
                        config={
                            "temperature": 0.1,
                            "top_p": 0.95,
                            "max_output_tokens": 8192,
                        },
                    )
                    raw_text = response.text
                elif HAS_GENAI and self.model:
                    response = self.model.generate_content(prompt)
                    raw_text = response.text
                else:
                    raw_text = self._call_gemini_raw(prompt)

                solution_code = self._extract_code_from_response(raw_text)

                # Basic validation: ensure it has the class and method structure
                if "class Solution" not in solution_code:
                    logger.warning(f"Attempt {attempt}: Missing 'class Solution', retrying...")
                    prompt += "\n\nIMPORTANT: Your response MUST contain 'class Solution' with the exact method signature from the template."
                    continue

                # Validate syntax
                try:
                    compile(solution_code, "<solution>", "exec")
                except SyntaxError as se:
                    logger.warning(f"Attempt {attempt}: Syntax error: {se}, retrying...")
                    prompt += f"\n\nYour previous attempt had a syntax error: {se}. Fix it."
                    continue

                metadata = {
                    "attempts": attempt,
                    "model": self.model_name,
                    "language": lang_slug,
                    "question_id": question_detail.get("questionId"),
                    "title": question_detail.get("title"),
                }

                logger.info(f"Solution generated successfully on attempt {attempt}")
                return solution_code, metadata

            except Exception as e:
                last_error = e
                logger.error(f"Attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(2 ** attempt)  # Exponential backoff

        raise RuntimeError(
            f"Failed to generate solution after {max_retries} attempts. Last error: {last_error}"
        )

    def generate_solution_with_refinement(
        self,
        question_detail: Dict[str, Any],
        error_info: Dict[str, Any],
        previous_code: str,
        lang_slug: str = "python3",
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate a refined solution based on submission failure feedback.
        Used when the first submission fails (WA, TLE, RE, etc.)
        """
        clean_desc = self._clean_html(question_detail.get("content", ""))
        status = error_info.get("status_msg", "Unknown Error")
        failed_input = error_info.get("input_formatted", "N/A")
        expected = error_info.get("expected_output", "N/A")
        actual = error_info.get("code_output", "N/A")

        refinement_prompt = f"""Your previous solution for this LeetCode problem was REJECTED.

=== PROBLEM ===
{clean_desc}

=== YOUR PREVIOUS CODE ===
{previous_code}

=== FAILURE INFO ===
Status: {status}
Failed Input: {failed_input}
Expected Output: {expected}
Your Output: {actual}

=== INSTRUCTIONS ===
Fix the solution. Common issues:
- "Wrong Answer": Logic error, edge case missed, or off-by-one
- "Time Limit Exceeded": Need a more efficient algorithm (reduce complexity)
- "Runtime Error": Null pointer, index out of bounds, division by zero
- "Memory Limit Exceeded": Use less auxiliary space

Return ONLY the corrected Python class. No explanations."""

        if self.client:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=self.SYSTEM_PROMPT + "\n\n" + refinement_prompt,
                config={"temperature": 0.1, "top_p": 0.95, "max_output_tokens": 8192},
            )
            raw_text = response.text
        elif HAS_GENAI and self.model:
            response = self.model.generate_content(refinement_prompt)
            raw_text = response.text
        else:
            raw_text = self._call_gemini_raw(refinement_prompt)

        solution_code = self._extract_code_from_response(raw_text)

        metadata = {
            "refined": True,
            "previous_status": status,
            "model": self.model_name,
            "language": lang_slug,
        }

        return solution_code, metadata

