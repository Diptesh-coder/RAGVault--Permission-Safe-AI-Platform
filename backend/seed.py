"""Seed initial users and documents on application startup (idempotent)."""
from datetime import datetime, timezone
from models import User, Document
from auth import hash_password


SEED_USERS = [
    {
        "username": "alice",
        "password": "admin123",
        "role": "admin",
        "department": "Executive",
        "clearance": "high",
        "full_name": "Alice Chen",
    },
    {
        "username": "bob",
        "password": "manager123",
        "role": "manager",
        "department": "Finance",
        "clearance": "high",
        "full_name": "Bob Martinez",
    },
    {
        "username": "carol",
        "password": "emp123",
        "role": "employee",
        "department": "Engineering",
        "clearance": "medium",
        "full_name": "Carol Singh",
    },
    {
        "username": "dave",
        "password": "intern123",
        "role": "intern",
        "department": "Engineering",
        "clearance": "low",
        "full_name": "Dave Park",
    },
]


SEED_DOCS = [
    {
        "title": "CEO Compensation Package 2026",
        "content": (
            "The CEO's total annual compensation for fiscal year 2026 is $4.8M, "
            "comprising $1.2M base salary, $2.1M performance bonus tied to ARR growth "
            "above 40%, and $1.5M in restricted stock units vesting over four years. "
            "This document is confidential and restricted to executive administrators."
        ),
        "role_access": ["admin"],
        "department": "Executive",
        "sensitivity": "high",
    },
    {
        "title": "Q4 2025 Finance Report",
        "content": (
            "Q4 revenue reached $142M, a 38% YoY increase. Operating margin expanded "
            "to 22.4%. Key drivers: enterprise expansion (+$24M) and the EMEA launch. "
            "Cash reserves stand at $410M. Finance managers and executives only."
        ),
        "role_access": ["admin", "manager"],
        "department": "Finance",
        "sensitivity": "high",
    },
    {
        "title": "Engineering Roadmap H1 2026",
        "content": (
            "H1 2026 engineering priorities: (1) multi-region failover for the core "
            "platform, (2) migration from REST to gRPC for internal services, "
            "(3) a dedicated RAG security workstream, (4) rollout of the new design "
            "system. Target GA date for the multi-region failover is April 2026."
        ),
        "role_access": ["admin", "manager", "employee"],
        "department": "Engineering",
        "sensitivity": "medium",
    },
    {
        "title": "Company Leave Policy",
        "content": (
            "All full-time employees receive 22 days of paid leave annually plus 10 "
            "public holidays. Interns receive 8 days of paid leave per six-month term. "
            "Leave must be requested at least two weeks in advance via the HR portal. "
            "Unused leave does not roll over beyond December 31."
        ),
        "role_access": ["admin", "manager", "employee", "intern"],
        "department": "All",
        "sensitivity": "low",
    },
    {
        "title": "Intern Onboarding Handbook",
        "content": (
            "Welcome to the program. Your first week includes orientation (day 1), "
            "dev environment setup (day 2), a codebase tour (day 3), and pairing "
            "sessions (days 4-5). Interns are paired with a mentor and receive weekly "
            "1:1 feedback. The program lasts 12 weeks."
        ),
        "role_access": ["admin", "manager", "employee", "intern"],
        "department": "All",
        "sensitivity": "low",
    },
    {
        "title": "Security Incident Retrospective SI-2026-014",
        "content": (
            "On 2026-01-17 an unauthorized access attempt was detected on the staging "
            "RAG pipeline. Root cause: a leaked internal token in a committed dotfile. "
            "Remediation: token rotation, secret-scanning pre-commit hooks, and the "
            "introduction of hardware-bound keys for production. No customer data was "
            "exposed."
        ),
        "role_access": ["admin"],
        "department": "Security",
        "sensitivity": "high",
    },
    {
        "title": "2026 Marketing Strategy",
        "content": (
            "Focus markets: North America (enterprise upmarket) and DACH (mid-market). "
            "Flagship campaign: 'Policy-Aware AI' thought leadership series with three "
            "whitepapers and a virtual summit in May. Paid budget: $6.2M. Expected CAC "
            "payback: 11 months."
        ),
        "role_access": ["admin", "manager"],
        "department": "Marketing",
        "sensitivity": "medium",
    },
    {
        "title": "Code of Conduct",
        "content": (
            "We are committed to a respectful, inclusive, harassment-free workplace. "
            "Report concerns to your manager or to the ethics hotline. Retaliation is "
            "strictly prohibited. This policy applies to all personnel regardless of "
            "role or tenure."
        ),
        "role_access": ["admin", "manager", "employee", "intern"],
        "department": "All",
        "sensitivity": "low",
    },
]


async def seed_database(db):
    # Users
    for u in SEED_USERS:
        existing = await db.users.find_one({"username": u["username"]})
        if existing:
            continue
        user = User(
            username=u["username"],
            password_hash=hash_password(u["password"]),
            role=u["role"],
            department=u["department"],
            clearance=u["clearance"],
            full_name=u["full_name"],
        )
        await db.users.insert_one(user.model_dump())

    # Documents
    for d in SEED_DOCS:
        existing = await db.documents.find_one({"title": d["title"]})
        if existing:
            continue
        doc = Document(
            title=d["title"],
            content=d["content"],
            role_access=d["role_access"],
            department=d["department"],
            sensitivity=d["sensitivity"],
            uploaded_by="system",
        )
        doc_dict = doc.model_dump()
        doc_dict["uploaded_at"] = doc_dict["uploaded_at"].isoformat()
        await db.documents.insert_one(doc_dict)
