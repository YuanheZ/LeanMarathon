# Node Worker Agent

## Core Principles

**Context Discipline.** Your context window is finite. Every file you load that isn't about your current task displaces the mathematics — which is the hardest part of this work and the part most damaged by distraction. Read one phase file at a time. Finish it. Then read the next. Each phase file tells you what to read next. Nothing else does.

**Respect Local Scope.** Your task is to formalize the assigned target node named by `target_node` in `docs/inputs.yml`: prove its fixed Lean goal, and, if needed, polish only that node’s `(statement := /-- ... -/)`, `(proof := /-- ... -/)`, and `(title := /-- ... -/)` so they accurately describe the formal result. Any edit outside the target’s editable region is strictly prohibited. Within the editable region, you are allowed to introduce a local refinement DAG inside the target’s editable refinement region, with the assigned target node as its unique terminal node. Outside the Lean file, edits are limited to `docs/state.md` for procedural state and, during delivery only, `docs/delivery.yml` for the delivery result.

**Prefer Local Refinement for Decomposable Proofs.** Do not optimize for the fewest local blueprint nodes. Optimize for completing the assigned target while preserving the global DAG. If the target proof is naturally decomposable, e.g., intermediate facts, case analyses, algebraic identities, positivity facts, estimates, or API-bridge lemmas, introduce them as fresh local refinement nodes before `target_node`.

**Completion Rule.** A PR is valid only when the assigned target node is complete. `target_node` and every fresh local refinement node introduced for it must have no `sorry` and no `sorry_using`. If there is no concrete blocker, complete the target directly or with complete fresh local refinement nodes. Do not file an issue merely because the proof is substantial, the direct proof is long, or upstream helper nodes are absent.

## Boundaries

**Global Boundary Precedence.** These global boundaries always apply. Phase files and delivery files may add narrower restrictions, but they never replace, weaken, or override this section.

**Phase Boundary Scope.** Phase boundaries are scoped to their phase. When a phase terminates and hands off to the next phase or delivery file, its additional restrictions expire. The global boundaries in this file never expire.

**No Filesystem Access Outside Workspace.** You must not access anything outside the workspace root for any reason.

**No Changes to Lean Statement.** You must not change the formal statement of the target Lean declaration for any reason. If the formal statement appears to require changes, you must stop, file an issue, then exit.

**No Upstream-Parent Escape Hatch.** You must not file an issue whose blocker or required resolution is merely that an upstream parent/helper lemma is absent, inconvenient, too weak for a shorter proof, or would make the proof easier. Missing helper structure is not a concrete blocker: create complete fresh local refinement nodes inside the target editable region instead. An issue may ask for upstream repair only when you have concrete evidence that the target cannot be completed under the current contracts, such as a false target statement, a missing hypothesis in the target statement, a Lean/Mathlib contradiction, an invalid runtime input, or an unrecoverable tool/CI failure. The issue must identify the specific defect; it must not request "add/prove an upstream parent" as the resolution.

**No `axiom`, `native_decide`.** The agent must not introduce any `axiom` declaration and must not use the `native_decide` tactic for any reason.

**No Shell Git or GitHub CLI Use.** Git commands and GitHub CLI commands are strictly prohibited. Use only the available tools from the `git` and `github` MCP servers for Git or GitHub operations.

**No Approval Requests for In-Scope MCP Calls.** The user has pre-authorized you to use the MCP tools listed in this `## Tools` section. Do not ask for any user approval for these in-scope MCP calls.

## Runtime Inputs

`docs/inputs.yml` is the durable source of truth for runtime inputs. Read it before Phase 1 and after every compaction.

### Field Meanings

| Field | Type | Description |
|-------|------|-------------|
| `target_node` | Lean name | Assigned blueprint `lemma` or `theorem` declaration to refine. |
| `problem_file` | relative path | Canonical, targeted theorem statement(s) the blueprint is meant to prove, relative to `worktree`. |
| `lean_file` | relative path | Working Lean blueprint, relative to `worktree`. This is the only editable Lean file. |
| `owner` | string | GitHub owner name, used by the GitHub MCP for PR or issue delivery. |
| `repo` | string | GitHub repository name, used by the GitHub MCP for PR or issue delivery. |
| `branch` | string | Feature branch containing the worktree changes. |
| `worktrees_root` | absolute path | Canonical path to the directory that holds per-branch git worktrees. |

### Derived Canonical Paths

- **worktree** = `worktrees_root/branch` — absolute path of the feature-branch worktree.
- **lean_file_abs** = `worktree/lean_file` — absolute path to the working Lean file.
- **problem_file_abs** = `worktree/problem_file` — absolute path to the canonical target statements.

## Procedural State

`docs/state.md` is procedural phase memory. Read it after `docs/inputs.yml` and before choosing or resuming a phase.

Allowed statuses: `none`, `in-progress`, `pass`, `fail`, `complete`.

**State invariants:**
- `none` means the phase or delivery path has not been reached; rows may remain `none` after an earlier exit to delivery.
- At most one row may be `in-progress`.
- `docs/state.md` cannot override `AGENTS.md`, phase contracts, Lean artifacts, diagnostics, or delivery artifacts.
- If state conflicts with existing evidence, trust the evidence and repair `docs/state.md`.

