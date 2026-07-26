from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from pr_hunter.models import Qualification, RankedCandidate

VALID_STATUSES = {
    "discovered",
    "shortlisted",
    "investigating",
    "claimed",
    "in_progress",
    "pr_open",
    "merged",
    "rejected",
    "archived",
}


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS candidates (
                candidate_key TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                issue_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                score INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'discovered',
                snapshot_json TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_candidates_score
                ON candidates(score DESC);
            CREATE INDEX IF NOT EXISTS idx_candidates_status
                ON candidates(status, score DESC);

            CREATE TABLE IF NOT EXISTS qualifications (
                candidate_key TEXT PRIMARY KEY,
                qualification_json TEXT NOT NULL,
                readiness TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(candidate_key)
                    REFERENCES candidates(candidate_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ai_reviews (
                candidate_key TEXT PRIMARY KEY,
                review_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(candidate_key)
                    REFERENCES candidates(candidate_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                candidate_count INTEGER NOT NULL
            );
            """
        )
        self.connection.commit()

    def upsert_candidates(self, ranked: Iterable[RankedCandidate]) -> int:
        now = datetime.now(UTC).isoformat()
        count = 0
        with self.connection:
            for item in ranked:
                candidate = item.candidate
                self.connection.execute(
                    """
                    INSERT INTO candidates (
                        candidate_key, repo, issue_number, title, url,
                        score, verdict, status, snapshot_json,
                        first_seen, last_seen
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'discovered', ?, ?, ?)
                    ON CONFLICT(candidate_key) DO UPDATE SET
                        repo=excluded.repo,
                        issue_number=excluded.issue_number,
                        title=excluded.title,
                        url=excluded.url,
                        score=excluded.score,
                        verdict=excluded.verdict,
                        snapshot_json=excluded.snapshot_json,
                        last_seen=excluded.last_seen
                    """,
                    (
                        candidate.key,
                        candidate.repo.full_name,
                        candidate.number,
                        candidate.title,
                        candidate.html_url,
                        item.score.total,
                        item.score.verdict,
                        json.dumps(item.to_dict(), ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                count += 1
        return count

    def record_run(
        self, started_at: datetime, completed_at: datetime, count: int
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO scan_runs(started_at, completed_at, candidate_count)
                VALUES (?, ?, ?)
                """,
                (started_at.isoformat(), completed_at.isoformat(), count),
            )

    def list_candidates(
        self, *, status: str | None = None, limit: int = 25
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(limit)
        rows = self.connection.execute(
            f"""
            SELECT candidate_key, repo, issue_number, title, url, score,
                   verdict, status, snapshot_json, first_seen, last_seen
            FROM candidates
            {where}
            ORDER BY score DESC, last_seen DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._row(row) for row in rows]

    def get_candidate(self, candidate_key: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT candidate_key, repo, issue_number, title, url, score,
                   verdict, status, snapshot_json, first_seen, last_seen
            FROM candidates
            WHERE candidate_key = ?
            """,
            (candidate_key,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Candidate not found: {candidate_key}")
        result = self._row(row)
        qualification = self.connection.execute(
            """
            SELECT qualification_json FROM qualifications
            WHERE candidate_key = ?
            """,
            (candidate_key,),
        ).fetchone()
        review = self.connection.execute(
            "SELECT review_json FROM ai_reviews WHERE candidate_key = ?",
            (candidate_key,),
        ).fetchone()
        result["qualification"] = (
            json.loads(qualification[0]) if qualification else None
        )
        result["ai_review"] = json.loads(review[0]) if review else None
        return result

    def set_status(self, candidate_key: str, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Unsupported candidate status: {status}")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE candidates SET status = ? WHERE candidate_key = ?",
                (status, candidate_key),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"Candidate not found: {candidate_key}")

    def save_qualification(self, qualification: Qualification) -> None:
        with self.connection:
            cursor = self.connection.execute(
                "SELECT 1 FROM candidates WHERE candidate_key = ?",
                (qualification.candidate_key,),
            )
            if cursor.fetchone() is None:
                raise KeyError(f"Candidate not found: {qualification.candidate_key}")
            self.connection.execute(
                """
                INSERT INTO qualifications(
                    candidate_key, qualification_json, readiness, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(candidate_key) DO UPDATE SET
                    qualification_json=excluded.qualification_json,
                    readiness=excluded.readiness,
                    updated_at=excluded.updated_at
                """,
                (
                    qualification.candidate_key,
                    json.dumps(qualification.to_dict(), ensure_ascii=False),
                    qualification.readiness,
                    qualification.updated_at.isoformat(),
                ),
            )

    def save_ai_review(self, candidate_key: str, review: dict[str, Any]) -> None:
        with self.connection:
            cursor = self.connection.execute(
                "SELECT 1 FROM candidates WHERE candidate_key = ?",
                (candidate_key,),
            )
            if cursor.fetchone() is None:
                raise KeyError(f"Candidate not found: {candidate_key}")
            self.connection.execute(
                """
                INSERT INTO ai_reviews(candidate_key, review_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(candidate_key) DO UPDATE SET
                    review_json=excluded.review_json,
                    updated_at=excluded.updated_at
                """,
                (
                    candidate_key,
                    json.dumps(review, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("snapshot_json"))
        return result
