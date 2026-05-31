# Lean LSP Tools - API Reference

API documentation for the four available Lean LSP MCP tools.

## `lean_diagnostic_messages` - Compilation Diagnostics

Get compiler diagnostics (errors, warnings, infos) for a Lean file.

**When to use:** after every edit, to check whether the file compiles.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | yes | — | Absolute or project-root-relative path to the Lean file. |
| `start_line` | integer ≥ 1 | no | (all) | Filter diagnostics from this line. |
| `end_line` | integer ≥ 1 | no | (all) | Filter diagnostics to this line. Pair with `start_line` for a bounded-range check — far cheaper than a full-file scan. |
| `declaration_name` | string | no | (all) | Filter to a single declaration. **Slow** — the server first resolves the declaration's line range. |
| `severity` | string enum | no | (all) | One of `"error"`, `"warning"`, `"info"`, `"hint"`. Omit to return all levels. |
| `interactive` | boolean | no | `false` | Return verbose nested TaggedText with embedded widgets; use only when plain text is insufficient. |

**Returns** (`interactive=false`) — a `DiagnosticsResult`:
- `success` (bool) — `true` if the queried file/range has no errors.
- `timed_out` (bool) — `true` if elaboration timed out; results are partial, not a real build failure.
- `items` (list) — each entry `{severity, message, line, column}`. `severity` is a **string** (`error`/`warning`/`info`/`hint`); `line`/`column` are 1-indexed.
- `failed_dependencies` (list) — file paths of dependencies that failed to build (e.g. a broken import).

With `interactive=true` it returns `{diagnostics: [...]}` of interactive TaggedText objects instead.

**Examples** (`file_path` is always `lean_file_abs`, the worker's single working Lean file):
```
lean_diagnostic_messages(file_path=<lean_file_abs>)                                # whole file
lean_diagnostic_messages(file_path=<lean_file_abs>, start_line=120, end_line=180)   # bounded range
lean_diagnostic_messages(file_path=<lean_file_abs>, severity="error")              # errors only
```

Empty `items` with `success=true` means no diagnostics in scope. **Empty diagnostics alone does not confirm proof completion** — also verify with `lean_goal` that no goals remain. Proof complete = no remaining goals + clean diagnostics. A non-empty `failed_dependencies` means an import failed; fix that first.

## `lean_goal` - Proof Goals

Get the proof goal state at a position. The most important tool — use it often.

**When to use:** before writing a tactic (to see what must be proved) and after a tactic (to see what it accomplished).

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | yes | — | Absolute or project-root-relative path to the Lean file. |
| `line` | integer ≥ 1 | yes | — | Line number (1-indexed). |
| `column` | integer ≥ 1 | no | (omitted) | Column (1-indexed). Omit to get the before/after states for the whole line. |
| `format` | string enum | no | `"text"` | `"text"` (default) or `"structured"`. |

**Returns** — a `GoalState` with `line_context` (the source line) plus:
- when `column` is **omitted** — `goals_before` (goals at line start) and `goals_after` (goals at line end), showing how the line's tactic transforms the state;
- when `column` is **given** — `goals` (goals at that position).

Each goal is a **plain string** under `format="text"` (the default). Under `format="structured"` each goal is instead an object `{context: [{name, type}, …], goal, status, pretty}`, with `status` ∈ `open`/`complete`/`unknown`. An empty goal list (or "no goals") means the proof is complete at that point.

**Pro tip:** call `lean_goal` on a line that has a tactic, with `column` omitted, to see the before/after states and read exactly what that tactic does.

## `lean_multi_attempt` - Try Multiple Tactics

Try several tactics at a position **without modifying the file**; returns the resulting goal state and diagnostics for each. Use it to A/B-test candidate tactics and to read the exact error of ones that fail.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | yes | — | Absolute or project-root-relative path to the Lean file. |
| `line` | integer ≥ 1 | yes | — | Line number (1-indexed) where the tactics would be placed. |
| `snippets` | list of strings | yes | — | Tactics to try; 3+ recommended (e.g. `["simp", "ring", "omega"]`). |
| `column` | integer ≥ 1 | no | (tactic line) | Column (1-indexed) for an exact source position; omit for fast line-based attempts. |

**Returns** — a `MultiAttemptResult` `{items: [...]}`, one entry per snippet: `{snippet, goals (goal strings after the snippet), diagnostics (list of DiagnosticMessage), timed_out}`. An empty `goals` with no error in `diagnostics` means the snippet closed all goals.

Each snippet is a single-line tactic; chain multiple steps with `;`. This tool is for testing only — once you pick a winner, edit the file with `apply_patch` and verify with `lean_diagnostic_messages`.

**Workflow:** `lean_goal` to see the goal → think of 3-5 candidate tactics → `lean_multi_attempt` to test them all → pick the winner, edit the file → `lean_diagnostic_messages` to verify.

## `lean_profile_proof` - Performance Profiling

Run `lean --profile` on a theorem; returns per-line timing and category totals. **Slow** — do not run it on theorems that already hit the heartbeat limit.

**When to use:** a proof compiles slowly and you need to find which line(s) are expensive.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | yes | — | Absolute or project-root-relative path to the Lean file. |
| `line` | integer ≥ 1 | yes | — | Line where the theorem starts (1-indexed). |
| `top_n` | integer ≥ 1 | no | `5` | Number of slowest lines to return. |
| `timeout` | number ≥ 1 | no | `60.0` | Maximum seconds to wait. |

**Returns** — a `ProofProfileResult`: `ms` (total elaboration time in ms), `lines` (the slowest source lines, each `{line, ms, text}`), and `categories` (cumulative time by category, in ms). Focus on lines above ~20% of total `ms`; for fixes consult `performance-optimization.md`.
