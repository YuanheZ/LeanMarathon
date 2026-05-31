# LeanMarathon

LeanMarathon orchestrates an end-to-end Lean blueprint and proof marathon.

It uses four agent roles:

- **Blueprinter**: creates the initial CI-passing Lean blueprint.
- **Target-Reviewer**: compares theorem targets against the canonical problem source.
- **Refiner**: repairs blueprint-level issues or failed Worker blockers.
- **Worker**: proves one dynamic-leaf proof node in Stage 2.

## Quick Start

```bash
python -m leanmarathon.cli init \
  --owner MyGitHubName \
  --repo MyTargetRepo \
  --problem-file /path/to/problem.txt \
  --proof-file /path/to/source-proof

python -m leanmarathon.cli auto \
  --owner MyGitHubName \
  --repo MyTargetRepo
```

The target repository receives `.leanmarathon/config.toml`, `LeanMarathon/Main.lean`,
the source inputs, and the verification workflows. Runtime worktrees and audit
logs live under `LeanMarathon/.orchestrator-repos/<owner>/<repo>/`.

Stage-specific commands remain available:

```bash
python -m leanmarathon.cli stage1 run --owner MyGitHubName --repo MyTargetRepo
python -m leanmarathon.cli stage2 run --owner MyGitHubName --repo MyTargetRepo
```

See `docs/dependencies.md` for v0.1 tool versions and user-provided path
requirements.
