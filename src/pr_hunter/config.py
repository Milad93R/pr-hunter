from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_QUERIES = (
    'is:issue is:open no:assignee label:"help wanted"',
    'is:issue is:open no:assignee label:"good first issue"',
    'is:issue is:open no:assignee label:bug label:"help wanted"',
)
DEFAULT_PREFERRED_ISSUE_TERMS = (
    "bug",
    "fix",
    "regression",
    "performance",
    "security",
    "reliability",
    "backend",
    "api",
    "test",
)
DEFAULT_DEPRIORITIZE_ISSUE_TERMS = (
    "wikipedia",
    "video",
    "marketing",
    "social media",
    "translation",
    "bounty",
    "blog post",
    "strategist",
    "positioning narrative",
)


@dataclass(frozen=True, slots=True)
class ContributorProfile:
    name: str
    languages: tuple[str, ...]
    topics: tuple[str, ...]
    exclude_topics: tuple[str, ...]
    preferred_issue_terms: tuple[str, ...]
    deprioritize_issue_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScanConfig:
    queries: tuple[str, ...]
    per_query: int
    max_candidates: int
    enrich_top: int
    min_repo_stars: int
    search_delay_seconds: float
    state_path: Path


@dataclass(frozen=True, slots=True)
class AIProfile:
    base_url: str
    model: str
    api_key_env: str


@dataclass(frozen=True, slots=True)
class AIConfig:
    enabled: bool
    scout: AIProfile | None
    reviewer: AIProfile | None


@dataclass(frozen=True, slots=True)
class AppConfig:
    profile: ContributorProfile
    scan: ScanConfig
    ai: AIConfig


def _tuple_strings(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Expected a list of strings in configuration")
    return tuple(value)


def _ai_profile(data: dict[str, Any] | None) -> AIProfile | None:
    if not data:
        return None
    required = ("base_url", "model", "api_key_env")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f"AI profile missing: {', '.join(missing)}")
    return AIProfile(
        base_url=str(data["base_url"]).rstrip("/"),
        model=str(data["model"]),
        api_key_env=str(data["api_key_env"]),
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    data: dict[str, Any] = {}
    base_dir = Path.cwd()
    if path:
        config_path = Path(path).expanduser().resolve()
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
        base_dir = config_path.parent

    profile_data = data.get("profile", {})
    scan_data = data.get("scan", {})
    ai_data = data.get("ai", {})

    state_value = scan_data.get("state_path", ".prhunter/state.db")
    state_path = Path(state_value).expanduser()
    if not state_path.is_absolute():
        state_path = (base_dir / state_path).resolve()

    profile = ContributorProfile(
        name=str(profile_data.get("name", "Contributor")),
        languages=_tuple_strings(
            profile_data.get("languages"), ("Go", "TypeScript", "Python")
        ),
        topics=_tuple_strings(
            profile_data.get("topics"),
            (
                "ai",
                "llm",
                "backend",
                "database",
                "kubernetes",
                "observability",
                "security",
            ),
        ),
        exclude_topics=_tuple_strings(
            profile_data.get("exclude_topics"),
            ("blockchain", "web3", "nft"),
        ),
        preferred_issue_terms=_tuple_strings(
            profile_data.get("preferred_issue_terms"),
            DEFAULT_PREFERRED_ISSUE_TERMS,
        ),
        deprioritize_issue_terms=_tuple_strings(
            profile_data.get("deprioritize_issue_terms"),
            DEFAULT_DEPRIORITIZE_ISSUE_TERMS,
        ),
    )
    scan = ScanConfig(
        queries=_tuple_strings(scan_data.get("queries"), DEFAULT_QUERIES),
        per_query=max(1, min(100, int(scan_data.get("per_query", 10)))),
        max_candidates=max(1, min(200, int(scan_data.get("max_candidates", 35)))),
        enrich_top=max(0, min(50, int(scan_data.get("enrich_top", 10)))),
        min_repo_stars=max(0, int(scan_data.get("min_repo_stars", 100))),
        search_delay_seconds=max(
            0.0,
            min(60.0, float(scan_data.get("search_delay_seconds", 31.0))),
        ),
        state_path=state_path,
    )
    ai = AIConfig(
        enabled=bool(ai_data.get("enabled", False)),
        scout=_ai_profile(ai_data.get("scout")),
        reviewer=_ai_profile(ai_data.get("reviewer")),
    )
    return AppConfig(profile=profile, scan=scan, ai=ai)
