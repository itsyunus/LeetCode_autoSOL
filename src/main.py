"""
Main Orchestrator — LeetCode Daily Auto-Solver
Coordinates the full pipeline:
  1. Check if today's problem is already solved
  2. Fetch the daily challenge from LeetCode
  3. Check the local solutions cache
  4. Generate a solution using AI if not cached
  5. Test against sample test cases
  6. Submit to LeetCode
  7. Handle failures with refinement loop
  8. Cache the accepted solution
  9. Commit results to git (for GitHub Actions)
"""

import os
import sys
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Optional

from .leetcode_api import LeetCodeAPI
from .solver import SolutionGenerator
from .solutions_db import SolutionsDB
from .bulk_downloader import BulkDownloader
from .browser_submitter import BrowserSubmitter

# ── Logging ──────────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "solver.log"),
            mode="a",
        ),
    ],
)
logger = logging.getLogger("leetcode-auto-solver")


class DailySolverPipeline:
    """End-to-end daily challenge solver."""

    MAX_SUBMISSION_RETRIES = 3  # Max times we'll refine & resubmit

    def __init__(
        self,
        leetcode_session: str,
        leetcode_csrf: str,
        gemini_api_key: str,
        gemini_model: str = "gemini-2.5-flash",
        lang: str = "python3",
        skip_if_solved: bool = True,
        dry_run: bool = False,
    ):
        self.lc = LeetCodeAPI(leetcode_session, leetcode_csrf)
        self.browser = BrowserSubmitter(leetcode_session, leetcode_csrf)
        self.solver = SolutionGenerator(gemini_api_key, gemini_model)
        self.db = SolutionsDB()
        self.bulk_db = BulkDownloader()
        self.lang = lang
        self.skip_if_solved = skip_if_solved
        self.dry_run = dry_run

    def run(self) -> dict:
        """
        Execute the full daily solver pipeline.
        Returns a result dict with status and metadata.
        """
        result = {
            "status": "unknown",
            "date": datetime.now(timezone.utc).isoformat(),
            "problem": None,
            "submission": None,
            "error": None,
        }

        try:
            # ── Step 1: Fetch daily challenge ────────────────────────
            logger.info("=" * 60)
            logger.info("🚀 LeetCode Daily Auto-Solver — Starting Pipeline")
            logger.info("=" * 60)

            challenge = self.lc.get_daily_challenge()
            question = challenge["question"]
            slug = question["titleSlug"]
            qid = question["questionId"]
            frontend_id = question["questionFrontendId"]
            title = question["title"]
            difficulty = question["difficulty"]

            result["problem"] = {
                "id": frontend_id,
                "title": title,
                "slug": slug,
                "difficulty": difficulty,
                "date": challenge["date"],
                "tags": [t["name"] for t in question.get("topicTags", [])],
            }

            logger.info(f"📋 Daily Problem: [{frontend_id}] {title} ({difficulty})")

            # ── Step 2: Check if already solved on LeetCode ──────────
            if self.skip_if_solved and self.lc.is_already_solved(slug):
                logger.info("✅ Already solved today — nothing to do!")
                result["status"] = "already_solved"
                return result

            # ── Step 3: Fetch full problem details ───────────────────
            detail = self.lc.get_question_detail(slug)

            # ── Step 4: Check local cache + bulk DB ────────────────
            cached = self.db.get_solution(slug)
            bulk_code = self.bulk_db.get_solution(slug)

            if cached:
                logger.info("📦 Found in local solve cache — using it")
                solution_code = cached["code"]
                # Strip the header comment if present
                if solution_code.startswith('"""'):
                    end = solution_code.find('"""', 3)
                    if end != -1:
                        solution_code = solution_code[end + 3:].strip()
                gen_metadata = cached.get("metadata", {})
                gen_metadata["source"] = "local_cache"
            elif bulk_code:
                logger.info("📦 Found in bulk solutions DB — using pre-downloaded solution")
                solution_code = bulk_code
                gen_metadata = {"source": "bulk_db"}
            else:
                # ── Step 5: Generate solution with AI ────────────────
                logger.info("🤖 No cached solution — generating with AI...")
                solution_code, gen_metadata = self.solver.generate_solution(
                    detail, lang_slug=self.lang
                )
                gen_metadata["source"] = "ai_generated"
                logger.info(f"Generated solution ({len(solution_code)} chars)")

            # ── Step 6: Pre-validate with sample tests ───────────────
            sample_tests = detail.get("exampleTestcases", "")
            if sample_tests and not self.dry_run:
                logger.info("🧪 Running against sample test cases...")
                try:
                    run_result = self.browser.run_code(
                        slug, qid, solution_code, sample_tests, self.lang
                    )
                    if run_result.get("status_msg") != "Accepted":
                        logger.warning(
                            f"Sample test failed: {run_result.get('status_msg')} — "
                            f"attempting refinement before submission"
                        )
                        solution_code, _ = self.solver.generate_solution_with_refinement(
                            detail, run_result, solution_code, self.lang
                        )
                    else:
                        logger.info("✅ Sample tests passed!")
                except Exception as e:
                    logger.warning(f"Pre-validation failed (non-fatal): {e}")

            if self.dry_run:
                logger.info("🏜️  DRY RUN — skipping submission")
                logger.info(f"Generated code:\n{solution_code}")
                result["status"] = "dry_run"
                result["solution_code"] = solution_code
                return result

            # ── Step 7: Submit with retry loop ───────────────────────
            submission_result = None
            current_code = solution_code

            for attempt in range(1, self.MAX_SUBMISSION_RETRIES + 1):
                logger.info(f"📤 Submission attempt {attempt}/{self.MAX_SUBMISSION_RETRIES}")

                sub_response = self.browser.submit_solution(slug, qid, current_code, self.lang)
                sub_id = sub_response.get("submission_id")

                if not sub_id:
                    logger.error(f"No submission ID returned: {sub_response}")
                    continue

                # Poll for result
                submission_result = self.browser.poll_submission_result(sub_id)
                status_msg = submission_result.get("status_msg", "Unknown")

                if status_msg == "Accepted":
                    logger.info("🎉 ACCEPTED!")
                    result["status"] = "accepted"
                    result["submission"] = {
                        "id": sub_id,
                        "runtime": submission_result.get("status_runtime"),
                        "memory": submission_result.get("status_memory"),
                        "runtime_percentile": submission_result.get("runtime_percentile"),
                        "memory_percentile": submission_result.get("memory_percentile"),
                        "attempts": attempt,
                    }

                    # Cache the solution
                    self.db.save_solution(
                        title_slug=slug,
                        question_id=qid,
                        title=title,
                        difficulty=difficulty,
                        code=current_code,
                        metadata={
                            "frontend_id": frontend_id,
                            **gen_metadata,
                        },
                        submission_result=submission_result,
                    )
                    break

                else:
                    logger.warning(f"Submission failed: {status_msg}")
                    if attempt < self.MAX_SUBMISSION_RETRIES:
                        logger.info("🔄 Refining solution based on failure feedback...")
                        current_code, _ = self.solver.generate_solution_with_refinement(
                            detail, submission_result, current_code, self.lang
                        )
                    else:
                        result["status"] = "failed"
                        result["error"] = f"Failed after {attempt} attempts: {status_msg}"
                        result["submission"] = {"last_status": status_msg}

            # ── Step 8: Git commit (for GitHub Actions) ──────────────
            self._git_commit_results(result)
            self.browser.close()

            return result

        except Exception as e:
            logger.exception(f"Pipeline failed: {e}")
            result["status"] = "error"
            result["error"] = str(e)
            self.browser.close()
            return result

    def _git_commit_results(self, result: dict):
        """Commit solution and logs to git for the GitHub Actions workflow."""
        try:
            repo_root = os.path.dirname(os.path.dirname(__file__))

            # Save result summary
            results_dir = os.path.join(repo_root, "logs")
            os.makedirs(results_dir, exist_ok=True)
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            result_file = os.path.join(results_dir, f"result_{date_str}.json")
            with open(result_file, "w") as f:
                json.dump(result, f, indent=2, default=str)

            # Git operations
            subprocess.run(["git", "config", "user.email", "leetcode-bot@auto-solver.dev"],
                         cwd=repo_root, capture_output=True)
            subprocess.run(["git", "config", "user.name", "LeetCode Auto-Solver"],
                         cwd=repo_root, capture_output=True)
            subprocess.run(["git", "add", "-A"], cwd=repo_root, capture_output=True)

            problem = result.get("problem", {})
            title = problem.get("title", "Unknown")
            pid = problem.get("id", "?")
            status = result.get("status", "unknown")
            commit_msg = f"✅ [{date_str}] #{pid} {title} — {status}"

            subprocess.run(
                ["git", "commit", "-m", commit_msg, "--allow-empty"],
                cwd=repo_root, capture_output=True,
            )
            subprocess.run(["git", "push"], cwd=repo_root, capture_output=True)
            logger.info(f"Git commit: {commit_msg}")

        except Exception as e:
            logger.warning(f"Git commit failed (non-fatal): {e}")


