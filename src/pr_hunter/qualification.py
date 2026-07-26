from __future__ import annotations

from datetime import UTC, datetime

from pr_hunter.models import Qualification


def evaluate_qualification(
    candidate_key: str,
    *,
    reproduced: bool,
    root_cause_confidence: str,
    test_plan: bool,
    ci_feasible: bool,
    scope: str,
    maintainer_signal: str,
    notes: str = "",
) -> Qualification:
    blockers: list[str] = []
    if not reproduced:
        blockers.append("Failure has not been reproduced")
    if root_cause_confidence != "high":
        blockers.append("Root cause is not proven to high confidence")
    if not test_plan:
        blockers.append("No focused regression-test plan")
    if not ci_feasible:
        blockers.append("Relevant validation cannot be run")
    if scope == "large":
        blockers.append("Scope is too large for an initial contribution")
    if maintainer_signal == "negative":
        blockers.append("Maintainer signal is negative")

    if blockers:
        readiness = "do_not_start"
    elif maintainer_signal == "positive":
        readiness = "ready_to_claim"
    else:
        readiness = "ask_maintainer"

    return Qualification(
        candidate_key=candidate_key,
        reproduced=reproduced,
        root_cause_confidence=root_cause_confidence,
        test_plan=test_plan,
        ci_feasible=ci_feasible,
        scope=scope,
        maintainer_signal=maintainer_signal,
        notes=notes,
        readiness=readiness,
        blockers=tuple(blockers),
        updated_at=datetime.now(UTC),
    )
