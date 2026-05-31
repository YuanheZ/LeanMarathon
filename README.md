# LeanMarathon

LeanMarathon is an end-to-end orchestration system for turning a natural
language mathematical proof into a reviewed Lean blueprint and then proving the
blueprint by running many Codex agents through Slurm.

The intended workflow is:

```text
source proof + target statements
  -> Stage 1: blueprint generation and target review
  -> Stage 2: per-node proof work
  -> GitHub main branch with completed Lean proofs
```

LeanMarathon owns scheduling, worktree management, Slurm submission, runtime
inputs, and audit logs. Normal users interact with `leanmarathon ...` commands
and a small target config file, not the orchestration scripts directly.

## Agent Roles

| Role | Responsibility |
|---|---|
| **Blueprinter** | Creates the first CI-passing Lean blueprint from the source proof and target statements. |
| **Target-Reviewer** | Audits theorem nodes against the canonical target statements and files grouped issues for blueprint defects. |
| **Refiner** | Repairs blueprint-level issues or Worker blocker issues through CI-green PRs. |
| **Worker** | Proves one dynamic-leaf proof node during Stage 2. |

## What LeanMarathon Creates

`leanmarathon init` creates or updates a GitHub target repository. The target
repo receives:

- `LeanMarathon/Main.lean`: the Lean blueprint/proof file.
- `.github/workflows/verify-blueprint.yml`: CI gate for blueprint PRs.
- `.github/workflows/warmup-cache.yml`: optional Lean cache warmup workflow.
- `lakefile.toml`, `lake-manifest.json`, and `lean-toolchain`.

Runtime data is kept outside committed target files:

- `.orchestrator-repos/<owner>/<repo>/`: local per-target orchestration clone.
- `.leanmarathon-targets/<owner>/<repo>/`: local target config and copied source inputs.
- `.leanmarathon-targets/<owner>/<repo>/worktrees/`: per-branch agent worktrees, kept outside the target clone so accidental local `lake` commands cannot create `.lake` in the target repo.
- `.orchestrator-runs/`: per-run audit logs, Slurm scripts, stdout/stderr.
- `.codex-session-home/`: isolated Codex session history.

These runtime directories are ignored by the LeanMarathon system repo.

## Requirements

LeanMarathon v0.1 expects these tool versions:

| Tool | Version |
|---|---|
| Codex CLI | `0.128.0` |
| `lean-lsp-mcp` | `0.26.2` |
| `lean-explore` | `1.2.1` |
| `github-mcp-server` | `0.32.0` |
| `git-mcp-server` | `2.10.5` |

Lean itself is user-provided. LeanMarathon does not pin the Lean installation.
Set `lean.project_root` in `.leanmarathon.local.toml` to the Lean project whose
`lakefile.toml`, `lake-manifest.json`, `lean-toolchain`, and `.lake` cache
should be used. LeanMarathon copies the Lake metadata into the target repo for
CI and points Lean MCP/DAG tooling at that same project root.

Required Python PDF packages:

| Import |
|---|
| `pdfplumber` |
| `fitz` |
| `pdfminer.high_level` |
| `pypdf` |
| `PyPDF2` |
| `pypdfium2` |

Numerical packages are optional. During `leanmarathon init`, LeanMarathon
auto-detects the installed subset from its known optional numerical table and
exposes only those rows to agents.

## Install

Clone the system repo and install it in a Python environment:

```bash
git clone <LeanMarathon repo URL> LeanMarathon
cd LeanMarathon

python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Install the external MCP servers and Codex CLI according to your environment.
For example, the Node Git MCP server should expose `git-mcp-server` on `PATH`:

```bash
npm install -g @cyanheads/git-mcp-server@2.10.5
```

Check the installation:

```bash
leanmarathon doctor
```

The doctor command checks required CLI/MCP tools and mandatory PDF imports. It
also checks configured optional numeric imports when run against a target repo.

## Environment

Create a local machine config once:

```bash
cp config/local.example.toml .leanmarathon.local.toml
```

Then edit `.leanmarathon.local.toml` with your installed tool paths, default
Lean project root, and Slurm account/partition settings. Environment variables
with the same names still override the local config when needed.

```toml
[paths]
venv_bin = "/absolute/path/to/LeanMarathon/.venv/bin"
node_bin = "/absolute/path/to/node/bin"
elan_bin = "/absolute/path/to/elan/bin"

[lean]
project_root = "/absolute/path/to/lean-project"

[slurm]
cpu_account = ""
gpu_account = ""
gpu_partition = "gpu"
gpu_gres = "gpu:<gpu-type>:1"
mem_per_cpu = 3850
```

If your cluster does not require `#SBATCH --account`, leave the account fields
empty.

Authenticate GitHub with `gh auth login` or a token in the environment. The
token must be able to create repositories, push branches, open PRs, write
issues, and run workflows. Generated Slurm jobs use `GITHUB_TOKEN` /
`GITHUB_PERSONAL_ACCESS_TOKEN` when present, otherwise they derive a token from
`gh auth token`. Do not put GitHub tokens in `.leanmarathon.local.toml` or any
committed file.

## Initialize A Target Repo

Prepare two inputs:

- `problem_file`: canonical target statement(s), usually a text file.
- `proof_file`: source proof material, either a file or a directory.

Initialize a private target repository:

```bash
leanmarathon init \
  --owner MyGitHubName \
  --repo MyTargetRepo \
  --problem-file /absolute/path/to/problem.txt \
  --proof-file /absolute/path/to/proof-source \
  --orchestrator-resource gpu \
  --orchestrator-cpus 42 \
  --agent-resource gpu \
  --agent-cpus 42 \
  --batch-size 16
```

