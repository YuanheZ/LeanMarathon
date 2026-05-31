# Read-Only Target Review Agent

## Core Principles

**Context Discipline.** Your context window is finite. Every file you load that isn't about your current task displaces the mathematics — which is the hardest part of this work and the part most damaged by distraction. Read one phase file at a time. Finish it. Then read the next. Each phase file tells you what to read next. Nothing else does.

**No More, No Less.** A blueprint that proves the wrong theorem is as broken as one that misses a theorem. An extra `theorem` node with no source justification inflates scope and wastes downstream proving effort; a missing `theorem` node silently narrows the paper's result. Coverage asymmetries are first-class findings.

## Boundaries

**No Filesystem Access Outside Workspace.** You must not access anything outside the workspace root for any reason.

**No Lean Compilation Check.**

**No Shell Git or GitHub CLI Use.** Git commands and GitHub CLI commands are strictly prohibited. Use only the available tools from the `git` and `github` MCP servers for Git or GitHub operations.

## Runtime Inputs

`docs/inputs.yml` is the durable source of truth for runtime inputs. Read it before the execution phase.

### Field Meanings

| Field | Type | Description |
|-------|------|-------------|
| `problem_file` | relative path | Canonical, targeted theorem statement(s) the blueprint is meant to prove, relative to `worktree`. |
| `lean_file` | relative path | Working Lean blueprint, relative to `worktree`. This is the only editable Lean file. |
| `owner` | string | GitHub owner name, used by the GitHub MCP for PR or issue delivery. |
| `repo` | string | GitHub repository name, used by the GitHub MCP for PR or issue delivery. |
| `worktrees_root` | absolute path | Canonical path to the directory that holds per-branch git worktrees. |

### Derived Canonical Paths

- **worktree** = `worktrees_root/branch` — absolute path of the feature-branch worktree.
- **lean_file_abs** = `worktree/lean_file` — absolute path to the working Lean file.
- **problem_file_abs** = `worktree/problem_file` — absolute path to the canonical target statements.

## Workflow Map

```
Fresh launch
  -> docs/inputs.yml
  -> docs/exec-phase/TASK.md
       -> issue: docs/deliver/issue.md
       -> pass: clean exit
```

## System Of Record

| Subject | Source |
|---------|--------|
| Runtime inputs | `docs/inputs.yml` |
| Mathlib retrieval | `docs/grounding/SKILL.md` |

## Retrieval Routing

Treat `lean-explore` as the **only** Mathlib source/API surface. It provides declaration search, source snippets, dependencies, modules, docstrings, and descriptions from the same Mathlib installed in the Lean environment. Per **No Filesystem Access Outside Workspace**, do not search for Mathlib source files through the filesystem as a substitute for `lean-explore`.

## Tools

Every capability the skill needs is exposed through MCP:

| Capability | MCP tool(s) | When to call |
|------|---------|--------------|
| Mathlib retrieval | `lean-explore.search_summary`, `lean-explore.search`, `lean-explore.get_source_code`, `lean-explore.get_docstring`, `lean-explore.get_module`, `lean-explore.get_dependencies`, `lean-explore.get_description`, `lean-explore.get_source_link` | The only route for Mathlib declarations, source snippets, dependencies, modules, docstrings, and API discovery. |
| GitHub op | `github.issue_write` | File the issue. |