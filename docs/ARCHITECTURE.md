# Architecture

## Design principle

PR Hunter optimizes for **merge probability per hour**, not issue volume.

The system therefore has three separate confidence layers:

1. **Discovery score**: public metadata suggests the issue is worth reading.
2. **AI review**: optional adversarial analysis identifies hidden risks.
3. **Qualification gate**: human-supplied evidence determines whether work may
   be claimed.

No layer can silently promote itself into the next one.

## Data flow

```text
GitHub Search API
      |
      v
deduplicate issue candidates
      |
      v
repository metadata + preliminary score
  | enforce configured repository star floor
  | prefer engineering work over marketing/bounty tasks
      |
      v
top-N enrichment
  | community profile
  | recent closed PRs
  | issue comments
  | issue timeline / linked PRs
      |
      v
final deterministic score
      |
      +----> SQLite candidate board
      |
      +----> table / JSON / Markdown
      |
      +----> optional AI scout -> AI reviewer
      |
      v
manual qualification evidence
      |
      v
ready_to_claim | ask_maintainer | do_not_start
```

## Modules

- `config.py`: TOML configuration and safe defaults
- `github.py`: read-only GitHub REST client
- `models.py`: typed issue, repository, score, and qualification records
- `scoring.py`: deterministic scoring with explanations and hard rejections
- `scanner.py`: two-pass discovery and enrichment orchestration
- `storage.py`: SQLite state board and review persistence
- `qualification.py`: evidence gate independent from discovery score
- `ai.py`: optional OpenAI-compatible scout/reviewer calls
- `reporting.py`: terminal, JSON, and Markdown output
- `cli.py`: command-line interface

## Why deterministic scoring comes first

LLMs are good at summarizing ambiguous issue descriptions but poor at knowing
whether work is already claimed or whether a repository is active unless those
facts are supplied. Public metadata is cheaper, reproducible, and auditable.
The AI layer receives the deterministic evidence instead of replacing it.

## Scoring boundaries

Positive signals include:

- stack and topic fit;
- preferred engineering issue types;
- recent repository and issue activity;
- explicit contribution labels;
- clear reproduction/expected/actual/test language;
- contribution documentation;
- recent PRs that merge within a reasonable time;
- maintainer participation.

Hard rejection signals include:

- archived repository;
- assigned issue;
- duplicate, invalid, or wontfix label;
- explicit claim language in comments;
- open pull request cross-referenced from the issue.

Scores are clamped to 0–100. A score is always accompanied by components,
risks, and hard-rejection reasons.

## Persistence

SQLite stores:

- the latest candidate snapshot;
- first and last seen timestamps;
- deterministic score and verdict;
- local workflow status;
- qualification evidence and readiness;
- optional AI review JSON.

GitHub credentials are never stored.

## Future extensions

- GitHub App installation for organization-scale scans
- notification-only scheduler
- local repository reproduction worktrees
- CI command discovery and cost estimation
- maintainer-response reminders
- merge-outcome calibration of scoring weights
- a read-only web dashboard over the SQLite database