By default the GitHub repo is private. Add `--public` only when you intend to
create a public target repo.

LeanMarathon copies the problem/proof source into local ignored runtime state,
not into the target GitHub repo. The committed target repo stays focused on the
Lean file, Lake metadata, and CI workflows.

## Run End To End

The normal command is:

```bash
leanmarathon auto --owner MyGitHubName --repo MyTargetRepo
```

By default this submits one parent Slurm job. The parent job submits Stage 1,
waits for it to finish, then submits Stage 2 and waits for it to finish.

To run the coordinator in the current terminal while still submitting Stage 1
and Stage 2 jobs to Slurm, use:

```bash
leanmarathon auto --owner MyGitHubName --repo MyTargetRepo --no-submit
```

Useful overrides:

```bash
leanmarathon auto \
  --owner MyGitHubName \
  --repo MyTargetRepo \
  --n 8 \
  --max-review-rounds 20 \
  --max-rounds 100 \
  --agent-resource cpu
```

## Run Stages Separately

Stage 1 creates and reviews the blueprint:

```bash
leanmarathon stage1 run --owner MyGitHubName --repo MyTargetRepo
```

Stage 1 loop:

```text
Blueprinter -> CI -> Target-Reviewer -> Refiner as needed
```

It terminates only when Target-Reviewer exits clean, or when the configured
round cap is exhausted.

Stage 2 proves the blueprint:

```bash
leanmarathon stage2 run --owner MyGitHubName --repo MyTargetRepo
```

Stage 2 loop:

```text
Worker fan-out on dynamic leaves -> collect PRs/issues -> Refiner as needed
```

Workers run on dynamic leaves of the Lean elaboration DAG: unproven proof nodes
whose proof-node ancestors are already proven. This avoids dispatching workers
against descendants whose upstream statements may still shift.

## Monitor A Run

Show open GitHub issues, open PRs, and the latest local run directory:

```bash
leanmarathon status --owner MyGitHubName --repo MyTargetRepo
```

Slurm jobs can be inspected with normal cluster tools:

```bash
squeue -u "$USER"
sacct -j <job-id> --format=JobID,JobName,State,ExitCode,Elapsed,AllocCPUS,ReqMem
```

Audit logs live in:

```text
.orchestrator-repos/<owner>/<repo>/.orchestrator-runs/
```

Important files:

| File | Meaning |
|---|---|
| `auto-*/auto.out`, `auto-*/auto.err` | Parent end-to-end coordinator logs. |
| `stage1-*/stage1.out`, `stage1-*/stage1.err` | Stage 1 orchestrator logs. |
| `worker-loop-*/orchestrator.out`, `worker-loop-*/orchestrator.err` | Stage 2 orchestrator logs. |
| `*/jobs/**/job.out`, `*/jobs/**/job.err` | Individual agent Slurm logs. |
| `stage1_result.json`, `result.json`, `audit.jsonl` | Machine-readable orchestration records. |

## Configuration

Target-level settings are written to:

```text
.leanmarathon-targets/<owner>/<repo>/config.toml
```

This file is local runtime state and is not committed to the target GitHub repo.
Common fields:

```toml
[hpc.auto]
resource = "cpu"
cpus = 1
time = "48:00:00"

[hpc.stage1_orchestrator]
resource = "cpu"
cpus = 1
time = "48:00:00"

[hpc.stage2_orchestrator]
resource = "gpu"
cpus = 42
time = "48:00:00"

[hpc.agent]
resource = "gpu"
cpus = 42
time = "4:00:00"
batch_size = 16

[stage1]
max_review_rounds = 20

[stage2]
max_rounds = 100

[capabilities]
numeric_tools = ["numpy", "scipy", "sympy"]
```

`numeric_tools` is generated by auto-detection during `leanmarathon init`.
It controls which package rows are visible in each agent worktree's
`docs/references/numeric-tools.md`. Missing optional numeric tools are not
fatal unless an agent explicitly needs them for a task.

PDF-reading packages are mandatory because the proof source may be a PDF and
formula extraction must be checked against rendered pages.

## GitHub And CI

Every agent delivers through GitHub:

- Blueprinter, Refiner, and successful Workers open PRs.
- Target-Reviewer and blocked Workers file issues.
- The verification workflow checks changed `LeanMarathon/**/*.lean` files.
- Stop hooks keep PR-delivering agents alive until their PR is CI-green and
  merged.

The target repo's `main` branch is the canonical state. Orchestrators always
fetch and validate the target `origin/main` before dispatching new work.

## Troubleshooting

Run dependency checks:

```bash
leanmarathon doctor
leanmarathon doctor --owner MyGitHubName --repo MyTargetRepo
```

Common problems:

| Symptom | Likely cause |
|---|---|
| `Resource not accessible by personal access token` | The active GitHub token cannot create repos or write PRs/issues. Use `gh auth status` and check scopes. |
| No CI run appears | GitHub token/workflow permissions are insufficient, or the PR did not touch `LeanMarathon/**/*.lean`. |
| `git-mcp-server` missing | Install `@cyanheads/git-mcp-server@2.10.5` and put its binary on `paths.node_bin` or `PATH`. |
| Lean tools time out on first use | Build/cache the Lean project in the user-provided Lean environment before launching large runs. |
| Slurm rejects account | Set or unset `slurm.cpu_account` / `slurm.gpu_account` in `.leanmarathon.local.toml` according to your cluster policy. |

More focused references:

- `docs/dependencies.md`
- `docs/hpc-slurm.md`
- `docs/github-setup.md`
- `docs/agent-contracts.md`
- `docs/troubleshooting.md`
