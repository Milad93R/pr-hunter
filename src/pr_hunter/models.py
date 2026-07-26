from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def isoformat(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


@dataclass(slots=True)
class RepositorySignals:
    full_name: str
    html_url: str
    description: str
    language: str | None
    topics: tuple[str, ...]
    stars: int
    forks: int
    open_issues: int
    archived: bool
    pushed_at: datetime | None
    license_name: str | None = None
    community_health: int | None = None
    has_contributing: bool = False
    has_pr_template: bool = False
    recent_pr_count: int = 0
    recent_pr_merge_rate: float | None = None
    median_pr_close_days: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["topics"] = list(self.topics)
        data["pushed_at"] = isoformat(self.pushed_at)
        return data


@dataclass(slots=True)
class IssueCandidate:
    repo: RepositorySignals
    number: int
    title: str
    body: str
    html_url: str
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    author: str
    author_association: str
    comments_count: int
    created_at: datetime
    updated_at: datetime
    maintainer_comment_count: int = 0
    last_maintainer_comment_at: datetime | None = None
    claim_signals: tuple[str, ...] = ()
    linked_open_prs: tuple[str, ...] = ()
    linked_closed_prs: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.repo.full_name}#{self.number}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "repo": self.repo.to_dict(),
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "html_url": self.html_url,
            "labels": list(self.labels),
            "assignees": list(self.assignees),
            "author": self.author,
            "author_association": self.author_association,
            "comments_count": self.comments_count,
            "created_at": isoformat(self.created_at),
            "updated_at": isoformat(self.updated_at),
            "maintainer_comment_count": self.maintainer_comment_count,
            "last_maintainer_comment_at": isoformat(self.last_maintainer_comment_at),
            "claim_signals": list(self.claim_signals),
            "linked_open_prs": list(self.linked_open_prs),
            "linked_closed_prs": list(self.linked_closed_prs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueCandidate:
        repo_data = data["repo"]
        repo = RepositorySignals(
            full_name=repo_data["full_name"],
            html_url=repo_data["html_url"],
            description=repo_data.get("description") or "",
            language=repo_data.get("language"),
            topics=tuple(repo_data.get("topics") or ()),
            stars=int(repo_data.get("stars") or 0),
            forks=int(repo_data.get("forks") or 0),
            open_issues=int(repo_data.get("open_issues") or 0),
            archived=bool(repo_data.get("archived")),
            pushed_at=parse_datetime(repo_data.get("pushed_at")),
            license_name=repo_data.get("license_name"),
            community_health=repo_data.get("community_health"),
            has_contributing=bool(repo_data.get("has_contributing")),
            has_pr_template=bool(repo_data.get("has_pr_template")),
            recent_pr_count=int(repo_data.get("recent_pr_count") or 0),
            recent_pr_merge_rate=repo_data.get("recent_pr_merge_rate"),
            median_pr_close_days=repo_data.get("median_pr_close_days"),
        )
        return cls(
            repo=repo,
            number=int(data["number"]),
            title=data["title"],
            body=data.get("body") or "",
            html_url=data["html_url"],
            labels=tuple(data.get("labels") or ()),
            assignees=tuple(data.get("assignees") or ()),
            author=data.get("author") or "",
            author_association=data.get("author_association") or "NONE",
            comments_count=int(data.get("comments_count") or 0),
            created_at=parse_datetime(data["created_at"]) or datetime.now(UTC),
            updated_at=parse_datetime(data["updated_at"]) or datetime.now(UTC),
            maintainer_comment_count=int(data.get("maintainer_comment_count") or 0),
            last_maintainer_comment_at=parse_datetime(
                data.get("last_maintainer_comment_at")
            ),
            claim_signals=tuple(data.get("claim_signals") or ()),
            linked_open_prs=tuple(data.get("linked_open_prs") or ()),
            linked_closed_prs=tuple(data.get("linked_closed_prs") or ()),
        )


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    name: str
    points: int
    reason: str


@dataclass(slots=True)
class ScoreResult:
    total: int
    verdict: str
    components: list[ScoreComponent] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    hard_rejects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "verdict": self.verdict,
            "components": [asdict(component) for component in self.components],
            "risks": self.risks,
            "hard_rejects": self.hard_rejects,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoreResult:
        return cls(
            total=int(data["total"]),
            verdict=data["verdict"],
            components=[
                ScoreComponent(**component) for component in data.get("components", [])
            ],
            risks=list(data.get("risks", [])),
            hard_rejects=list(data.get("hard_rejects", [])),
        )


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: IssueCandidate
    score: ScoreResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "score": self.score.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Qualification:
    candidate_key: str
    reproduced: bool
    root_cause_confidence: str
    test_plan: bool
    ci_feasible: bool
    scope: str
    maintainer_signal: str
    notes: str
    readiness: str
    blockers: tuple[str, ...]
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_key": self.candidate_key,
            "reproduced": self.reproduced,
            "root_cause_confidence": self.root_cause_confidence,
            "test_plan": self.test_plan,
            "ci_feasible": self.ci_feasible,
            "scope": self.scope,
            "maintainer_signal": self.maintainer_signal,
            "notes": self.notes,
            "readiness": self.readiness,
            "blockers": list(self.blockers),
            "updated_at": isoformat(self.updated_at),
        }
