"""Pydantic models for the Policy-Aware RAG system."""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime, timezone
import uuid


Role = Literal["admin", "manager", "employee", "intern"]
Sensitivity = Literal["low", "medium", "high"]


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    password_hash: str
    role: Role
    department: str
    clearance: Sensitivity = "low"
    full_name: str


class UserPublic(BaseModel):
    id: str
    username: str
    role: Role
    department: str
    clearance: Sensitivity
    full_name: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class Document(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    content: str
    role_access: List[Role]
    department: str  # "All" means any department
    sensitivity: Sensitivity
    uploaded_by: str  # username
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentCreate(BaseModel):
    title: str
    content: str
    role_access: List[Role]
    department: str = "All"
    sensitivity: Sensitivity = "low"


class DocumentPublic(BaseModel):
    id: str
    title: str
    content: str
    role_access: List[Role]
    department: str
    sensitivity: Sensitivity
    uploaded_by: str
    uploaded_at: datetime


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class Citation(BaseModel):
    doc_id: str
    title: str
    department: str
    sensitivity: Sensitivity
    score: float


class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]
    access_decision: Literal["granted", "denied", "partial"]
    guardrail_triggered: bool
    guardrail_reason: Optional[str] = None
    filtered_out_count: int = 0  # how many docs were excluded by policy
    session_id: str


class AuditLog(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    role: Role
    department: str
    query: str
    access: Literal["granted", "denied", "partial"]
    guardrail_triggered: bool
    cited_doc_ids: List[str] = []
    filtered_out_count: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
