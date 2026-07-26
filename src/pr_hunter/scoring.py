from __future__ import annotations

from datetime import UTC, datetime

from pr_hunter.config import ContributorProfile
from pr_hunter.models import IssueCandidate, ScoreComponent, ScoreResult

HARD_BLOCK_LABELS = {
    "duplicate",
    "invalid",
    "wontfix",
    "won't fix",
    "not planned",
}
SOFT_BLOCK_LABELS = {
    "blocked",
    "needs info",
    "needs-info",
    "waiting for feedback",
    "on hold",
}


def _days_since(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, (now - value).days)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def score_candidate(
    candidate: IssueCandidate,
    profile: ContributorProfile,
    *,
    now: datetime | None = None,
) -> ScoreResult:
    now = now or datetime.now(UTC)
    components: list[ScoreComponent] = [
        ScoreComponent("baseline", 20, "Passed GitHub search filters")
    ]
    risks: list[str] = []
    hard_rejects: list[str] = []
    repo = candidate.repo
    labels = {label.casefold() for label in candidate.labels}
    topics = {topic.casefold() for topic in repo.topics}
    preferred_topics = {topic.casefold() for topic in profile.topics}
    excluded_topics = {topic.casefold() for topic in profile.exclude_topics}
    languages = {language.casefold() for language in profile.languages}
    issue_signal_text = " ".join((candidate.title, *candidate.labels))

    if repo.archived:
        hard_rejects.append("Repository is archived")
    if candidate.assignees:
        hard_rejects.append(
            f"Issue already assigned to {', '.join(candidate.assignees)}"
        )
    blocked = labels & HARD_BLOCK_LABELS
    if blocked:
        hard_rejects.append(f"Blocking label: {', '.join(sorted(blocked))}")
    if candidate.claim_signals:
        hard_rejects.append("Recent comment indicates somebody claimed the work")
    if candidate.linked_open_prs:
        hard_rejects.append("An open pull request is already linked to the issue")

    if repo.language and repo.language.casefold() in languages:
        components.append(
            ScoreComponent(
                "stack-fit",
                14,
                f"Primary language {repo.language} matches profile",
            )
        )
    else:
        components.append(
            ScoreComponent(
                "stack-fit",
                -6,
                f"Primary language {repo.language or 'unknown'} is outside profile",
            )
        )

    topic_matches = topics & preferred_topics
    if topic_matches:
        points = min(8, len(topic_matches) * 3)
        components.append(
            ScoreComponent(
                "topic-fit",
                points,
                f"Matching topics: {', '.join(sorted(topic_matches))}",
            )
        )
    excluded_matches = topics & excluded_topics
    if excluded_matches:
        components.append(
            ScoreComponent(
                "topic-exclusion",
                -14,
                f"Excluded topics: {', '.join(sorted(excluded_matches))}",
            )
        )
        risks.append("Repository is in an excluded domain")

    preferred_issue_matches = tuple(
        term
        for term in profile.preferred_issue_terms
        if term.casefold() in issue_signal_text.casefold()
    )
    if preferred_issue_matches:
        components.append(
            ScoreComponent(
                "engineering-fit",
                min(8, 4 + len(preferred_issue_matches)),
                "Engineering signals: " + ", ".join(preferred_issue_matches[:4]),
            )
        )
    deprioritized_issue_matches = tuple(
        term
        for term in profile.deprioritize_issue_terms
        if term.casefold() in issue_signal_text.casefold()
    )
    if deprioritized_issue_matches:
        components.append(
            ScoreComponent(
                "work-type",
                -20,
                "Deprioritized work type: "
                + ", ".join(deprioritized_issue_matches[:4]),
            )
        )
        risks.append("Task appears less valuable than a focused engineering change")

    pushed_days = _days_since(repo.pushed_at, now)
    if pushed_days is None:
        components.append(
            ScoreComponent("repo-activity", -5, "Repository push date unavailable")
        )
    elif pushed_days <= 30:
        components.append(
            ScoreComponent(
                "repo-activity", 10, f"Repository pushed {pushed_days} days ago"
            )
        )
    elif pushed_days <= 90:
        components.append(
            ScoreComponent(
                "repo-activity", 7, f"Repository pushed {pushed_days} days ago"
            )
        )
    elif pushed_days <= 180:
        components.append(
            ScoreComponent(
                "repo-activity", 4, f"Repository pushed {pushed_days} days ago"
            )
        )
    elif pushed_days > 365:
        components.append(
            ScoreComponent(
                "repo-activity",
                -12,
                f"Repository has not been pushed for {pushed_days} days",
            )
        )
        risks.append("Repository may be inactive")

    if repo.stars >= 10_000:
        reputation = 8
    elif repo.stars >= 1_000:
        reputation = 6
    elif repo.stars >= 100:
        reputation = 3
    elif repo.stars >= 10:
        reputation = 1
    else:
        reputation = -4
    components.append(
        ScoreComponent(
            "reputation",
            reputation,
            f"Repository has {repo.stars:,} stars",
        )
    )

    community_points = 0
    community_reasons: list[str] = []
    if repo.community_health is not None:
        community_points += min(4, repo.community_health // 25)
        community_reasons.append(f"{repo.community_health}% community health")
    if repo.has_contributing:
        community_points += 2
        community_reasons.append("contribution guide")
    if repo.has_pr_template:
        community_points += 1
        community_reasons.append("PR template")
    if community_reasons:
        components.append(
            ScoreComponent(
                "contribution-friction",
                community_points,
                ", ".join(community_reasons),
            )
        )

    if repo.recent_pr_merge_rate is not None:
        rate = repo.recent_pr_merge_rate
        if rate >= 0.65:
            merge_points = 5
        elif rate >= 0.40:
            merge_points = 2
        elif rate < 0.20:
            merge_points = -5
            risks.append("Few recently closed PRs were merged")
        else:
            merge_points = -1
        components.append(
            ScoreComponent(
                "merge-history",
                merge_points,
                f"{rate:.0%} of {repo.recent_pr_count} recent closed PRs merged",
            )
        )
    if repo.median_pr_close_days is not None:
        days = repo.median_pr_close_days
        if days <= 14:
            close_points = 3
        elif days <= 45:
            close_points = 1
        elif days > 120:
            close_points = -3
            risks.append("Recent pull requests close slowly")
        else:
            close_points = 0
        components.append(
            ScoreComponent(
                "review-speed",
                close_points,
                f"Median recent PR close time is {days:.1f} days",
            )
        )

    label_points = 0
    label_reasons: list[str] = []
    if "help wanted" in labels:
        label_points += 7
        label_reasons.append("help wanted")
    if "good first issue" in labels:
        label_points += 4
        label_reasons.append("good first issue")
    if "bug" in labels or _contains_any(candidate.title, ("fix", "bug", "error")):
        label_points += 5
        label_reasons.append("bug/fix")
    if labels & {"performance", "security", "reliability"}:
        label_points += 4
        label_reasons.append("high-signal engineering label")
    if label_reasons:
        components.append(
            ScoreComponent(
                "issue-labels",
                min(14, label_points),
                ", ".join(label_reasons),
            )
        )

    soft_blocked = labels & SOFT_BLOCK_LABELS
    if soft_blocked:
        components.append(
            ScoreComponent(
                "soft-block",
                -10,
                f"Soft blocking label: {', '.join(sorted(soft_blocked))}",
            )
        )
        risks.append("Issue is waiting on information or another dependency")

    body = candidate.body
    clarity_points = 0
    clarity_reasons: list[str] = []
    if len(body) >= 500:
        clarity_points += 4
        clarity_reasons.append("detailed body")
    elif len(body) >= 180:
        clarity_points += 2
        clarity_reasons.append("useful body")
    else:
        clarity_points -= 3
        clarity_reasons.append("thin body")
        risks.append("Issue description may be too thin to estimate")
    clarity_terms = {
        "reproduction steps": ("reproduce", "steps to reproduce", "minimal repro"),
        "expected behavior": ("expected behavior", "expected result"),
        "actual behavior": ("actual behavior", "actual result"),
        "test evidence": ("test", "failing test", "regression"),
        "code references": ("`", ".py", ".ts", ".go", ".tsx", ".js"),
    }
    for name, terms in clarity_terms.items():
        if _contains_any(body, terms):
            clarity_points += 1
            clarity_reasons.append(name)
    components.append(
        ScoreComponent(
            "issue-clarity",
            min(9, clarity_points),
            ", ".join(clarity_reasons),
        )
    )

    updated_days = _days_since(candidate.updated_at, now) or 0
    if updated_days <= 14:
        freshness = 5
    elif updated_days <= 30:
        freshness = 3
    elif updated_days <= 90:
        freshness = 1
    elif updated_days > 365:
        freshness = -7
        risks.append("Issue discussion is stale")
    else:
        freshness = -2
    components.append(
        ScoreComponent(
            "issue-freshness",
            freshness,
            f"Issue updated {updated_days} days ago",
        )
    )

    age_days = _days_since(candidate.created_at, now) or 0
    if age_days <= 365:
        age_points = 2
    elif age_days > 730:
        age_points = -6
        risks.append("Issue is more than two years old")
    else:
        age_points = -1
    components.append(
        ScoreComponent("issue-age", age_points, f"Issue age is {age_days} days")
    )

    if not candidate.assignees:
        components.append(ScoreComponent("availability", 6, "Issue has no assignee"))
    if 1 <= candidate.comments_count <= 12:
        components.append(
            ScoreComponent(
                "discussion",
                2,
                f"Manageable discussion ({candidate.comments_count} comments)",
            )
        )
    elif candidate.comments_count > 30:
        components.append(
            ScoreComponent(
                "discussion",
                -4,
                f"Large discussion ({candidate.comments_count} comments)",
            )
        )
        risks.append("Long discussion may hide changing requirements")

    if candidate.maintainer_comment_count:
        points = 4
        last_days = _days_since(candidate.last_maintainer_comment_at, now)
        if last_days is not None and last_days <= 30:
            points += 2
        components.append(
            ScoreComponent(
                "maintainer-signal",
                points,
                f"{candidate.maintainer_comment_count} maintainer comments",
            )
        )
    elif candidate.comments_count:
        risks.append("No maintainer participation detected in fetched comments")

    if candidate.linked_closed_prs and not candidate.linked_open_prs:
        risks.append("A related PR was previously closed; inspect why")

    raw_total = sum(component.points for component in components)
    total = max(0, min(100, raw_total))
    if hard_rejects:
        verdict = "skip"
        total = min(total, 35)
    elif deprioritized_issue_matches and not preferred_issue_matches:
        total = min(total, 59)
        verdict = "investigate" if total >= 50 else "skip"
    elif total >= 80:
        verdict = "strong"
    elif total >= 65:
        verdict = "promising"
    elif total >= 50:
        verdict = "investigate"
    else:
        verdict = "skip"
    return ScoreResult(
        total=total,
        verdict=verdict,
        components=components,
        risks=risks,
        hard_rejects=hard_rejects,
    )


def positive_summary(score: ScoreResult, limit: int = 3) -> list[str]:
    positives = sorted(
        (component for component in score.components if component.points > 0),
        key=lambda component: component.points,
        reverse=True,
    )
    return [component.reason for component in positives[:limit]]
