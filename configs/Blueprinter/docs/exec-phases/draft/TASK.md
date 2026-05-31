# Phase 3 - Draft the Lean Blueprint File

## Required Inputs

This phase requires `lean_file_abs`, derived from `docs/inputs.yml`, plus the Phase 1 and Phase 2 findings.

## Required Context

Read:
1. `docs/references/decomposition.md` for the **gold-standard** decomposition rubric.
2. `docs/contracts/blueprint-format.md` for **HARD** Lean blueprint formatting rules; then,
3. `docs/contracts/latex-quality.md` for **HARD** LaTeX writing rules.

## 1. Decompose

### Objective

Design the optimal decomposition that **minimizes repair radius**,
where each node is subject to the rubric's constraints:
- **Formalizability under context isolation.** A sorry-filling agent must be able to discharge the node given only its direct dependencies — no other context from the blueprint.
- **Mathlib-style flat structure.** Each node should be provable by a sequence of tactics that *apply* Mathlib premises and/or its direct dependencies, not by proving things inline via nested `have` blocks. If a proof needs a `have` with a non-trivial justification, that `have` should be a top-level node.

## 2. Write Decomposition State Summary

Immediately after decomposition, write the decomposition strategy under `## Phase Summary` in `docs/state.md` using this format.

```
[Phase 3.1] Decomposition Strategy

Summary:
«one-paragraph summary of the optimal decomposition strategy»

Key decisions:
- «what was split and why»
- «what was kept together and why»
- «predicted failures and how they are isolated»
- «anything should be highlighted»
```

## 3. Write the Lean Blueprint File

The Lean blueprint file is located at `lean_file_abs`, derived from `docs/inputs.yml`. Use exactly this absolute path for every `apply-patch.apply_patch`, read, and `lean-lsp-mcp.lean_diagnostic_messages` call.

Following all rules strictly, for each node in topological order:

1. Write the `@[blueprint ...]` attribute with all metadata.
2. Write the formal type signature.
3. For `lemma`/`theorem`, use exactly one of the multiline placeholder proof bodies allowed by `docs/contracts/blueprint-format.md`; for definitional nodes, provide a complete formalization with no `sorry`.

After writing the complete file:

1. Run `lean-lsp-mcp.lean_diagnostic_messages` with `file_path = "<lean_file_abs>"` to check compilation.
2. Fix any messages that are NOT sorry-related.

### File Headers

The working Lean file should begin with:
```lean
import Mathlib
import Architect

set_option linter.all false
set_option maxHeartbeats 500000
```

## 4. Verification: Lean Compilation

Compile the working Lean file with `lean-lsp-mcp.lean_diagnostic_messages(file_path = "<lean_file_abs>")` and inspect the output.

- **PASS:** every emitted diagnostic is exactly one line matching the canonical "sorry" warning, with no continuation lines. Accepted variants:
  - `` <file>:<line>:<col>: warning: declaration uses `sorry` ``
  - `<file>:<line>:<col>: warning: declaration uses 'sorry'`
- **FAIL:** anything else.

## 5. Write Verification State Summary

After verification, write the verification result under `## Phase Summary` in `docs/state.md` using this format.

```
[Phase 3.2] Verification
- PASSED
```

## 6. Next

If verification passes, set `draft` to `pass`, set `deliver-pr` to `in-progress`, then read `docs/deliver/pr.md`.
