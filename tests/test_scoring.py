from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from pr_hunter.config import ContributorProfile
from pr_hunter.models import IssueCandidate, RepositorySignals
from pr_hunter.scoring import score_candidate

NOW = datetime(2026, 7, 26, tzinfo=UTC)
PROFILE = ContributorProfile(
    name="Milad",
    languages=("Go", "TypeScript", "Python"),
    topics=("ai", "kubernetes", "observability", "security"),
    exclude_topics=("blockchain", "web3"),
    preferred_issue_terms=("bug", "fix", "regression", "security", "test"),
    deprioritize_issue_terms=("wikipedia", "video", "marketing", "bounty"),
)


def candidate(**overrides):
    repo = RepositorySignals(
        full_name="example/active-project",
        html_url="https://github.com/example/active-project",
        description="Production AI infrastructure",
        language="Go",
        topics=("ai", "kubernetes"),
        stars=5_000,
        forks=500,
        open_issues=120,
        archived=False,
        pushed_at=NOW - timedelta(days=3),
        community_health=100,
        has_contributing=True,
        has_pr_template=True,
        recent_pr_count=30,
        recent_pr_merge_rate=0.7,
        median_pr_close_days=9.0,
    )
    values = {
        "repo": repo,
        "number": 42,
        "title": "Fix retry loop after context cancellation",
        "body": (
            "Steps to reproduce: run `worker.go` with a cancelled context. "
            "Expected behavior: retry stops. Actual behavior: it loops. "
            "A regression test should cover the failing path. " * 4
        ),
        "html_url": "https://github.com/example/active-project/issues/42",
        "labels": ("bug", "help wanted"),
        "assignees": (),
        "author": "reporter",
        "author_association": "CONTRIBUTOR",
        "comments_count": 4,
        "created_at": NOW - timedelta(days=30),
        "updated_at": NOW - timedelta(days=2),
        "maintainer_comment_count": 2,
        "last_maintainer_comment_at": NOW - timedelta(days=1),
    }
    values.update(overrides)
    return IssueCandidate(**values)


class ScoringTests(unittest.TestCase):
    def test_strong_candidate_scores_high(self):
        result = score_candidate(candidate(), PROFILE, now=NOW)
        self.assertGreaterEqual(result.total, 80)
        self.assertEqual(result.verdict, "strong")
        self.assertEqual(result.hard_rejects, [])

    def test_assigned_issue_is_hard_rejected(self):
        result = score_candidate(
            candidate(assignees=("another-contributor",)), PROFILE, now=NOW
        )
        self.assertEqual(result.verdict, "skip")
        self.assertLessEqual(result.total, 35)
        self.assertTrue(any("assigned" in reason for reason in result.hard_rejects))

    def test_linked_open_pr_is_hard_rejected(self):
        result = score_candidate(
            candidate(
                linked_open_prs=("https://github.com/example/active-project/pull/77",)
            ),
            PROFILE,
            now=NOW,
        )
        self.assertEqual(result.verdict, "skip")
        self.assertTrue(any("pull request" in reason for reason in result.hard_rejects))

    def test_excluded_topic_is_penalized(self):
        item = candidate()
        item.repo.topics = ("blockchain", "web3")
        result = score_candidate(item, PROFILE, now=NOW)
        exclusions = [
            component
            for component in result.components
            if component.name == "topic-exclusion"
        ]
        self.assertEqual(len(exclusions), 1)
        self.assertLess(exclusions[0].points, 0)

    def test_non_engineering_work_is_deprioritized(self):
        result = score_candidate(
            candidate(
                title="Create a Wikipedia page and marketing video",
                labels=("documentation", "help wanted"),
            ),
            PROFILE,
            now=NOW,
        )
        work_type = [
            component
            for component in result.components
            if component.name == "work-type"
        ]
        self.assertEqual(len(work_type), 1)
        self.assertEqual(work_type[0].points, -20)
        engineering_score = score_candidate(candidate(), PROFILE, now=NOW)
        self.assertLess(result.total, engineering_score.total)
        self.assertLessEqual(result.total, 59)
        self.assertEqual(result.verdict, "investigate")

    def test_deprioritized_work_is_not_promoted_from_skip(self):
        item = candidate(
            title="Bounty: make a marketing video",
            labels=("bounty",),
            body="Thin request.",
            comments_count=40,
            created_at=NOW - timedelta(days=900),
            updated_at=NOW - timedelta(days=800),
            maintainer_comment_count=0,
        )
        item.repo.language = "Rust"
        item.repo.topics = ("blockchain", "web3")
        item.repo.stars = 0
        item.repo.pushed_at = NOW - timedelta(days=800)
        item.repo.community_health = None
        item.repo.has_contributing = False
        item.repo.has_pr_template = False
        item.repo.recent_pr_merge_rate = 0.0
        item.repo.median_pr_close_days = 200

        result = score_candidate(item, PROFILE, now=NOW)

        self.assertEqual(result.verdict, "skip")


if __name__ == "__main__":
    unittest.main()
