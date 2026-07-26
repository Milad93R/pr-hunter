from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from pr_hunter.models import IssueCandidate, RepositorySignals, parse_datetime


class GitHubError(RuntimeError):
    """A GitHub API request failed."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        rate_limit_reset: datetime | None = None,
        rate_limit_remaining: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.rate_limit_reset = rate_limit_reset
        self.rate_limit_remaining = rate_limit_remaining
        self.retry_after = retry_after


class GitHubClient:
    """Small read-only GitHub REST client.

    This class intentionally exposes GET operations only.
    """

    api_root = "https://api.github.com"

    def __init__(self, token: str | None = None, timeout: int = 30):
        self.token = token or self._discover_token()
        self.timeout = timeout

    @staticmethod
    def _discover_token() -> str | None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            return token.strip()
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() or None

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
        allow_not_found: bool = False,
    ) -> Any:
        url = path if path.startswith("https://") else f"{self.api_root}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
        headers = {
            "Accept": accept,
            "User-Agent": "pr-hunter/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and allow_not_found:
                return None
            body = error.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(body).get("message", body)
            except json.JSONDecodeError:
                message = body
            reset = error.headers.get("X-RateLimit-Reset")
            reset_at = None
            suffix = ""
            if reset and reset.isdigit():
                reset_at = datetime.fromtimestamp(int(reset), tz=UTC)
                suffix = f" (rate limit resets at {reset_at.isoformat()})"
            remaining = error.headers.get("X-RateLimit-Remaining")
            rate_limit_remaining = None
            if remaining and remaining.isdigit():
                rate_limit_remaining = int(remaining)
            retry_after = None
            retry_after_header = error.headers.get("Retry-After")
            if retry_after_header:
                try:
                    retry_after = max(0.0, float(retry_after_header))
                except ValueError:
                    pass
            raise GitHubError(
                f"GitHub GET {path} failed: HTTP {error.code}: {message}{suffix}",
                status_code=error.code,
                rate_limit_reset=reset_at,
                rate_limit_remaining=rate_limit_remaining,
                retry_after=retry_after,
            ) from error
        except urllib.error.URLError as error:
            raise GitHubError(f"GitHub GET {path} failed: {error.reason}") from error

    def search_issues(self, query: str, per_page: int) -> list[dict[str, Any]]:
        data = self.get(
            "/search/issues",
            params={
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": per_page,
            },
        )
        return list(data.get("items", []))

    def repository(self, full_name: str) -> dict[str, Any]:
        return self.get(f"/repos/{full_name}")

    def community_profile(self, full_name: str) -> dict[str, Any] | None:
        return self.get(
            f"/repos/{full_name}/community/profile",
            allow_not_found=True,
        )

    def issue_comments(self, full_name: str, number: int) -> list[dict[str, Any]]:
        data = self.get(
            f"/repos/{full_name}/issues/{number}/comments",
            params={"per_page": 100},
        )
        return list(data)

    def issue_timeline(self, full_name: str, number: int) -> list[dict[str, Any]]:
        data = self.get(
            f"/repos/{full_name}/issues/{number}/timeline",
            params={"per_page": 100},
            accept="application/vnd.github+json",
        )
        return list(data)

    def recent_closed_pulls(
        self, full_name: str, per_page: int = 30
    ) -> list[dict[str, Any]]:
        data = self.get(
            f"/repos/{full_name}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": per_page,
            },
        )
        return list(data)


def repository_from_api(data: dict[str, Any]) -> RepositorySignals:
    license_data = data.get("license") or {}
    return RepositorySignals(
        full_name=data["full_name"],
        html_url=data["html_url"],
        description=data.get("description") or "",
        language=data.get("language"),
        topics=tuple(data.get("topics") or ()),
        stars=int(data.get("stargazers_count") or 0),
        forks=int(data.get("forks_count") or 0),
        open_issues=int(data.get("open_issues_count") or 0),
        archived=bool(data.get("archived")),
        pushed_at=parse_datetime(data.get("pushed_at")),
        license_name=license_data.get("spdx_id") or license_data.get("name"),
    )


def issue_from_api(
    data: dict[str, Any], repository: RepositorySignals
) -> IssueCandidate:
    labels = tuple(
        label["name"] if isinstance(label, dict) else str(label)
        for label in data.get("labels", [])
    )
    assignees = tuple(
        user.get("login", "")
        for user in data.get("assignees", [])
        if isinstance(user, dict)
    )
    author_data = data.get("user") or {}
    return IssueCandidate(
        repo=repository,
        number=int(data["number"]),
        title=data["title"],
        body=data.get("body") or "",
        html_url=data["html_url"],
        labels=labels,
        assignees=assignees,
        author=author_data.get("login") or "",
        author_association=data.get("author_association") or "NONE",
        comments_count=int(data.get("comments") or 0),
        created_at=parse_datetime(data.get("created_at")) or datetime.now(UTC),
        updated_at=parse_datetime(data.get("updated_at")) or datetime.now(UTC),
    )
