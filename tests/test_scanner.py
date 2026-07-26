import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from pr_hunter.github import GitHubError
from pr_hunter.scanner import Scanner


class RetryClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def search_issues(self, query, per_page):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class DiscoveryClient:
    def search_issues(self, query, per_page):
        return [
            self.issue("small/project", 1, "2026-07-26T12:00:00Z"),
            self.issue("large/project", 2, "2026-07-25T12:00:00Z"),
        ]

    @staticmethod
    def issue(repo, number, updated_at):
        return {
            "repository_url": f"https://api.github.com/repos/{repo}",
            "number": number,
            "title": "Fix a focused bug",
            "body": "Steps to reproduce and expected behavior.",
            "html_url": f"https://github.com/{repo}/issues/{number}",
            "labels": [{"name": "bug"}],
            "assignees": [],
            "user": {"login": "reporter"},
            "author_association": "CONTRIBUTOR",
            "comments": 0,
            "created_at": "2026-07-20T12:00:00Z",
            "updated_at": updated_at,
        }

    def repository(self, full_name):
        stars = 5 if full_name == "small/project" else 500
        return {
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "description": "Test repository",
            "language": "Go",
            "topics": [],
            "stargazers_count": stars,
            "forks_count": 0,
            "open_issues_count": 2,
            "archived": False,
            "pushed_at": "2026-07-26T12:00:00Z",
            "license": {"spdx_id": "MIT"},
        }


class ScannerRetryTests(unittest.TestCase):
    def scanner(self, client):
        config = SimpleNamespace(scan=SimpleNamespace(per_query=10))
        return Scanner(client, config)

    @patch("pr_hunter.scanner.time.sleep")
    def test_secondary_limit_honors_github_reset(self, sleep):
        error = GitHubError(
            "GitHub secondary rate limit",
            status_code=403,
            rate_limit_reset=datetime.now(UTC) + timedelta(seconds=45),
            rate_limit_remaining=0,
        )
        client = RetryClient([error, [{"number": 123}]])

        result = self.scanner(client)._search_with_retry("is:issue")

        self.assertEqual(result, [{"number": 123}])
        self.assertEqual(client.calls, 2)
        self.assertGreaterEqual(sleep.call_args.args[0], 45)

    @patch("pr_hunter.scanner.time.sleep")
    def test_secondary_limit_ignores_primary_reset_when_quota_remains(self, sleep):
        error = GitHubError(
            "GitHub secondary rate limit",
            status_code=403,
            rate_limit_reset=datetime.now(UTC) + timedelta(seconds=5),
            rate_limit_remaining=30,
        )
        client = RetryClient([error, []])

        self.scanner(client)._search_with_retry("is:issue")

        self.assertGreaterEqual(sleep.call_args.args[0], 60)

    @patch("pr_hunter.scanner.time.sleep")
    def test_non_rate_limit_error_is_not_retried(self, sleep):
        client = RetryClient(
            [GitHubError("GitHub GET failed: HTTP 500", status_code=500)]
        )

        with self.assertRaises(GitHubError):
            self.scanner(client)._search_with_retry("is:issue")

        self.assertEqual(client.calls, 1)
        sleep.assert_not_called()

    def test_scan_enforces_repository_star_floor_after_search(self):
        scan = SimpleNamespace(
            queries=("is:issue is:open",),
            per_query=10,
            max_candidates=1,
            enrich_top=0,
            min_repo_stars=100,
            search_delay_seconds=0,
        )
        profile = SimpleNamespace(
            languages=("Go",),
            topics=(),
            exclude_topics=(),
            preferred_issue_terms=("bug",),
            deprioritize_issue_terms=(),
        )
        config = SimpleNamespace(scan=scan, profile=profile)

        results = Scanner(DiscoveryClient(), config).scan()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].candidate.repo.full_name, "large/project")
