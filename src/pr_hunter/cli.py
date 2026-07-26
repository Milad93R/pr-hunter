from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pr_hunter.ai import AIReviewError, two_account_review
from pr_hunter.config import AppConfig, load_config
from pr_hunter.github import GitHubClient, GitHubError
from pr_hunter.models import IssueCandidate, RankedCandidate, ScoreResult
from pr_hunter.qualification import evaluate_qualification
from pr_hunter.reporting import (
    render_json,
    render_markdown,
    render_stored_table,
    render_table,
)
from pr_hunter.scanner import Scanner
from pr_hunter.storage import VALID_STATUSES, Store


def _common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--config",
        help="TOML configuration path (defaults are used when omitted)",
    )
    parser.add_argument(
        "--state",
        help="Override the SQLite state path",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prhunter",
        description=(
            "Find and qualify high-value open-source contribution opportunities"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = _common_parser()

    scan = subparsers.add_parser(
        "scan", parents=[common], help="Discover and rank live GitHub issues"
    )
    scan.add_argument("--limit", type=int, help="Maximum unique candidates")
    scan.add_argument(
        "--enrich",
        type=int,
        help="Number of top candidates to enrich deeply",
    )
    scan.add_argument(
        "--format",
        choices=("table", "json", "markdown"),
        default="table",
    )
    scan.add_argument("--output", help="Write rendered output to a file")
    scan.add_argument("--quiet", action="store_true", help="Hide scan progress")

    list_command = subparsers.add_parser(
        "list", parents=[common], help="List locally stored candidates"
    )
    list_command.add_argument("--status", choices=sorted(VALID_STATUSES))
    list_command.add_argument("--limit", type=int, default=25)
    list_command.add_argument("--format", choices=("table", "json"), default="table")

    show = subparsers.add_parser(
        "show", parents=[common], help="Show stored evidence for one candidate"
    )
    show.add_argument("candidate_key")

    status = subparsers.add_parser(
        "status", parents=[common], help="Update local workflow status"
    )
    status.add_argument("candidate_key")
    status.add_argument("value", choices=sorted(VALID_STATUSES))

    qualify = subparsers.add_parser(
        "qualify",
        parents=[common],
        help="Evaluate the evidence gate before claiming work",
    )
    qualify.add_argument("candidate_key")
    qualify.add_argument("--reproduced", required=True, choices=("yes", "no"))
    qualify.add_argument(
        "--root-cause",
        required=True,
        choices=("low", "medium", "high"),
    )
    qualify.add_argument("--test-plan", required=True, choices=("yes", "no"))
    qualify.add_argument("--ci-feasible", required=True, choices=("yes", "no"))
    qualify.add_argument("--scope", required=True, choices=("small", "medium", "large"))
    qualify.add_argument(
        "--maintainer-signal",
        required=True,
        choices=("positive", "unknown", "negative"),
    )
    qualify.add_argument("--notes", default="")

    brief = subparsers.add_parser(
        "brief", parents=[common], help="Export a Markdown decision brief"
    )
    brief.add_argument("--status", choices=sorted(VALID_STATUSES))
    brief.add_argument("--limit", type=int, default=10)
    brief.add_argument("--output", required=True)
    brief.add_argument("--title", default="PR Hunter decision brief")

    ai_review = subparsers.add_parser(
        "ai-review",
        parents=[common],
        help="Run optional scout-versus-reviewer analysis",
    )
    ai_review.add_argument("candidate_key")

    return parser


def _load(args: argparse.Namespace) -> tuple[AppConfig, Path]:
    config = load_config(args.config)
    state_path = (
        Path(args.state).expanduser().resolve()
        if args.state
        else config.scan.state_path
    )
    return config, state_path


def _ranked_from_record(record: dict[str, Any]) -> RankedCandidate:
    snapshot = record["snapshot"]
    return RankedCandidate(
        candidate=IssueCandidate.from_dict(snapshot["candidate"]),
        score=ScoreResult.from_dict(snapshot["score"]),
    )


def _write_or_print(text: str, output: str | None = None) -> None:
    if output:
        path = Path(output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        print(path)
    else:
        print(text)


def _handle_scan(args: argparse.Namespace) -> None:
    config, state_path = _load(args)

    def progress(message: str) -> None:
        if not args.quiet:
            print(f"[prhunter] {message}", file=sys.stderr)

    started = datetime.now(UTC)
    scanner = Scanner(GitHubClient(), config, progress)
    ranked = scanner.scan(limit=args.limit, enrich_top=args.enrich)
    completed = datetime.now(UTC)
    with Store(state_path) as store:
        store.upsert_candidates(ranked)
        store.record_run(started, completed, len(ranked))

    if args.format == "json":
        text = render_json(ranked)
    elif args.format == "markdown":
        text = render_markdown(ranked, "PR Hunter live scan")
    else:
        text = render_table(ranked)
    _write_or_print(text, args.output)


def _handle_list(args: argparse.Namespace) -> None:
    _, state_path = _load(args)
    with Store(state_path) as store:
        records = store.list_candidates(status=args.status, limit=args.limit)
    if args.format == "json":
        print(render_json(records))
    else:
        print(render_stored_table(records))


def _handle_show(args: argparse.Namespace) -> None:
    _, state_path = _load(args)
    with Store(state_path) as store:
        record = store.get_candidate(args.candidate_key)
    print(render_json(record))


def _handle_status(args: argparse.Namespace) -> None:
    _, state_path = _load(args)
    with Store(state_path) as store:
        store.set_status(args.candidate_key, args.value)
    print(f"{args.candidate_key}: {args.value}")


def _yes(value: str) -> bool:
    return value == "yes"


def _handle_qualify(args: argparse.Namespace) -> None:
    _, state_path = _load(args)
    qualification = evaluate_qualification(
        args.candidate_key,
        reproduced=_yes(args.reproduced),
        root_cause_confidence=args.root_cause,
        test_plan=_yes(args.test_plan),
        ci_feasible=_yes(args.ci_feasible),
        scope=args.scope,
        maintainer_signal=args.maintainer_signal,
        notes=args.notes,
    )
    with Store(state_path) as store:
        store.save_qualification(qualification)
    print(render_json(qualification.to_dict()))


def _handle_brief(args: argparse.Namespace) -> None:
    _, state_path = _load(args)
    with Store(state_path) as store:
        records = store.list_candidates(status=args.status, limit=args.limit)
    ranked = [_ranked_from_record(record) for record in records]
    _write_or_print(render_markdown(ranked, args.title), args.output)


def _handle_ai_review(args: argparse.Namespace) -> None:
    config, state_path = _load(args)
    if not config.ai.scout or not config.ai.reviewer:
        raise ValueError("Both [ai.scout] and [ai.reviewer] must be configured")
    with Store(state_path) as store:
        candidate = store.get_candidate(args.candidate_key)
        review = two_account_review(
            candidate,
            config.ai.scout,
            config.ai.reviewer,
        )
        store.save_ai_review(args.candidate_key, review)
    print(render_json(review))


HANDLERS = {
    "scan": _handle_scan,
    "list": _handle_list,
    "show": _handle_show,
    "status": _handle_status,
    "qualify": _handle_qualify,
    "brief": _handle_brief,
    "ai-review": _handle_ai_review,
}


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        HANDLERS[args.command](args)
    except (AIReviewError, GitHubError, KeyError, ValueError) as error:
        print(f"prhunter: {error}", file=sys.stderr)
        raise SystemExit(2) from error
