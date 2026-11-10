"""
LeetCode GraphQL API Client
Handles all communication with LeetCode's backend:
  - Fetching daily challenge
  - Fetching question metadata, templates, test cases
  - Submitting solutions
  - Checking submission status
"""

import requests
import time
import json
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"
LEETCODE_BASE_URL = "https://leetcode.com"


class LeetCodeAPI:
    """Full-featured LeetCode API client using GraphQL + REST hybrid."""

    def __init__(self, session_token: str, csrf_token: str):
        self.session = requests.Session()
        self.session.cookies.set("LEETCODE_SESSION", session_token, domain=".leetcode.com")
        self.session.cookies.set("csrftoken", csrf_token, domain=".leetcode.com")
        self.session.headers.update({
            "Content-Type": "application/json",
            "Referer": LEETCODE_BASE_URL,
            "Origin": LEETCODE_BASE_URL,
            "x-csrftoken": csrf_token,
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        })

    @staticmethod
    def _response_json(response, endpoint: str) -> Dict[str, Any]:
        """Decode API JSON with a useful error when a proxy/login page returns HTML."""
        try:
            data = response.json()
        except ValueError as exc:
            content_type = response.headers.get("Content-Type", "unknown")
            raise RuntimeError(
                f"{endpoint} returned a non-JSON response "
                f"(HTTP {response.status_code}, content type: {content_type}). "
                "Check LeetCode session validity, rate limits, or a security challenge."
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"{endpoint} returned an unexpected JSON payload.")
        return data

    def _graphql(self, query: str, variables: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute a GraphQL query against LeetCode's API."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        resp = self.session.post(LEETCODE_GRAPHQL_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = self._response_json(resp, "LeetCode GraphQL")

        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")

        return data["data"]

    def get_daily_challenge(self) -> Dict[str, Any]:
        """
        Fetch today's daily coding challenge.
        Returns question slug, id, title, difficulty, and frontend ID.
        """
        query = """
        query questionOfToday {
            activeDailyCodingChallengeQuestion {
                date
                link
                question {
                    questionId
                    questionFrontendId
                    title
                    titleSlug
                    difficulty
                    topicTags {
                        name
                        slug
                    }
                    stats
                    isPaidOnly
                }
            }
        }
        """
        data = self._graphql(query)
        challenge = data["activeDailyCodingChallengeQuestion"]
        logger.info(
            f"Daily challenge: [{challenge['question']['questionFrontendId']}] "
            f"{challenge['question']['title']} ({challenge['question']['difficulty']})"
        )
        return challenge

    def get_question_detail(self, title_slug: str) -> Dict[str, Any]:
        """
        Fetch full question details including:
          - HTML content (problem description)
          - Code snippets/templates for all languages
          - Sample test cases
          - Hints
          - Constraints
        """
        query = """
        query questionDetail($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                questionId
                questionFrontendId
                title
                titleSlug
                content
                difficulty
                topicTags {
                    name
                    slug
                }
                codeSnippets {
                    lang
                    langSlug
                    code
                }
                sampleTestCase
                exampleTestcases
                hints
                metaData
                stats
                similarQuestions
            }
        }
        """
        data = self._graphql(query, {"titleSlug": title_slug})
        question = data["question"]
        logger.info(f"Fetched details for: {question['title']}")
        return question

    def get_all_questions_list(self, limit: int = 3000) -> list:
        """
        Fetch the full problemset list from LeetCode.
        Useful for building a local solutions database index.
        """
        query = """
        query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
            problemsetQuestionList: questionList(
                categorySlug: $categorySlug
                limit: $limit
                skip: $skip
                filters: $filters
            ) {
                total: totalNum
                questions: data {
                    questionId
                    questionFrontendId
                    title
                    titleSlug
                    difficulty
                    topicTags {
                        name
                        slug
                    }
                    isPaidOnly
                    status
                    acRate
                }
            }
        }
        """
        variables = {
            "categorySlug": "all-code-essentials",
            "limit": limit,
            "skip": 0,
            "filters": {},
        }
        data = self._graphql(query, variables)
        questions = data["problemsetQuestionList"]["questions"]
        logger.info(f"Fetched {len(questions)} questions from problemset")
        return questions

    def submit_solution(
        self, slug: str, question_id: str, code: str, lang_slug: str = "python3"
    ) -> Dict[str, Any]:
        """
        Submit a solution to LeetCode.
        Returns the submission ID for status polling.
        """
        url = f"{LEETCODE_BASE_URL}/problems/{slug}/submit/"
        payload = {
            "lang": lang_slug,
            "question_id": question_id,
            "typed_code": code,
        }

        logger.info(f"Submitting solution for '{slug}' in {lang_slug}...")
        resp = self.session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        result = self._response_json(resp, "LeetCode submission")
        submission_id = result.get("submission_id")
        logger.info(f"Submission ID: {submission_id}")
        return result

    def check_submission(self, submission_id: int) -> Dict[str, Any]:
        """Check the status of a submission by its ID."""
        url = f"{LEETCODE_BASE_URL}/submissions/detail/{submission_id}/check/"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return self._response_json(resp, "LeetCode submission status")

    def poll_submission_result(
        self, submission_id: int, max_retries: int = 20, interval: float = 2.0
    ) -> Dict[str, Any]:
        """
        Poll submission status until it's judged.
        LeetCode judges asynchronously — we poll until state != 'PENDING'.
        """
        for attempt in range(max_retries):
            result = self.check_submission(submission_id)
            state = result.get("state")

            if state == "SUCCESS":
                status_msg = result.get("status_msg", "Unknown")
                if status_msg == "Accepted":
                    runtime = result.get("status_runtime", "N/A")
                    memory = result.get("status_memory", "N/A")
                    logger.info(
                        f"✅ ACCEPTED — Runtime: {runtime}, Memory: {memory}"
                    )
                else:
                    logger.warning(
                        f"❌ {status_msg} — "
                        f"Failed test: {result.get('input_formatted', 'N/A')}"
                    )
                return result

            logger.debug(f"Polling attempt {attempt + 1}/{max_retries}, state={state}")
            time.sleep(interval)

        raise TimeoutError(
            f"Submission {submission_id} still pending after {max_retries} polls"
        )

    def run_code(
        self, slug: str, question_id: str, code: str,
        test_input: str, lang_slug: str = "python3"
    ) -> Dict[str, Any]:
        """
        Run code against custom test cases (without submitting).
        Useful for pre-validation before actual submission.
        """
        url = f"{LEETCODE_BASE_URL}/problems/{slug}/interpret_solution/"
        payload = {
            "lang": lang_slug,
            "question_id": question_id,
            "typed_code": code,
            "data_input": test_input,
        }

        resp = self.session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        result = self._response_json(resp, "LeetCode sample-test request")
        interpret_id = result.get("interpret_id")

        # Poll for run result
        for _ in range(20):
            check_url = f"{LEETCODE_BASE_URL}/submissions/detail/{interpret_id}/check/"
            check_resp = self.session.get(check_url, timeout=30)
            check_resp.raise_for_status()
            check_result = self._response_json(check_resp, "LeetCode sample-test status")

            if check_result.get("state") == "SUCCESS":
                return check_result
            time.sleep(1.5)

        raise TimeoutError(f"Code run {interpret_id} timed out")

    def get_submission_list(self, slug: str, limit: int = 5) -> list:
        """Fetch recent submissions for a problem (to check if already solved)."""
        query = """
        query submissionList($questionSlug: String!, $limit: Int, $offset: Int) {
            questionSubmissionList(
                questionSlug: $questionSlug
                limit: $limit
                offset: $offset
            ) {
                submissions {
                    id
                    statusDisplay
                    lang
                    runtime
                    memory
                    timestamp
                }
            }
        }
        """
        data = self._graphql(query, {
            "questionSlug": slug,
            "limit": limit,
            "offset": 0,
        })
        question_data = data.get("questionSubmissionList")
        if not question_data or not isinstance(question_data, dict):
            return []
        return question_data.get("submissions") or []

    def is_already_solved(self, slug: str) -> bool:
        """Check if the user has already solved this problem today."""
        try:
            submissions = self.get_submission_list(slug, limit=5)
            for sub in submissions:
                if sub["statusDisplay"] == "Accepted":
                    logger.info(f"Problem '{slug}' already solved — skipping.")
                    return True
        except Exception as e:
            logger.warning(f"Could not check submission history: {e}")
        return False

