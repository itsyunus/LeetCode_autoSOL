"""
Bulk Solutions Downloader
Downloads ALL ~3000+ LeetCode solutions from well-known public repositories,
indexes them by problem slug/ID, and stores them for instant lookup.

Sources (in priority order):
  1. walkccc/LeetCode — 3000+ problems, organized by number, Python solutions
  2. neetcode-gh/leetcode — NeetCode's curated optimal solutions
  3. LeetCode Community Solutions API — top-voted discuss solutions (fills gaps)

After running this once, the daily solver hits the local DB first and
only falls back to AI for brand-new problems not yet in any public repo.
"""

import os
import re
import sys
import json
import shutil
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# ── Repo sources with known directory structures ─────────────────────
SOLUTION_REPOS = [
    {
        "name": "walkccc/LeetCode",
        "url": "https://github.com/walkccc/LeetCode.git",
        "sparse_path": "solutions",
        "pattern": r"(\d+)\.\s*(.+)",  # "1. Two Sum" style dirs
        "file_glob": "*.py",
        "priority": 1,
    },
    {
        "name": "neetcode-gh/leetcode",
        "url": "https://github.com/neetcode-gh/leetcode.git",
        "sparse_path": "python",
        "pattern": r"(\d+)-(.+)\.py",  # "0001-two-sum.py" style files
        "file_glob": "*.py",
        "priority": 2,
    },
    {
        "name": "kamyu104/LeetCode-Solutions",
        "url": "https://github.com/kamyu104/LeetCode-Solutions.git",
        "sparse_path": "Python",
        "pattern": r"(.+)\.py",  # "two-sum.py" style
        "file_glob": "*.py",
        "priority": 3,
    },
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = PROJECT_ROOT / "solutions_db"
INDEX_FILE = DB_DIR / "_master_index.json"
CLONE_DIR = PROJECT_ROOT / ".repos"


class BulkDownloader:
    """Downloads and indexes all LeetCode solutions from public repos."""

    def __init__(self, db_dir: Path = DB_DIR, clone_dir: Path = CLONE_DIR):
        self.db_dir = db_dir
        self.clone_dir = clone_dir
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.clone_dir.mkdir(parents=True, exist_ok=True)
        self.index: Dict[str, dict] = {}
        self._load_index()

    # ── Index Management ─────────────────────────────────────────────

    def _load_index(self):
        index_file = self.db_dir / "_master_index.json"
        if index_file.exists():
            with open(index_file, encoding="utf-8") as f:
                self.index = json.load(f)
        else:
            self.index = {}

    def _save_index(self):
        index_file = self.db_dir / "_master_index.json"
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2, sort_keys=True)
        logger.info(f"Index saved: {len(self.index)} solutions indexed")

    # ── Git Clone (Shallow + Sparse for speed) ───────────────────────

    def _clone_repo(self, repo: dict) -> Optional[Path]:
        """
        Shallow-clone a repo. Uses sparse checkout to grab only the
        Python solutions directory — saves bandwidth and disk space.
        """
        name = repo["name"].replace("/", "_")
        dest = self.clone_dir / name

        if dest.exists():
            logger.info(f"Repo already cloned: {name} — pulling latest...")
            try:
                subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=dest, capture_output=True, timeout=120,
                )
                return dest
            except Exception as e:
                logger.warning(f"Pull failed for {name}: {e} — re-cloning")
                shutil.rmtree(dest, ignore_errors=True)

        logger.info(f"Cloning {repo['name']}...")
        try:
            # Shallow clone with depth=1 for speed
            result = subprocess.run(
                [
                    "git", "clone",
                    "--depth", "1",
                    "--filter=blob:none",
                    "--sparse",
                    repo["url"],
                    str(dest),
                ],
                capture_output=True, text=True, timeout=300,
            )

            if result.returncode != 0:
                # Fall back to regular shallow clone if sparse fails
                logger.warning(f"Sparse clone failed, trying regular clone...")
                shutil.rmtree(dest, ignore_errors=True)
                subprocess.run(
                    ["git", "clone", "--depth", "1", repo["url"], str(dest)],
                    capture_output=True, text=True, timeout=600,
                )

            if repo.get("sparse_path"):
                subprocess.run(
                    ["git", "sparse-checkout", "set", repo["sparse_path"]],
                    cwd=dest, capture_output=True, timeout=60,
                )

            logger.info(f"✅ Cloned {repo['name']}")
            return dest

        except subprocess.TimeoutExpired:
            logger.error(f"Clone timed out for {repo['name']}")
            shutil.rmtree(dest, ignore_errors=True)
            return None
        except Exception as e:
            logger.error(f"Clone failed for {repo['name']}: {e}")
            shutil.rmtree(dest, ignore_errors=True)
            return None

    # ── Solution Parsing ─────────────────────────────────────────────

    def _parse_walkccc(self, repo_dir: Path) -> Dict[str, dict]:
        """
        Parse walkccc/LeetCode repo structure:
          solutions/
            1. Two Sum/
              1.py
            2. Add Two Numbers/
              2.py
        """
        solutions = {}
        solutions_dir = repo_dir / "solutions"

        if not solutions_dir.exists():
            # Try alternate paths
            for alt in ["solutions", "src"]:
                alt_dir = repo_dir / alt
                if alt_dir.exists():
                    solutions_dir = alt_dir
                    break
            else:
                logger.warning(f"No solutions directory found in walkccc repo")
                return solutions

        for problem_dir in sorted(solutions_dir.iterdir()):
            if not problem_dir.is_dir():
                continue

            dirname = problem_dir.name
            match = re.match(r"(\d+)\.\s*(.+)", dirname)
            if not match:
                continue

            problem_id = match.group(1)
            title = match.group(2).strip()
            slug = self._title_to_slug(title)

            # Find the Python solution file
            py_files = list(problem_dir.glob("*.py"))
            if not py_files:
                continue

            # Prefer the file matching the problem ID
            solution_file = None
            for pf in py_files:
                if pf.stem == problem_id or pf.stem == slug:
                    solution_file = pf
                    break
            if not solution_file:
                solution_file = py_files[0]

            code = solution_file.read_text(encoding="utf-8", errors="ignore")
            if not code.strip():
                continue

            solutions[slug] = {
                "id": problem_id,
                "title": title,
                "slug": slug,
                "code": code,
                "source": "walkccc/LeetCode",
            }

        return solutions

    def _parse_neetcode(self, repo_dir: Path) -> Dict[str, dict]:
        """
        Parse neetcode-gh/leetcode repo structure:
          python/
            0001-two-sum.py
            0002-add-two-numbers.py
        """
        solutions = {}
        python_dir = repo_dir / "python"

        if not python_dir.exists():
            for alt in ["python", "Python", "py"]:
                alt_dir = repo_dir / alt
                if alt_dir.exists():
                    python_dir = alt_dir
                    break
            else:
                logger.warning("No python directory found in neetcode repo")
                return solutions

        for py_file in sorted(python_dir.glob("*.py")):
            name = py_file.stem
            match = re.match(r"(\d+)-(.+)", name)
            if match:
                problem_id = str(int(match.group(1)))  # Strip leading zeros
                slug = match.group(2)
            else:
                slug = name
                problem_id = "0"

            code = py_file.read_text(encoding="utf-8", errors="ignore")
            if not code.strip():
                continue

            title = slug.replace("-", " ").title()
            solutions[slug] = {
                "id": problem_id,
                "title": title,
                "slug": slug,
                "code": code,
                "source": "neetcode-gh/leetcode",
            }

        return solutions

    def _parse_kamyu104(self, repo_dir: Path) -> Dict[str, dict]:
        """
        Parse kamyu104/LeetCode-Solutions repo structure:
          Python/
            two-sum.py
            add-two-numbers.py
        """
        solutions = {}
        python_dir = repo_dir / "Python"

        if not python_dir.exists():
            for alt in ["Python", "python", "py"]:
                alt_dir = repo_dir / alt
                if alt_dir.exists():
                    python_dir = alt_dir
                    break
            else:
                return solutions

        for py_file in sorted(python_dir.glob("*.py")):
            slug = py_file.stem
            code = py_file.read_text(encoding="utf-8", errors="ignore")
            if not code.strip():
                continue

            title = slug.replace("-", " ").replace("_", " ").title()
            solutions[slug] = {
                "id": "0",
                "title": title,
                "slug": slug,
                "code": code,
                "source": "kamyu104/LeetCode-Solutions",
            }

        return solutions

    def _title_to_slug(self, title: str) -> str:
        """Convert a problem title to a URL slug."""
        slug = title.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"[\s]+", "-", slug)
        slug = re.sub(r"-+", "-", slug)
        return slug.strip("-")

    # ── LeetCode API: Community Solutions (Gap Filler) ───────────────

    def _fetch_community_solutions(
        self,
        session_token: Optional[str] = None,
        csrf_token: Optional[str] = None,
        slugs: Optional[List[str]] = None,
        batch_size: int = 50,
        delay: float = 1.0,
    ) -> Dict[str, dict]:
        """
        Fetch top community solutions from LeetCode's discuss API.
        Used to fill gaps not covered by the public repos.
        Rate-limited to avoid getting blocked.
        """
        if not session_token or not csrf_token:
            logger.info("No LeetCode tokens — skipping community solutions")
            return {}

        import requests

        solutions = {}
        session = requests.Session()
        session.cookies.set("LEETCODE_SESSION", session_token, domain=".leetcode.com")
        session.cookies.set("csrftoken", csrf_token, domain=".leetcode.com")
        session.headers.update({
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com",
            "x-csrftoken": csrf_token,
        })

        target_slugs = slugs or []
        if not target_slugs:
            return solutions

        logger.info(f"Fetching community solutions for {len(target_slugs)} problems...")

        for i, slug in enumerate(target_slugs[:batch_size]):
            try:
                query = """
                query communitySolutions($questionSlug: String!, $first: Int!, $orderBy: TopicSortingOption) {
                    questionSolutions(
                        questionSlug: $questionSlug
                        first: $first
                        orderBy: $orderBy
                    ) {
                        solutions {
                            id
                            title
                            post {
                                content
                            }
                            solutionTags {
                                name
                                slug
                            }
                        }
                    }
                }
                """
                resp = session.post(
                    "https://leetcode.com/graphql",
                    json={
                        "query": query,
                        "variables": {
                            "questionSlug": slug,
                            "first": 1,
                            "orderBy": "most_votes",
                        },
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                sols = data.get("data", {}).get("questionSolutions", {}).get("solutions", [])
                if sols:
                    content = sols[0].get("post", {}).get("content", "")
                    # Extract Python code from markdown
                    py_match = re.search(
                        r"```(?:python3?|py)\s*\n(.*?)```",
                        content, re.DOTALL | re.IGNORECASE,
                    )
                    if py_match:
                        code = py_match.group(1).strip()
                        solutions[slug] = {
                            "id": "0",
                            "title": slug.replace("-", " ").title(),
                            "slug": slug,
                            "code": code,
                            "source": "leetcode-community",
                        }

                if (i + 1) % 10 == 0:
                    logger.info(f"  Progress: {i + 1}/{len(target_slugs[:batch_size])}")

                time.sleep(delay)  # Rate limiting

            except Exception as e:
                logger.warning(f"Failed to fetch community solution for {slug}: {e}")
                continue

        return solutions

    # ── Slug Resolution via LeetCode API ─────────────────────────────

    def fetch_problem_slug_map(
        self,
        session_token: Optional[str] = None,
        csrf_token: Optional[str] = None,
    ) -> Dict[str, dict]:
        """
        Fetch the complete problem list from LeetCode to build an
        authoritative ID → slug mapping. This lets us match solutions
        from repos that use IDs vs slugs.
        """
        import requests

        slug_map = {}
        session = requests.Session()

        if session_token and csrf_token:
            session.cookies.set("LEETCODE_SESSION", session_token, domain=".leetcode.com")
            session.cookies.set("csrftoken", csrf_token, domain=".leetcode.com")
            session.headers.update({
                "Content-Type": "application/json",
                "Referer": "https://leetcode.com",
                "x-csrftoken": csrf_token,
            })

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
                    isPaidOnly
                }
            }
        }
        """

        total_fetched = 0
        skip = 0
        batch = 500

        logger.info("Fetching complete LeetCode problem list...")

        while True:
            try:
                resp = session.post(
                    "https://leetcode.com/graphql",
                    json={
                        "query": query,
                        "variables": {
                            "categorySlug": "all-code-essentials",
                            "limit": batch,
                            "skip": skip,
                            "filters": {},
                        },
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()

                questions = data["data"]["problemsetQuestionList"]["questions"]
                total = data["data"]["problemsetQuestionList"]["total"]

                for q in questions:
                    fid = q["questionFrontendId"]
                    slug_map[fid] = {
                        "id": q["questionId"],
                        "frontend_id": fid,
                        "title": q["title"],
                        "slug": q["titleSlug"],
                        "difficulty": q["difficulty"],
                        "paid": q["isPaidOnly"],
                    }
                    # Also index by slug for reverse lookups
                    slug_map[q["titleSlug"]] = slug_map[fid]

                total_fetched += len(questions)
                logger.info(f"  Fetched {total_fetched}/{total} problems...")

                if total_fetched >= total or not questions:
                    break

                skip += batch
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Failed to fetch problem list at skip={skip}: {e}")
                break

        # Save slug map
        slug_map_file = self.db_dir / "_slug_map.json"
        with open(slug_map_file, "w") as f:
            json.dump(slug_map, f, indent=2)
        logger.info(f"Slug map saved: {total_fetched} problems")

        return slug_map

    # ── Master Download Pipeline ─────────────────────────────────────

    def download_all(
        self,
        session_token: Optional[str] = None,
        csrf_token: Optional[str] = None,
        fetch_community: bool = False,
    ) -> Dict[str, int]:
        """
        Download ALL solutions from all sources and build the master index.

        Returns stats dict with counts per source.
        """
        stats = {}
        all_solutions: Dict[str, dict] = {}

        # ── Source 1: walkccc/LeetCode ───────────────────────────
        repo = SOLUTION_REPOS[0]
        repo_dir = self._clone_repo(repo)
        if repo_dir:
            walkccc_solutions = self._parse_walkccc(repo_dir)
            stats["walkccc"] = len(walkccc_solutions)
            all_solutions.update(walkccc_solutions)
            logger.info(f"📦 walkccc/LeetCode: {len(walkccc_solutions)} solutions")

        # ── Source 2: neetcode-gh/leetcode ────────────────────────
        repo = SOLUTION_REPOS[1]
        repo_dir = self._clone_repo(repo)
        if repo_dir:
            neetcode_solutions = self._parse_neetcode(repo_dir)
            # Only add if not already present (walkccc has priority)
            new_from_neetcode = 0
            for slug, sol in neetcode_solutions.items():
                if slug not in all_solutions:
                    all_solutions[slug] = sol
                    new_from_neetcode += 1
            stats["neetcode"] = new_from_neetcode
            logger.info(f"📦 neetcode-gh/leetcode: {new_from_neetcode} new solutions")

        # ── Source 3: kamyu104/LeetCode-Solutions ────────────────
        repo = SOLUTION_REPOS[2]
        repo_dir = self._clone_repo(repo)
        if repo_dir:
            kamyu_solutions = self._parse_kamyu104(repo_dir)
            new_from_kamyu = 0
            for slug, sol in kamyu_solutions.items():
                if slug not in all_solutions:
                    all_solutions[slug] = sol
                    new_from_kamyu += 1
            stats["kamyu104"] = new_from_kamyu
            logger.info(f"📦 kamyu104/LeetCode-Solutions: {new_from_kamyu} new solutions")

        # ── Source 4: LeetCode Community (optional, fills gaps) ──
        if fetch_community and session_token and csrf_token:
            # Get slug map first
            slug_map = self.fetch_problem_slug_map(session_token, csrf_token)

            # Find gaps
            all_slugs = set(v["slug"] for v in slug_map.values() if isinstance(v, dict) and "slug" in v)
            covered_slugs = set(all_solutions.keys())
            gap_slugs = list(all_slugs - covered_slugs)
            logger.info(f"Found {len(gap_slugs)} problems not covered by repos")

            if gap_slugs:
                community = self._fetch_community_solutions(
                    session_token, csrf_token, gap_slugs[:200]
                )
                for slug, sol in community.items():
                    if slug not in all_solutions:
                        all_solutions[slug] = sol
                stats["community"] = len(community)
                logger.info(f"📦 LeetCode Community: {len(community)} gap-fill solutions")

        # ── Write solutions to DB ────────────────────────────────
        logger.info(f"\n💾 Writing {len(all_solutions)} solutions to database...")
        solutions_code_dir = self.db_dir / "code"
        solutions_code_dir.mkdir(exist_ok=True)

        for slug, sol in all_solutions.items():
            # Save code file
            safe_name = re.sub(r"[^a-z0-9_-]", "_", slug)
            code_file = solutions_code_dir / f"{safe_name}.py"
            code_file.write_text(sol["code"], encoding="utf-8")

            # Add to index
            self.index[slug] = {
                "id": sol["id"],
                "title": sol["title"],
                "slug": slug,
                "file": f"code/{safe_name}.py",
                "source": sol["source"],
            }

        self._save_index()

        # ── Stats ────────────────────────────────────────────────
        stats["total"] = len(all_solutions)
        logger.info("\n" + "=" * 60)
        logger.info("📊 DOWNLOAD COMPLETE")
        logger.info("=" * 60)
        for source, count in stats.items():
            logger.info(f"  {source}: {count}")
        logger.info(f"  TOTAL INDEXED: {stats['total']}")
        logger.info("=" * 60)

        return stats

    # ── Lookup for the Daily Solver ──────────────────────────────────

    LANGUAGE_EXTENSIONS = {
        "python3": "py", "cpp": "cpp", "java": "java",
        "javascript": "js", "typescript": "ts", "go": "go", "rust": "rs",
    }

    def get_solution(self, slug: str, language: str = "python3") -> Optional[str]:
        """Look up a cached solution for the requested LeetCode language."""
        entry = self.index.get(slug)
        if not entry:
            return None
        language_entry = entry.get("languages", {}).get(language)
        relative_file = language_entry.get("file") if language_entry else None
        if not relative_file and language == "python3":
            relative_file = entry.get("file")
        if not relative_file:
            return None
        code_file = self.db_dir / relative_file
        if not code_file.exists():
            logger.warning("Indexed solution file is missing: %s", code_file)
            return None
        code = code_file.read_text(encoding="utf-8", errors="ignore")
        source = language_entry.get("source") if language_entry else entry.get("source", "legacy-db")
        logger.info("📦 DB hit: %s [%s] from %s", slug, language, source)
        return code

    def fetch_online_solution(
        self, slug: str, frontend_id: str, language: str = "python3",
        title: Optional[str] = None,
    ) -> Optional[dict]:
        """Fetch one language-specific solution from Doocs on demand and cache it.

        The upstream repository is CC-BY-SA-4.0. Attribution is retained in both
        the cached source file and index metadata. Candidates still require
        LeetCode sample validation before submission.
        """
        import requests
        extension = self.LANGUAGE_EXTENSIONS.get(language)
        if not extension:
            logger.info("No Doocs extension mapping for language %s", language)
            return None
        try:
            problem_number = int(frontend_id)
            lower = (problem_number // 100) * 100
            upper = lower + 99
            directory = f"solution/{lower:04d}-{upper:04d}"
            api_url = f"https://api.github.com/repos/doocs/leetcode/contents/{directory}"
            response = requests.get(api_url, headers={"Accept": "application/vnd.github+json"}, timeout=(5, 15))
            if response.status_code == 404:
                return None
            response.raise_for_status()
            folders = response.json()
            prefix = f"{problem_number}."
            problem_folder = next((item for item in folders if item.get("type") == "dir" and item.get("name", "").startswith(prefix)), None)
            if not problem_folder or not problem_folder.get("url"):
                return None
            folder_response = requests.get(problem_folder["url"], timeout=(5, 15))
            folder_response.raise_for_status()
            expected_name = f"Solution.{extension}"
            source_file = next((item for item in folder_response.json() if item.get("type") == "file" and item.get("name") == expected_name), None)
            if not source_file or not source_file.get("download_url"):
                return None
            code_response = requests.get(source_file["download_url"], timeout=(5, 20))
            code_response.raise_for_status()
            code = code_response.text.strip()
            if not code:
                return None

            source_url = source_file.get("html_url") or source_file["download_url"]
            comment_prefix = "#" if extension == "py" else "//"
            code = (
                f"{comment_prefix} Source: {source_url}\n"
                f"{comment_prefix} License: CC-BY-SA-4.0 (Doocs/leetcode)\n" + code
            )
            safe_slug = re.sub(r"[^a-z0-9_-]", "_", slug.lower())
            relative_file = f"code/{safe_slug}.{extension}"
            code_file = self.db_dir / relative_file
            code_file.parent.mkdir(parents=True, exist_ok=True)
            code_file.write_text(code, encoding="utf-8")
            entry = self.index.setdefault(slug, {
                "id": str(frontend_id), "title": title or slug.replace("-", " ").title(),
                "slug": slug, "languages": {},
            })
            entry.setdefault("languages", {})[language] = {
                "file": relative_file, "source": "doocs/leetcode",
                "source_url": source_url, "license": "CC-BY-SA-4.0",
                "language": language,
            }
            self._save_index()
            logger.info("🌐 Downloaded and cached %s solution for %s from Doocs", language, slug)
            return {"code": code, "source": "doocs/leetcode", "source_url": source_url,
                    "license": "CC-BY-SA-4.0", "language": language}
        except requests.RequestException as exc:
            logger.warning("Online solution lookup failed for %s: %s", slug, exc)
            return None
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("Could not parse Doocs solution for %s: %s", slug, exc)
            return None

    def get_stats(self) -> dict:
        """Return database statistics."""
        sources = {}
        for entry in self.index.values():
            src = entry.get("source", "unknown")
            sources[src] = sources.get(src, 0) + 1

        return {
            "total": len(self.index),
            "by_source": sources,
        }


# ── CLI Entry Point ──────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logger.info("🚀 LeetCode Bulk Solutions Downloader")
    logger.info("This will clone public repos and index ALL solutions.\n")

    session_token = os.environ.get("LEETCODE_SESSION")
    csrf_token = os.environ.get("LEETCODE_CSRF_TOKEN")
    fetch_community = os.environ.get("FETCH_COMMUNITY", "false").lower() == "true"

    downloader = BulkDownloader()
    stats = downloader.download_all(
        session_token=session_token,
        csrf_token=csrf_token,
        fetch_community=fetch_community,
    )

    print(f"\n✅ Done! {stats['total']} solutions indexed in {DB_DIR}")


if __name__ == "__main__":
    main()

