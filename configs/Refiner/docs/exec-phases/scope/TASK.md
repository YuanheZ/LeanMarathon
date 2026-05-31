# Phase 1 - Scope

Before starting this phase, set `scope` to `in-progress` in `docs/state.md`.

## Required Inputs

This phase requires `problem_file_abs`, `proof_file_abs`, and `issues_file_abs`, derived from `docs/inputs.yml`.

Read `problem_file_abs` **fully** before scoping. Then read `issues_file_abs` **fully**:
- If `issues_file_abs` is a file, read that file.
- If `issues_file_abs` is a directory, read every `#*.md` file in numeric issue order.

Do **not** read `proof_file_abs` end-to-end. It is the raw source proof; consult it token-efficiently, per illness area, in the classification step below.

## Conditional Required Context

If numerical simulation can materially help plan the fix, read these references before running any simulation:
1. `docs/references/numeric-tools.md`
2. `docs/references/compute.md`

## 1. Identify the illness area(s)

An **illness area** is a connected sub-DAG of nodes that an issue (or a set of correlated issues) forces you to consider. A node belongs to an illness area when it is one of:

- **Directly named or demanded by an issue** — an existing label some issue in `issues_file_abs` points at, or a new label some issue requires.
- **Reached by propagation** — a node that either cites, or is cited by, a node already in the area (directly or transitively via `sorry_using` / `\cref`), where the planned edit plausibly requires this node to change too.

**Tool guidance:** Use `dag-tracker.parent_nodes` and `dag-tracker.child_nodes` with each relevant Lean name (for example, `{"lean_name":"T"}`) to identify direct upstream and downstream proof nodes. Repeat on newly included nodes only when transitive propagation is needed for the issue.

**Reminder:** Everything outside the illness area(s) is off-limits, per **No scope creep** boundary.

## 2. Classify each illness area against the source proof

`proof_file_abs` is the raw source proof. It is fallible and may itself contain genuine gaps, hand-waves, or flawed steps. Read it **token-efficiently**: for each illness area, locate the passage(s) corresponding to its nodes — by node titles, statements, and `\cref` labels — and read only those bounded regions. Do not read `proof_file_abs` end-to-end; this mirrors the **No End-to-End Blueprint Reads** boundary.

Classify each illness area as exactly one of:
- **drift** — the blueprint is what is wrong: a node's architecture was reshaped away from the source proof, or its statement was mis-encoded relative to the source proof or contradicts the canonical `problem_file`. The source proof's step here is sound. Fix: realign the blueprint to the source proof / `problem_file`.
- **source-gap** — the blueprint faithfully reflects the source proof, but the source argument here is itself genuinely incomplete, hand-waved, or wrong. The issue exposes a real hole in the source. Fix: a genuine mathematical repair that legitimately diverges from `proof_file`.

A misformalized, wrong, or unprovable statement is a *symptom*, not a separate class — classify it by cause:
- a **target node** (a `problem_file` theorem) with a wrong statement is always **drift**: `problem_file` is canonical ground truth and cannot itself be at fault;
- an **intermediate node** with a wrong or unprovable statement is **drift** if the blueprint mis-stated a step the source proof gets right, or **source-gap** if it faithfully encodes a step the source proof itself gets wrong.

Record, per illness area, the `proof_file` or `problem_file` passage(s) consulted and the concrete evidence for the classification.

## 3. Plan the fix

For each illness area, plan a coherent fix that closes all of its issues at once. The fix is keyed to the area's Phase-2 classification:

- **drift** → make the blueprint match the source proof / `problem_file`: remove invented structure, restore the architecture the source argument uses, and correct any mis-encoded node statement.
- **source-gap** → a genuine mathematical repair: a corrected NL argument and correctly-typed new nodes that actually close the gap. This repair legitimately diverges from `proof_file` because the source was wrong here. It must close the gap, not relocate it elsewhere.

A fix that merely reshapes or renames nodes to silence an issue — without restoring source fidelity or closing a source gap — is not a valid fix.

### Numerical Simulation

Numerical simulation is **optional and non-proving**. Use it only when it can materially help plan the fix.

#### Performance Expectations

Do not default to scalar Python with only standard-library packages such as `math`. Prefer suitable specialized numerical packages from the workspace environment.

Do not default to plain brute-force search. Prefer an efficient formulation using vectorized, compiled, parallelized, JIT-compiled, or otherwise optimized computation when such a formulation is available.

#### Hard Constraints

**Read-Only Numerical Simulation with Runtime Cap.** Do not edit files other than required `docs/state.md` updates, write scripts, install packages, or access anything outside the workspace. `python3` is provided by the workspace virtual environment. Run self-contained commands only and every numerical simulation command must have an explicit wall-clock cap of at most five minutes, in the form:
```
timeout 300s python3 -c "..."
```

## 4. Write State Summary

Write one merged Phase 1 summary under `## Phase Summary` in `docs/state.md` using this format. The current output format is the state-summary format.

```
[Phase 1] Scope

[Phase 1.1] Illness Areas
 
Illness Area 1
  Affected nodes: «label», «label», ...
  Issues: #N₁[, #N₂, ...]

Illness Area 2
  ...
 
Coverage:
  #N₁ → Illness Area k
  #N₂ → Illness Area k
  ...

[Phase 1.2] Source Classification

Illness Area 1
  proof_file passage(s) consulted: «section / lemma / line range»
  Classification: drift | source-gap
  Evidence: «what in proof_file, versus the blueprint, supports this verdict»

Illness Area 2
  ...

[Phase 1.3] Fix Plans

Illness Area 1
  Fix: «graph modification that cures this area, consistent with the [Phase 1.2] classification»

Illness Area 2
  Fix: «graph modification that cures this area, consistent with the [Phase 1.2] classification»

...
```

**Notation:**
- **label** - the string inside a node's `@[blueprint "..."]` attribute (e.g. `lem:c-w-spec`, `def:psi-d`, `thm:gen`); the same form LaTeX uses in `\cref{...}`. A proposed label for a node that does not yet exist is prefixed `NEW:` (e.g. `NEW:fourier-bound`) so it is visibly distinct from existing labels.
- **#N** - a GitHub issue number, drawn from `issues_file_abs`.

**Self-validation:**
- every issue in `issues_file_abs` appears in Coverage. If not, revise in place.
- every illness area has a `[Phase 1.2]` classification with cited `proof_file` evidence. If not, revise in place.
- every illness area gets the fix plan. If not, revise in place.

## 5. Next

Set `scope` to `pass`, set `refine` to `in-progress`, then read `docs/exec-phases/refine/TASK.md`.
