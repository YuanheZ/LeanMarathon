# LeanMarathon Quickstart

## 1. Initialize A Target Repo

```bash
leanmarathon init \
  --owner MyGitHubName \
  --repo MyTargetRepo \
  --problem-file /absolute/path/to/problem.txt \
  --proof-file /absolute/path/to/proof-source
```

This creates a private GitHub repo, writes `.leanmarathon/config.toml`, copies
the source inputs, installs the CI workflows, and pushes `main`.

## 2. Run End To End

```bash
leanmarathon auto --owner MyGitHubName --repo MyTargetRepo
```

This submits one parent orchestration job. It runs Stage 1 to produce a
review-clean blueprint, then runs Stage 2 to prove the dynamic leaves.

Stage 1 runs:

```text
Blueprinter -> CI -> Target-Reviewer -> Refiner as needed
```

Stage 2 runs the dynamic-leaf Worker loop and invokes Refiner whenever open
issues exist.

## 3. Run Stages Separately

```bash
leanmarathon stage1 run --owner MyGitHubName --repo MyTargetRepo
leanmarathon stage2 run --owner MyGitHubName --repo MyTargetRepo
```

Use separate commands when you want to inspect or manually repair the initial
blueprint before proof work begins.
