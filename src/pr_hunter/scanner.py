from __future__ import annotations

import re
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pr_hunter.config import AppConfig
from pr_hunter.github import (
    GitHubClient,
    GitHubError,
    issue_from_api,
    repository_from_api,
)
from pr_hunter.models import IssueCandidate, RankedCandidate, parse_datetime
from pr_hunter.scoring import score_candidate

MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
CLAIM_PATTERN = re.compile(
    r"\b("
    r"i(?:'m| am) working on (?:this|it)"
    r"|i(?: can| would like to) work on (?:this|it)"
    r"|i(?:'ll| will) take (?:this|it)"
    r"|please assign (?:this|it) to me"
    r"|/assign"
    r")\b",
    re.IGNORECASE,
)


class Scanner:
    def __init__(
        self,
        client: GitHubClient,
        config: AppConfig,
        progress: Callable[[str], None] | None = None,
    ):
        self.client = client
        self.config = config
        self.progress = progress or (lambda _: None)
        self._repositories: dict[str, Any] = {}
        self._community: set[str] = set()
        self._pull_history: set[str] = set()

    def _queries(self) -> list[str]:
        queries: list[str] = []
        for base in self.config.scan.queries:
            for language in self.config.profile.languages:
                parts = [
                    base,
                    f'language:"{language}"',
                    f"stars:>={self.config.scan.min_repo_stars}",
                ]
                queries.append(" ".join(parts))
        return queries

    def scan(
        self,
        *,
        limit: int | None = None,
        enrich_top: int | None = None,
    ) -> list[RankedCandidate]:
        limit = limit or self.config.scan.max_candidates
        enrich_top = self.config.scan.enrich_top if enrich_top is None else enrich_top
        raw_issues: dict[str, dict[str, Any]] = {}
        queries = self._queries()
        for index, query in enumerate(queries, 1):
            self.progress(f"search {index}/{len(queries)}: {query}")
            for item in self._search_with_retry(query):
                repo_name = item["repository_url"].rsplit("/", 2)[-2:]
                key = f"{'/'.join(repo_name)}#{item['number']}"
                raw_issues[key] = item
            if index < len(queries) and self.config.scan.search_delay_seconds > 0:
                time.sleep(self.config.scan.search_delay_seconds)

        ordered_items = sorted(
            raw_issues.values(),
            key=lambda item: item.get("updated_at") or "",
            reverse=True,
        )
        candidates: list[IssueCandidate] = []
        for index, item in enumerate(ordered_items, 1):
            if len(candidates) >= limit:
                break
            repo_name = "/".join(item["repository_url"].rsplit("/", 2)[-2:])
            self.progress(f"repository {index}/{len(ordered_items)}: {repo_name}")
            repository = self._repository(repo_name)
            if repository.stars < self.config.scan.min_repo_stars:
                self.progress(
                    f"skip {repo_name}: {repository.stars} stars is below "
                    f"the {self.config.scan.min_repo_stars}-star floor"
                )
                continue
            candidates.append(issue_from_api(item, repository))

        preliminary = [
            RankedCandidate(
                candidate,
                score_candidate(candidate, self.config.profile),
            )
            for candidate in candidates
        ]
        preliminary.sort(key=lambda item: item.score.total, reverse=True)

        for index, ranked in enumerate(preliminary[:enrich_top], 1):
            self.progress(
                f"enrich {index}/{min(enrich_top, len(preliminary))}: "
                f"{ranked.candidate.key}"
            )
            self._enrich_repository(ranked.candidate.repo)
            self._enrich_issue(ranked.candidate)

        final = [
            RankedCandidate(
                ranked.candidate,
                score_candidate(ranked.candidate, self.config.profile),
            )
            for ranked in preliminary
        ]
        final.sort(key=lambda item: item.score.total, reverse=True)
        return final

    def _search_with_retry(self, query: str) -> list[dict[str, Any]]:
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                return self.client.search_issues(query, self.config.scan.per_query)
            except GitHubError as error:
                secondary_limit = "secondary rate limit" in str(error).casefold()
                if not secondary_limit or attempt == max_attempts - 1:
                    raise
                delay = float(60 * (2**attempt))
                if error.retry_after is not None:
                    delay = max(delay, error.retry_after + 1)
                if (
                    error.rate_limit_reset is not None
                    and error.rate_limit_remaining in (None, 0)
                ):
                    reset_delay = (
                        error.rate_limit_reset - datetime.now(UTC)
                    ).total_seconds()
                    delay = max(delay, reset_delay + 1)
                delay = min(300.0, max(1.0, delay))
                self.progress(f"GitHub secondary throttle; retrying in {delay:.0f}s")
                time.sleep(delay)
        return []

    def _repository(self, full_name: str):
        if full_name not in self._repositories:
            self._repositories[full_name] = repository_from_api(
                self.client.repository(full_name)
            )
        return self._repositories[full_name]

    def _enrich_repository(self, repo) -> None:
        if repo.full_name not in self._community:
            community = self.client.community_profile(repo.full_name) or {}
            files = community.get("files") or {}
            repo.community_health = community.get("health_percentage")
            repo.has_contributing = bool(files.get("contributing"))
            repo.has_pr_template = bool(files.get("pull_request_template"))
            self._community.add(repo.full_name)

        if repo.full_name not in self._pull_history:
            pulls = self.client.recent_closed_pulls(repo.full_name)
            repo.recent_pr_count = len(pulls)
            if pulls:
                merged = sum(bool(pull.get("merged_at")) for pull in pulls)
                repo.recent_pr_merge_rate = merged / len(pulls)
                close_days: list[float] = []
                for pull in pulls:
                    created = parse_datetime(pull.get("created_at"))
                    closed = parse_datetime(pull.get("closed_at"))
                    if created and closed:
                        close_days.append(
                            max(0.0, (closed - created).total_seconds() / 86_400)
                        )
                if close_days:
                    repo.median_pr_close_days = statistics.median(close_days)
            self._pull_history.add(repo.full_name)

    def _enrich_issue(self, candidate: IssueCandidate) -> None:
        comments = self.client.issue_comments(
            candidate.repo.full_name, candidate.number
        )
        maintainer_dates = [
            parse_datetime(comment.get("created_at"))
            for comment in comments
            if comment.get("author_association") in MAINTAINER_ASSOCIATIONS
        ]
        maintainer_dates = [date for date in maintainer_dates if date]
        candidate.maintainer_comment_count = len(maintainer_dates)
        candidate.last_maintainer_comment_at = (
            max(maintainer_dates) if maintainer_dates else None
        )

        recent_cutoff = datetime.now(UTC) - timedelta(days=120)
        claims: list[str] = []
        for comment in comments:
            created = parse_datetime(comment.get("created_at"))
            if not created or created < recent_cutoff:
                continue
            body = comment.get("body") or ""
            if CLAIM_PATTERN.search(body):
                login = (comment.get("user") or {}).get("login") or "unknown"
                claims.append(f"{login}: {body[:120].strip()}")
        candidate.claim_signals = tuple(claims)

        timeline = self.client.issue_timeline(
            candidate.repo.full_name, candidate.number
        )
        open_prs: list[str] = []
        closed_prs: list[str] = []
        for event in timeline:
            if event.get("event") != "cross-referenced":
                continue
            source_issue = (event.get("source") or {}).get("issue") or {}
            if not source_issue.get("pull_request"):
                continue
            url = source_issue.get("html_url")
            if not url:
                continue
            if source_issue.get("state") == "open":
                open_prs.append(url)
            else:
                closed_prs.append(url)
        candidate.linked_open_prs = tuple(dict.fromkeys(open_prs))
        candidate.linked_closed_prs = tuple(dict.fromkeys(closed_prs))
