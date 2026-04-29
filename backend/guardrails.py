"""Query guardrails with word-boundary regex matching (fewer false positives)."""
import re
from typing import Tuple

SENSITIVE_PATTERNS = [
    r"ceo salary",
    r"executive salary",
    r"executive compensation",
    r"confidential",
    r"classified",
    r"password",
    r"api key",
    r"social security",
    r"ssn",
    r"termination",
    r"layoff",
    r"acquisition",
    r"merger",
    r"board minutes",
    r"trade secret",
]

# Precompile one regex that uses word boundaries so `ssn` won't match `lessons`.
_COMPILED = re.compile(
    r"\b(?:" + "|".join(SENSITIVE_PATTERNS) + r")\b",
    flags=re.IGNORECASE,
)


def check_query(query: str) -> Tuple[bool, str]:
    m = _COMPILED.search(query or "")
    if m:
        return True, f"Query matches sensitive pattern: '{m.group(0).lower()}'"
    return False, ""