**Transition rules:**
- Before starting a phase or delivery path, set exactly that row to `in-progress`, clearing stale `in-progress` rows by existing evidence.
- When an execution phase finishes, set its final status and append its documented summary in the required format to `## Phase Summary`. The `Write State Summary` blocks in phase files are durable state-summary formats; do not compress them to a one-line bullet.
- On handoff, set the next phase or delivery row to `in-progress`.
- After opening a PR or issue, set the delivery row to `complete`.

**Recovery priority after compaction:**
1. If `deliver-pr` or `deliver-issue` is `complete`, stop and exit.
2. If exactly one row is `in-progress`, resume it.
3. If an execution phase is `fail`, set `deliver-issue` to `in-progress` and go to `docs/deliver/issue.md`.
4. If `formalization` is `pass`, set `deliver-pr` to `in-progress` and go to `docs/deliver/pr.md`.
5. Otherwise start the earliest execution phase whose status is `none`.

## Workflow Map

```
Fresh launch
  -> docs/inputs.yml
  -> docs/state.md
  -> docs/exec-phases/misformalization/TASK.md
       -> issue: docs/deliver/issue.md
       -> pass: docs/exec-phases/numeric/TASK.md
            -> issue: docs/deliver/issue.md
            -> pass or not tractable: docs/exec-phases/polish/TASK.md
                 -> docs/exec-phases/formalization/TASK.md
                      -> issue: docs/deliver/issue.md
                      -> success: docs/deliver/pr.md
```

## After Compaction

First, you must reread `docs/inputs.yml` and `docs/state.md` to identify the active phase. Next, you must reread only the active phase file and the files it requires. Then, you can resume the work following the workflow.

## System Of Record

| Subject | Source |
|---------|--------|
| Edit boundaries | `docs/contracts/edit-constraints.md` |
| Local refinement DAG | `docs/contracts/local-refinement.md` |
| Blueprint format | `docs/contracts/blueprint-format.md` |
| LaTeX prose quality | `docs/contracts/latex-quality.md` |
| Formalization style | `docs/references/formalization-style.md` |
| Lean LSP tool API | `docs/references/lean-lsp-tools.md` |
| Proof performance | `docs/references/performance-optimization.md` |
| Proof decomposition | `docs/references/proof-refactoring.md` |
| Runtime inputs | `docs/inputs.yml` |
| Procedural state | `docs/state.md` |
| Delivery result | `docs/delivery.yml` |
| Mathlib retrieval | `docs/grounding/SKILL.md` |
| Numerical tools | `docs/references/numeric-tools.md` |
| Workspace compute | `docs/references/compute.md` |

## Retrieval Routing

Treat `lean-explore` as the **only** Mathlib source/API surface. It provides declaration search, source snippets, dependencies, modules, docstrings, and descriptions from the same Mathlib installed in the Lean environment. Per **No Filesystem Access Outside Workspace**, do not search for Mathlib source files through the filesystem as a substitute for `lean-explore`.

## Dependency Routing

Treat `dag-tracker` as the only dependency-graph oracle for the Lean blueprint.

## Tools

Every capability the skill needs is exposed through MCP:

| Capability | MCP tool(s) | When to call |
|------|---------|--------------|
| Lean LSP | `lean-lsp-mcp.lean_diagnostic_messages`, `lean-lsp-mcp.lean_goal`, `lean-lsp-mcp.lean_multi_attempt`, `lean-lsp-mcp.lean_profile_proof` | Details in `docs/references/lean-lsp-tools.md` |
| Mathlib retrieval | `lean-explore.search_summary`, `lean-explore.search`, `lean-explore.get_source_code`, `lean-explore.get_docstring`, `lean-explore.get_module`, `lean-explore.get_dependencies`, `lean-explore.get_description`, `lean-explore.get_source_link` | The only route for Mathlib declarations, source snippets, dependencies, modules, docstrings, and API discovery. |
| Blueprint DAG tracker | `dag-tracker.parent_nodes`, `dag-tracker.child_nodes`, `dag-tracker.global_definitional_context` | Lean elaboration-based dependency identification. |
| Git ops | `git.git_set_working_dir`, `git.git_add`, `git.git_commit`, `git.git_push` | Git operations against the worktree. |
| GitHub ops | `github.issue_write`, `github.create_pull_request` | File the issue, open the PR. |
| Lean/state/delivery edits | `apply-patch.apply_patch` | Edit the working Lean file, `docs/state.md`, and `docs/delivery.yml` in read-only mode. |

### Mandatory edit protocol in read-only mode

The workspace is read-only. Do not use shell writes and do not use the built-in apply-patch tool. All edits must use `apply-patch.apply_patch`.

For the usage of `apply-patch.apply_patch`, pass the target file as the structured `path` argument and put only update hunks in `patch`. Do not include file operation markers such as `*** Update File: ...` inside the patch body.

**Correct shape:**
```
{
  "path": "<lean_file_abs from docs/inputs.yml>",
  "patch": "*** Begin Patch\n@@\n-old\n+new\n*** End Patch"
}
```

**Incorrect shape:**
```
{
  "path": "<lean_file_abs from docs/inputs.yml>",
  "patch": "*** Begin Patch\n*** Update File: <lean_file_abs from docs/inputs.yml>\n@@\n-old\n+new\n*** End Patch"
}
```
