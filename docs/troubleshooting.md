# Troubleshooting

Run dependency checks first:

```bash
leanmarathon doctor
leanmarathon doctor --owner MyGitHubName --repo MyTargetRepo
```

## GitHub Authentication Fails

If commands fail with token or permission errors, refresh `gh auth login` or set:

```bash
export LEANMARATHON_GITHUB_TOKEN=...
```

The token needs contents, pull requests, issues, actions, and workflows
read/write permissions.

## `gh` Is Not On The Job PATH

Set `paths.venv_bin`, `paths.node_bin`, `paths.elan_bin`, or the full
`paths.agent_path` / `paths.orchestrator_path` overrides in
`.leanmarathon.local.toml`. Generated jobs compose PATH from those fields plus
`/usr/local/bin:/usr/bin:/bin`.

## GitHub Says The Account Is Suspended

If CI fails during `actions/checkout` or `git fetch` with `Your account is
suspended`, the workflow has not reached Lean. Wait for GitHub service recovery
or resolve the account restriction before relaunching orchestration.

## No Workflow Runs Appear

Check that the PR modifies `LeanMarathon/**/*.lean` and that workflow
permissions are available. The verifier workflow runs on `pull_request_target`.

## Lean LSP Cannot Find A Project

Check `lean.project_root`, `paths.elan_bin`, and the worktree location. Agent
worktrees should be under:

```text
<lean_project_root>/.leanmarathon-worktrees/<owner>/<repo>/
```

## DAG Extraction Times Out

DAG extraction uses Lean elaboration and `Architect.collectUsed`. Timeouts exit
the orchestrator instead of filing a compilation issue. Increase orchestrator
CPUs/time or repair expensive Lean terms so the configured heartbeat/thread
budget is enough.

## Worktrees Accumulate

Merged successful agent jobs clean their worktrees automatically. Failed jobs
preserve worktrees and feature branches for debugging. Use
`leanmarathon status` to find the latest local run directory and inspect
`job.err` files.
