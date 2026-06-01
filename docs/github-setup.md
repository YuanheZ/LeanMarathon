# GitHub Setup

LeanMarathon needs GitHub authentication for repository creation, branch
pushes, PRs, issues, workflow installation, and CI-triggered merges.

Preferred setup:

```bash
gh auth login
```

or set a LeanMarathon-specific token:

```bash
export LEANMARATHON_GITHUB_TOKEN=...
```

Required permissions:

| Permission area | Needed for |
|---|---|
| Contents read/write | Push branches and initialize target repos. |
| Pull requests read/write | Open and merge agent PRs. |
| Issues read/write | File and close review/blocker issues. |
| Actions/workflows read/write | Install and run copied workflows. |

Do not write tokens into `.leanmarathon.local.toml`, agent configs, docs, or
target repo files. Generated Slurm jobs inherit a token from
`LEANMARATHON_GITHUB_TOKEN` or from `gh auth token`; token values are not
written into generated job scripts.

The verification and cache warmup workflow templates are copied into every
generated target repo during `leanmarathon init`.
