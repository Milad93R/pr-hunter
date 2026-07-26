# PR Hunter

PR Hunter is an evidence-first assistant for finding worthwhile open-source
issues and deciding whether they are safe to pursue.

It searches GitHub, ranks opportunities against a contributor profile, checks
repository health and recent pull-request behavior, detects competing work,
tracks candidates locally, and enforces a qualification checklist before work
is claimed. An optional two-model pass lets one AI account make the case for an
issue while another account tries to reject it.

PR Hunter is deliberately **read-only on GitHub**. It never comments, assigns
an issue, creates a fork, pushes code, or opens a pull request.

## Why it exists

A folder of cloned repositories is not a contribution system. The expensive
mistakes happen before implementation:

- choosing a feature that maintainers never requested;
- beginning work while another pull request already exists;
- trusting a plausible root-cause story without reproducing it;
- changing a broad subsystem when a narrow fix was required;
- spending days on a repository that rarely reviews external work;
- submitting a PR and forgetting to follow up until it becomes stale.

PR Hunter separates **discovery** from **qualification**. A high discovery
score means "investigate this," not "start coding."

## Current capabilities

- Authenticated GitHub search through `GITHUB_TOKEN` or the existing `gh` login
- Configurable languages, topics, exclusions, star floor, and search queries
- Engineering-work preferences that demote marketing, video, bounty, and
  similar non-code tasks
- Conservative search pacing and bounded minute-scale retry for GitHub
  secondary throttling
- Two-pass ranking:
  - fast deterministic scoring for all search results;
  - deeper enrichment for top candidates
- Repository signals:
  - activity and archive state
  - stars and primary language
  - community health, contribution guide, and PR template
  - recent PR merge ratio and median close time
- Issue signals:
  - assignment and blocking labels
  - body/reproduction clarity
  - freshness and discussion size
  - maintainer participation
  - comments that indicate somebody already claimed the work
  - open pull requests cross-referenced from the issue timeline
- SQLite state board with explicit candidate statuses
- Mandatory evidence gate for reproduction, root-cause confidence, test plan,
  CI feasibility, scope, and maintainer signal
- Markdown briefings for human review
- Optional scout-versus-reviewer AI analysis using separate OpenAI-compatible
  endpoints
- Zero runtime Python dependencies

## Quick start

```bash
cd /home/milad/projects/self/pr-hunter
uv venv --python 3.12
uv pip install --python .venv/bin/python -e .
. .venv/bin/activate
cp hunter.toml.example hunter.local.toml

# Uses GITHUB_TOKEN when set, otherwise `gh auth token`.
prhunter scan --config hunter.local.toml --limit 20
prhunter list
prhunter show owner/repository#123
```

The first scan creates `.prhunter/state.db`.

## The human-gated workflow

```text
discover -> shortlist -> investigate -> qualify -> claim -> implement -> PR
```

Only the first three steps are automated. After reproducing an issue and
inspecting the repository, record the evidence:

```bash
prhunter qualify owner/repository#123 \
  --reproduced yes \
  --root-cause high \
  --test-plan yes \
  --ci-feasible yes \
  --scope medium \
  --maintainer-signal positive \
  --notes "Failure reproduced in parser.py; focused regression test identified."
```

Possible gate results:

- `ready_to_claim`: evidence is strong and maintainer signal is positive.
- `ask_maintainer`: technical evidence is strong but ownership/direction needs
  confirmation.
- `do_not_start`: one or more safety gates failed.

Change the local workflow status independently:

```bash
prhunter status owner/repository#123 shortlisted
prhunter status owner/repository#123 investigating
```

Supported statuses are `discovered`, `shortlisted`, `investigating`, `claimed`,
`in_progress`, `pr_open`, `merged`, `rejected`, and `archived`.

## Generate a review briefing

```bash
prhunter brief --limit 10 --output reports/weekly.md
```

The report includes scores, evidence, risks, and links. It does not make any
GitHub changes.

## Optional two-account AI review

Copy the example configuration and set the keys in your environment:

```bash
export PRHUNTER_SCOUT_KEY="..."
export PRHUNTER_REVIEWER_KEY="..."
prhunter ai-review owner/repository#123 --config hunter.local.toml
```

The default example points the scout to local port `40701` and the skeptical
reviewer to `40702`. No key is stored in SQLite or printed in reports.

The scout must distinguish facts from assumptions and cannot claim that an
issue was reproduced. The reviewer receives both the candidate evidence and
the scout analysis, then looks specifically for:

- an unproven root cause;
- an already active contributor;
- low maintainer interest;
- excessive scope;
- weak testability;
- low career value relative to effort.

AI analysis is advisory. It cannot pass the manual qualification gate.

## Configuration

See [`hunter.toml.example`](hunter.toml.example). Search queries use GitHub's
issue-search syntax. PR Hunter appends each configured language and the
repository star floor to every query.

For a narrow scan:

```toml
[profile]
languages = ["Go"]
topics = ["kubernetes", "observability"]
exclude_topics = ["blockchain"]
preferred_issue_terms = ["bug", "fix", "performance", "security", "test"]
deprioritize_issue_terms = ["wikipedia", "video", "marketing", "bounty"]

[scan]
queries = ["is:issue is:open no:assignee label:bug label:\"help wanted\""]
```

## Commands

```text
prhunter scan       Discover, enrich, rank, and save live candidates
prhunter list       Show candidates already stored locally
prhunter show       Show all stored evidence for one candidate
prhunter status     Move a candidate through the local workflow
prhunter qualify    Record evidence and evaluate the pre-claim gate
prhunter brief      Export a Markdown decision brief
prhunter ai-review  Run the optional scout and skeptical reviewer
```

## Safety model

- GitHub integration performs GET requests only.
- There is no mutation method in the GitHub client.
- Secrets are read from environment variables or `gh auth token`.
- Raw tokens are never persisted.
- Candidate state is local SQLite data.
- The tool refuses to treat AI output as reproduction evidence.
- Security work must remain inside explicitly authorized scopes.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m pr_hunter --help
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the data flow and scoring
boundaries.
