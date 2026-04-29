"""Query guardrails: flag queries that target sensitive information.

A triggered guardrail does NOT automatically block the query – the downstream
RBAC layer always has final say. A trigger simply means the event is recorded
with elevated scrutiny and the UI surfaces a warning banner.
"""
from typing import Tuple

SENSITIVE_PATTERNS = [
    "ceo salary",
    "executive salary",
    "executive compensation",
    "confidential",
    "classified",
    "password",
    "api key",
    "social security",
    "ssn",
    "termination",
    "layoff",
    "acquisition",
    "merger",
    "board minutes",
    "trade secret",
]


def check_query(query: str) -> Tuple[bool, str]:
    q = query.lower()
    for pattern in SENSITIVE_PATTERNS:
        if pattern in q:
            return True, f"Query matches sensitive pattern: '{pattern}'"
    return False, ""
