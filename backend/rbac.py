"""RBAC + ABAC policy enforcement.

Filtering happens BEFORE similarity search (pre-filter pipeline):
    filter -> retrieve -> re-rank -> validate.

A user may access a document iff ALL the following hold:
  1. RBAC: user.role is in doc.role_access
  2. ABAC department: doc.department == "All" OR doc.department == user.department
     (admins can see every department)
  3. ABAC clearance: sensitivity rank(user.clearance) >= rank(doc.sensitivity)
"""
from typing import List
from models import UserPublic

SENSITIVITY_RANK = {"low": 1, "medium": 2, "high": 3}


def user_can_access(user: UserPublic, doc: dict) -> bool:
    # 1. Role-Based Access Control
    if user.role not in doc.get("role_access", []):
        return False

    # 2. Department (ABAC). Admins see all departments.
    if user.role != "admin":
        doc_dept = doc.get("department", "All")
        if doc_dept != "All" and doc_dept != user.department:
            return False

    # 3. Sensitivity clearance (ABAC)
    user_rank = SENSITIVITY_RANK.get(user.clearance, 1)
    doc_rank = SENSITIVITY_RANK.get(doc.get("sensitivity", "low"), 1)
    if doc_rank > user_rank:
        return False

    return True


def filter_documents(user: UserPublic, docs: List[dict]) -> (List[dict], int):
    """Returns (allowed_docs, filtered_out_count). Pre-search filtering."""
    allowed = [d for d in docs if user_can_access(user, d)]
    filtered_out = len(docs) - len(allowed)
    return allowed, filtered_out
