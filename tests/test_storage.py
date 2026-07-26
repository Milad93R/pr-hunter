from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pr_hunter.models import (
    IssueCandidate,
    RankedCandidate,
    RepositorySignals,
    ScoreResult,
)
from pr_hunter.qualification import evaluate_qualification
from pr_hunter.storage import Store


def ranked_candidate() -> RankedCandidate:
    repo = RepositorySignals(
        full_name="owner/repo",
        html_url="https://github.com/owner/repo",
        description="Test",
        language="Python",
        topics=("ai",),
        stars=100,
        forks=10,
        open_issues=4,
        archived=False,
        pushed_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    issue = IssueCandidate(
        repo=repo,
        number=1,
        title="Fix the parser",
        body="Steps to reproduce",
        html_url="https://github.com/owner/repo/issues/1",
        labels=("bug",),
        assignees=(),
        author="reporter",
        author_association="NONE",
        comments_count=0,
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        updated_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    return RankedCandidate(issue, ScoreResult(72, "promising"))


class StorageTests(unittest.TestCase):
    def test_candidate_state_and_qualification_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.db"
            with Store(path) as store:
                store.upsert_candidates([ranked_candidate()])
                store.set_status("owner/repo#1", "shortlisted")
                qualification = evaluate_qualification(
                    "owner/repo#1",
                    reproduced=True,
                    root_cause_confidence="high",
                    test_plan=True,
                    ci_feasible=True,
                    scope="small",
                    maintainer_signal="positive",
                )
                store.save_qualification(qualification)
                record = store.get_candidate("owner/repo#1")

            self.assertEqual(record["status"], "shortlisted")
            self.assertEqual(record["score"], 72)
            self.assertEqual(record["qualification"]["readiness"], "ready_to_claim")

    def test_upsert_preserves_workflow_status(self):
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "state.db") as store:
                store.upsert_candidates([ranked_candidate()])
                store.set_status("owner/repo#1", "investigating")
                store.upsert_candidates([ranked_candidate()])
                record = store.get_candidate("owner/repo#1")
            self.assertEqual(record["status"], "investigating")


if __name__ == "__main__":
    unittest.main()
