# LeanMarathon Command Parameters

This file lists the user-facing arguments accepted by the `leanmarathon` CLI.

## `leanmarathon init`

Creates and initializes a target GitHub repository.

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--owner` | Yes | - | GitHub owner or organization for the target repository. |
| `--repo` | Yes | - | Target repository name. |
| `--problem-file` | Yes | - | Local canonical target statement file. |
| `--proof-file` | Yes | - | Local natural-language proof source; may be a file or directory. |
| `--target-problem-file` | No | Basename of `--problem-file` | Path used for the problem file inside the target repo/runtime inputs. |
| `--target-proof-file` | No | Basename of `--proof-file` | Path used for the proof source inside the target repo/runtime inputs. |
| `--lean-file` | No | `LeanMarathon/Main.lean` | Blueprint Lean file path inside the target repo. |
| `--lean-project-root` | Conditional | Local config/env value if set | Absolute path to the user's Lean project root containing Lake metadata. Required when not provided by local config or environment. |
| `--public` | No | Private repo | Create a public target repo instead of a private repo. |
| `--auto-resource` | No | `cpu` | Slurm resource mode for the parent `auto` job; `cpu` or `gpu`. |
| `--auto-cpus` | No | `1` | CPU cores for the parent `auto` job. |
| `--auto-time` | No | `48:00:00` | Slurm wall time for the parent `auto` job. |
| `--stage1-orchestrator-resource` | No | `cpu` | Slurm resource mode for the Stage 1 orchestrator; `cpu` or `gpu`. |
| `--stage1-orchestrator-cpus` | No | `1` | CPU cores for the Stage 1 orchestrator. |
| `--stage1-orchestrator-time` | No | `48:00:00` | Slurm wall time for the Stage 1 orchestrator. |
| `--orchestrator-resource` | No | `gpu` | Slurm resource mode for the Stage 2 orchestrator; `cpu` or `gpu`. |
| `--orchestrator-cpus` | No | `42` | CPU cores for the Stage 2 orchestrator. |
| `--orchestrator-time` | No | `48:00:00` | Slurm wall time for the Stage 2 orchestrator. |
| `--agent-resource` | No | `gpu` | Slurm resource mode for Blueprinter, Target-Reviewer, Refiner, and Worker jobs; `cpu` or `gpu`. |
| `--agent-cpus` | No | `42` | CPU cores for each agent job. |
| `--agent-time` | No | `4:00:00` | Slurm wall time for each agent job. |
| `--batch-size` | No | `16` | Maximum concurrent Stage 2 Worker jobs. |
| `--max-rounds` | No | `100` | Stage 2 round cap. |
| `--max-review-rounds` | No | `20` | Stage 1 review/refiner round cap. |
| `--blueprinter-prompt` | No | `Begin from Phase 1` | Custom Blueprinter start prompt. |
| `--target-reviewer-prompt` | No | `Begin the work.` | Custom Target-Reviewer start prompt. |
| `--refiner-prompt` | No | `Begin from Phase 1` | Custom Refiner start prompt. |
| `--worker-prompt` | No | `Begin from Phase 1` | Custom Worker start prompt. |

## `leanmarathon stage1 run`

Runs the Stage 1 Blueprinter / Target-Reviewer / Refiner loop for an initialized target.

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--owner` | Yes | - | GitHub owner or organization for the target repository. |
| `--repo` | Yes | - | Target repository name. |
| `--max-review-rounds` | No | Target config value | Stage 1 review/refiner round cap. |
| `--start-review-round` | No | `1` | First Target-Reviewer round index. |
| `--skip-blueprinter` | No | `false` | Skip Blueprinter and start from Target-Reviewer / Refiner loop on current target `main`. |
| `--agent-resource` | No | Target config value | Override agent Slurm resource mode; `cpu` or `gpu`. |
| `--submit` | No | `true` | Submit the Stage 1 orchestrator as a Slurm job. |
| `--no-submit` | No | `false` | Run the Stage 1 orchestrator in the current process; agent jobs still use Slurm. |

## `leanmarathon stage2 run`

Runs the Stage 2 Worker / Refiner loop for an initialized target.

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--owner` | Yes | - | GitHub owner or organization for the target repository. |
| `--repo` | Yes | - | Target repository name. |
| `--n` | No | Target config `batch_size` | Maximum concurrent Worker jobs in one batch. |
| `--max-rounds` | No | Target config value | Stage 2 round cap. |
| `--start-round` | No | Auto-resume | Manual first Stage 2 round index override. Normally omitted. |
| `--agent-resource` | No | Target config value | Override Worker/Refiner Slurm resource mode; `cpu` or `gpu`. |
| `--submit` | No | `true` | Submit the Stage 2 orchestrator as a Slurm job. |
| `--no-submit` | No | `false` | Run the Stage 2 orchestrator in the current process; agent jobs still use Slurm. |

## `leanmarathon auto`

Runs Stage 1 and then Stage 2 for an initialized target.

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--owner` | Yes | - | GitHub owner or organization for the target repository. |
| `--repo` | Yes | - | Target repository name. |
| `--max-review-rounds` | No | Target config value | Stage 1 review/refiner round cap. |
| `--max-rounds` | No | Target config value | Stage 2 round cap. |
| `--start-review-round` | No | `1` | First Target-Reviewer round index for Stage 1. |
| `--start-round` | No | Auto-resume | Manual first Stage 2 round index override. Normally omitted. |
| `--n` | No | Target config `batch_size` | Maximum concurrent Worker jobs in one Stage 2 batch. |
| `--skip-blueprinter` | No | `false` | Skip Blueprinter and start Stage 1 from Target-Reviewer / Refiner loop on current target `main`. |
| `--agent-resource` | No | Target config value | Override agent Slurm resource mode for Stage 1 and Stage 2; `cpu` or `gpu`. |
| `--submit` | No | `true` | Submit the parent end-to-end coordinator as a Slurm job. |
| `--no-submit` | No | `false` | Run the parent coordinator in the current process; Stage 1, Stage 2, and agent jobs still use Slurm according to their normal paths. |

## `leanmarathon status`

Shows local and GitHub status for an initialized target.

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--owner` | Yes | - | GitHub owner or organization for the target repository. |
| `--repo` | Yes | - | Target repository name. |

## `leanmarathon doctor`

Checks local dependencies and, optionally, one initialized target.

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--owner` | No | - | GitHub owner or organization for a target repository to include in checks. |
| `--repo` | No | - | Target repository name to include in checks. |
