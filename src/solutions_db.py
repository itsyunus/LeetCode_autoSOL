"""
Solutions Database
Maintains a local cache of previously solved problems.
Checks this before hitting the AI API to save credits and time.
Also indexes public solution repositories.
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

SOLUTIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "solutions")


class SolutionsDB:
    """Local solutions cache backed by JSON files on disk."""

    def __init__(self, solutions_dir: str = SOLUTIONS_DIR):
        self.solutions_dir = solutions_dir
        self.index_path = os.path.join(solutions_dir, "_index.json")
        os.makedirs(solutions_dir, exist_ok=True)
        self._index = self._load_index()

    def _load_index(self) -> Dict[str, Any]:
        """Load the solutions index from disk."""
        if os.path.exists(self.index_path):
            with open(self.index_path, "r") as f:
                return json.load(f)
        return {"solutions": {}, "stats": {"total": 0, "easy": 0, "medium": 0, "hard": 0}}

    def _save_index(self):
        """Persist the solutions index to disk."""
        with open(self.index_path, "w") as f:
            json.dump(self._index, f, indent=2)

    def has_solution(self, title_slug: str) -> bool:
        """Check if we have a cached solution for this problem."""
        return title_slug in self._index["solutions"]

    def get_solution(self, title_slug: str) -> Optional[Dict[str, Any]]:
        """Retrieve a cached solution."""
        if not self.has_solution(title_slug):
            return None

        entry = self._index["solutions"][title_slug]
        solution_file = os.path.join(self.solutions_dir, entry["file"])

        if not os.path.exists(solution_file):
            logger.warning(f"Solution file missing for {title_slug}: {solution_file}")
            return None

        with open(solution_file, "r") as f:
            code = f.read()

        return {
            "code": code,
            "metadata": entry.get("metadata", {}),
            "cached": True,
        }

    def save_solution(
        self,
        title_slug: str,
        question_id: str,
        title: str,
        difficulty: str,
        code: str,
        metadata: Optional[Dict] = None,
        submission_result: Optional[Dict] = None,
    ):
        """Save a successfully submitted solution to the cache."""
        # Create filename: "0001_two-sum.py"
        frontend_id = metadata.get("frontend_id", question_id) if metadata else question_id
        safe_slug = title_slug.replace("/", "_")
        filename = f"{str(frontend_id).zfill(4)}_{safe_slug}.py"
        filepath = os.path.join(self.solutions_dir, filename)

        # Write the solution file with header
        header = f'"""\n{frontend_id}. {title}\nDifficulty: {difficulty}\n'
        if submission_result:
            runtime = submission_result.get("status_runtime", "N/A")
            memory = submission_result.get("status_memory", "N/A")
            header += f"Runtime: {runtime}\nMemory: {memory}\n"
        header += f'Solved: {datetime.now(timezone.utc).isoformat()}\n"""\n\n'

        with open(filepath, "w") as f:
            f.write(header + code)

        # Update index
        self._index["solutions"][title_slug] = {
            "file": filename,
            "question_id": question_id,
            "title": title,
            "difficulty": difficulty,
            "solved_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        # Update stats
        self._index["stats"]["total"] = len(self._index["solutions"])
        difficulty_lower = difficulty.lower()
        if difficulty_lower in self._index["stats"]:
            count = sum(
                1 for s in self._index["solutions"].values()
                if s.get("difficulty", "").lower() == difficulty_lower
            )
            self._index["stats"][difficulty_lower] = count

        self._save_index()
        logger.info(f"Saved solution: {filename}")

    def get_stats(self) -> Dict[str, int]:
        """Return solve statistics."""
        return self._index["stats"]

    def list_solved(self) -> list:
        """Return list of all solved problem slugs."""
        return list(self._index["solutions"].keys())

    def get_solve_history(self, limit: int = 10) -> list:
        """Return recent solve history sorted by date."""
        entries = []
        for slug, info in self._index["solutions"].items():
            entries.append({
                "slug": slug,
                "title": info.get("title", slug),
                "difficulty": info.get("difficulty", "Unknown"),
                "solved_at": info.get("solved_at", ""),
            })

        entries.sort(key=lambda x: x["solved_at"], reverse=True)
        return entries[:limit]