def main():
    """Entry point — reads config from environment variables."""
    # Required environment variables
    leetcode_session = os.environ.get("LEETCODE_SESSION")
    leetcode_csrf = os.environ.get("LEETCODE_CSRF_TOKEN")
    gemini_api_key = os.environ.get("GEMINI_API_KEY")

    if not all([leetcode_session, leetcode_csrf, gemini_api_key]):
        missing = []
        if not leetcode_session:
            missing.append("LEETCODE_SESSION")
        if not leetcode_csrf:
            missing.append("LEETCODE_CSRF_TOKEN")
        if not gemini_api_key:
            missing.append("GEMINI_API_KEY")
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        logger.error(
            "Set these as GitHub Secrets or in your .env file.\n"
            "See README.md for instructions on obtaining these values."
        )
        sys.exit(1)

    # Optional config
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    lang = os.environ.get("SOLUTION_LANGUAGE", "python3")
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    skip_solved = os.environ.get("SKIP_IF_SOLVED", "true").lower() == "true"

    pipeline = DailySolverPipeline(
        leetcode_session=leetcode_session,
        leetcode_csrf=leetcode_csrf,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        lang=lang,
        skip_if_solved=skip_solved,
        dry_run=dry_run,
    )

    result = pipeline.run()

    # Print summary
    logger.info("=" * 60)
    logger.info("📊 PIPELINE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Status:     {result['status']}")
    if result.get("problem"):
        p = result["problem"]
        logger.info(f"  Problem:    [{p['id']}] {p['title']} ({p['difficulty']})")
    if result.get("submission"):
        s = result["submission"]
        logger.info(f"  Runtime:    {s.get('runtime', 'N/A')}")
        logger.info(f"  Memory:     {s.get('memory', 'N/A')}")
        logger.info(f"  Attempts:   {s.get('attempts', 'N/A')}")
    if result.get("error"):
        logger.error(f"  Error:      {result['error']}")
    logger.info("=" * 60)

    # Exit with error code if failed
    if result["status"] in ("error", "failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()

