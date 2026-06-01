# LeanMarathon Quickstart

## 1. Install And Configure

Install the CLI:

```bash
git clone <LeanMarathon repo URL> LeanMarathon
cd LeanMarathon
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Create local machine config:

```bash
cp config/local.example.toml .leanmarathon.local.toml
```

Fill in tool paths, Slurm settings, and `lean.project_root`. The Lean project
root must contain `lakefile.toml`, `lake-manifest.json`, and `lean-toolchain`.

Authenticate GitHub:

```bash
gh auth login
```

or:

```bash
export LEANMARATHON_GITHUB_TOKEN=...
```

Check the environment:

```bash
leanmarathon doctor
```

## 2. Initialize A Target Repo

Prepare a canonical problem file and a proof source file or directory. Then:

```bash
leanmarathon init \
  --owner MyGitHubName \
  --repo MyTargetRepo \
  --problem-file /absolute/path/to/problem.txt \
  --proof-file /absolute/path/to/proof-source
```

This creates a private GitHub repo by default, copies Lake metadata from the
configured Lean project root into the target repo, installs CI workflows, writes
`LeanMarathon/Main.lean`, and pushes `main`.

Local runtime config and input copies are written under:

```text
.leanmarathon-targets/<owner>/<repo>/
```

The target GitHub repo does not commit source inputs or LeanMarathon runtime
config.

## 3. Run End To End

```bash
leanmarathon auto --owner MyGitHubName --repo MyTargetRepo
```

This submits one parent Slurm job. The parent job runs Stage 1 to produce a
review-clean blueprint, then runs Stage 2 to prove the blueprint.

To keep the parent coordinator in the current terminal while still submitting
Stage 1 and Stage 2 to Slurm:

```bash
leanmarathon auto --owner MyGitHubName --repo MyTargetRepo --no-submit
```

## 4. Run Stages Separately

```bash
leanmarathon stage1 run --owner MyGitHubName --repo MyTargetRepo
leanmarathon stage2 run --owner MyGitHubName --repo MyTargetRepo
```

Stage 1 runs:

```text
Blueprinter -> CI -> Target-Reviewer -> Refiner as needed
```

Stage 2 runs:

```text
Worker fan-out on dynamic leaves -> Refiner for open issues -> repeat
```

Stage 2 auto-resumes by default, so normally do not pass `--start-round`.
