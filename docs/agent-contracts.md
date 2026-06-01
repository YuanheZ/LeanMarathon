# Agent Contracts

LeanMarathon exposes four Codex agent roles. The role-specific workspace
templates live under `agents/` and are copied into sparse Git worktrees before
each job starts.

| Role | Branch pattern | Default prompt | Delivery |
|---|---|---|---|
| Blueprinter | `blueprint/init` | `Begin from Phase 1` | Creates the initial Lean blueprint and delivers a CI-green PR merged into `main`. |
| Target-Reviewer | `target-review/round-<n>` | `Begin the work.` | Audits theorem nodes against canonical targets and exits cleanly or files a grouped issue titled `Blueprint target review`. |
| Refiner | `blueprint-refiner/round-<n>` in Stage 1, `refiner/round-<n>` in Stage 2 | `Begin from Phase 1` | Repairs open issues and delivers a CI-green PR merged into `main`. |
| Worker | `round-<n>/<target_node>` | `Begin from Phase 1` | Proves one Stage 2 dynamic leaf, or files a blocker issue. |

Blueprinter, Refiner, and successful Worker jobs run with stop hooks that keep
the agent alive until the delivered PR is CI-green and merged. Target-Reviewer
does not use a stop hook. A blocked Worker may finish by filing an issue.

Custom prompts can be supplied at `leanmarathon init` with
`--blueprinter-prompt`, `--target-reviewer-prompt`, `--refiner-prompt`, and
`--worker-prompt`. Default prompts are not written to prompt files; custom
prompts are stored in local target config and materialized inside worktrees.
