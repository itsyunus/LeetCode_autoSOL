"""Load and serialize the canonical LeetCode cookie pair.

The bundle is stored as one GitHub Actions secret so the session and CSRF
cookie cannot be split across two independent secret writes. Legacy secrets
remain supported during migration.
"""
import json
import os
from typing import Mapping, Optional, Tuple


def load_cookie_pair(environ: Optional[Mapping[str, str]] = None) -> Tuple[str, str]:
    env = environ if environ is not None else os.environ
    raw_bundle = (env.get("LEETCODE_COOKIE_BUNDLE") or "").strip()
    if raw_bundle:
        try:
            bundle = json.loads(raw_bundle)
        except (TypeError, ValueError) as exc:
            raise ValueError("LEETCODE_COOKIE_BUNDLE is not valid JSON.") from exc
        if not isinstance(bundle, dict):
            raise ValueError("LEETCODE_COOKIE_BUNDLE must contain a JSON object.")
        session = str(bundle.get("LEETCODE_SESSION") or "").strip()
        csrf = str(bundle.get("LEETCODE_CSRF_TOKEN") or "").strip()
    else:
        session = (env.get("LEETCODE_SESSION") or "").strip()
        csrf = (env.get("LEETCODE_CSRF_TOKEN") or "").strip()

    if not session or not csrf:
        raise ValueError(
            "Missing LeetCode cookie pair. Configure LEETCODE_COOKIE_BUNDLE "
            "or both legacy secrets LEETCODE_SESSION and LEETCODE_CSRF_TOKEN."
        )
    return session, csrf


def serialize_cookie_pair(session: str, csrf: str) -> str:
    session = (session or "").strip()
    csrf = (csrf or "").strip()
    if len(session) < 50:
        raise ValueError("Candidate LEETCODE_SESSION is empty or unexpectedly short.")
    if not csrf:
        raise ValueError("Candidate csrftoken is empty.")
    return json.dumps(
        {"LEETCODE_SESSION": session, "LEETCODE_CSRF_TOKEN": csrf},
        separators=(",", ":"),
        sort_keys=True,
    )
