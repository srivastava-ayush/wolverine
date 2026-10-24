"""Persistent run state. Never store credentials or raw model prompts here."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

Status = Literal["investigating", "awaiting_approval", "approved", "published", "failed"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Evidence:
    id: str
    source: str
    modality: Literal["text", "tool"]
    trust: Literal["reported", "observed"]
    content: str
    created_at: str = field(default_factory=now)


@dataclass
class Run:
    id: str
    repo: str
    issue: int
    requester: str
    test_command: list[str]
    docker_image: str
    status: Status = "investigating"
    evidence: list[Evidence] = field(default_factory=list)
    summary: str = ""
    diff_hash: str = ""
    base_sha: str = ""
    head_sha: str = ""
    approved_by: str = ""
    pr_url: str = ""
    error: str = ""
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)

    @classmethod
    def new(cls, repo: str, issue: int, requester: str, command: list[str], image: str):
        return cls(uuid4().hex, repo, issue, requester, command, image)

    def add(self, source: str, trust: Literal["reported", "observed"], content: str):
        self.evidence.append(Evidence(f"e{len(self.evidence) + 1}", source,
                                      "tool" if trust == "observed" else "text",
                                      trust, content[:12000]))

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        data["evidence"] = [Evidence(**item) for item in data["evidence"]]
        return cls(**data)
