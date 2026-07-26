from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from pr_hunter.models import RankedCandidate
from pr_hunter.scoring import positive_summary


def _short(value: str, length: int) -> str:
    clean = " ".join(value.split())
    if len(clean) <= length:
        return clean
    return clean[: length - 1] + "…"


def render_table(ranked: Iterable[RankedCandidate]) -> str:
    items = list(ranked)
    if not items:
        return "No candidates found."
    headers = ("#", "score", "verdict", "repository", "issue", "top signal")
    rows: list[tuple[str, ...]] = []
    for index, item in enumerate(items, 1):
        summary = positive_summary(item.score, 1)
        signal = summary[0] if summary else "No positive signal"
        if item.score.hard_rejects:
            signal = f"REJECT: {item.score.hard_rejects[0]}"
        rows.append(
            (
                str(index),
                str(item.score.total),
                item.score.verdict,
                _short(item.candidate.repo.full_name, 28),
                _short(f"#{item.candidate.number} {item.candidate.title}", 48),
                _short(signal, 42),
            )
        )
    widths = [
        min(
            max(len(headers[index]), *(len(row[index]) for row in rows)),
            (3, 5, 11, 28, 48, 42)[index],
        )
        for index in range(len(headers))
    ]

    def line(values: tuple[str, ...]) -> str:
        return "  ".join(
            _short(value, widths[index]).ljust(widths[index])
            for index, value in enumerate(values)
        )

    divider = "  ".join("-" * width for width in widths)
    return "\n".join([line(headers), divider, *(line(row) for row in rows)])


def render_stored_table(records: Iterable[dict[str, Any]]) -> str:
    rows = list(records)
    if not rows:
        return "No stored candidates."
    headers = ("score", "verdict", "status", "candidate", "title")
    values = [
        (
            str(row["score"]),
            row["verdict"],
            row["status"],
            _short(row["candidate_key"], 38),
            _short(row["title"], 58),
        )
        for row in rows
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in values))
        for index in range(len(headers))
    ]

    def line(row: tuple[str, ...]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    return "\n".join(
        [
            line(headers),
            "  ".join("-" * width for width in widths),
            *(line(row) for row in values),
        ]
    )


def render_markdown(ranked: Iterable[RankedCandidate], title: str) -> str:
    items = list(ranked)
    lines = [
        f"# {title}",
        "",
        "> Discovery scores identify investigation candidates. They do not",
        "> replace reproduction, root-cause, test, or maintainer gates.",
        "",
    ]
    if not items:
        return "\n".join(lines + ["No candidates found.", ""])
    lines.extend(
        [
            "| Rank | Score | Verdict | Candidate |",
            "|---:|---:|---|---|",
        ]
    )
    for index, item in enumerate(items, 1):
        candidate = item.candidate
        lines.append(
            f"| {index} | {item.score.total} | {item.score.verdict} | "
            f"[{candidate.key}]({candidate.html_url}) — "
            f"{candidate.title.replace('|', '\\|')} |"
        )
    lines.append("")
    for index, item in enumerate(items, 1):
        candidate = item.candidate
        lines.extend(
            [
                f"## {index}. {candidate.key} — {candidate.title}",
                "",
                f"- **URL:** {candidate.html_url}",
                (
                    f"- **Repository:** {candidate.repo.stars:,} stars; "
                    f"{candidate.repo.language or 'unknown language'}"
                ),
                f"- **Score:** {item.score.total}/100 ({item.score.verdict})",
                f"- **Labels:** {', '.join(candidate.labels) or 'none'}",
                f"- **Maintainer comments:** {candidate.maintainer_comment_count}",
                (
                    f"- **Recent PR merge rate:** "
                    f"{_rate(candidate.repo.recent_pr_merge_rate)}"
                ),
                "",
                "### Strong signals",
                "",
            ]
        )
        positives = positive_summary(item.score, 5)
        lines.extend(f"- {reason}" for reason in positives)
        if not positives:
            lines.append("- None detected")
        lines.extend(["", "### Risks", ""])
        combined_risks = [
            *(f"Hard reject: {reason}" for reason in item.score.hard_rejects),
            *item.score.risks,
        ]
        lines.extend(f"- {risk}" for risk in combined_risks)
        if not combined_risks:
            lines.append("- No metadata-level risks detected")
        lines.extend(["", "---", ""])
    return "\n".join(lines)


def render_json(value: Any) -> str:
    if isinstance(value, list) and (not value or isinstance(value[0], RankedCandidate)):
        value = [item.to_dict() for item in value]
    return json.dumps(value, indent=2, ensure_ascii=False)


def _rate(value: float | None) -> str:
    return "not enriched" if value is None else f"{value:.0%}"
