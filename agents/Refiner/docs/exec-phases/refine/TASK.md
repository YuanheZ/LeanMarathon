# Phase 2 - Refine

Before starting this phase, set `refine` to `in-progress` in `docs/state.md`.

## Required Inputs & Context

This phase requires `lean_file_abs`, derived from `docs/inputs.yml`, plus the Phase 1 illness areas and fix plans recorded in `docs/state.md`.

Read `docs/grounding/SKILL.md` for Mathlib grounding.

## Required Contracts

Read in order:
1. `docs/contracts/blueprint-format.md` - **HARD** Lean blueprint formatting rules.
2. `docs/contracts/latex-quality.md` - **HARD** LaTeX writing rules.

## 1. Refine

The Lean blueprint file is at `lean_file_abs`, derived from `docs/inputs.yml`. Use exactly this absolute path for every `apply-patch.apply_patch`, targeted read, and `lean-lsp-mcp.lean_diagnostic_messages` call.

**Objective.** Work through each fix plan to cure all illness areas, following the contracts strictly. The proof-body discipline below governs every `lemma` / `theorem` body you touch.

**Source-anchored execution.** Execute each fix plan according to its Phase-1 classification recorded in `docs/state.md`. A **drift** realignment restores the source proof's architecture — remove the invented structure the blueprint accreted. A **source-gap** repair writes a genuine corrected argument; it is expected and correct for that repair to diverge from `proof_file`. A repair that merely relocates a `sorry` or renames structure, without restoring source fidelity or closing the gap, is not a valid fix — do not deliver it.

### Proof-body discipline

You never write Lean tactic proofs. Decide every `lemma`/`theorem` body by walking this tree:
```
Is the node NEW (inserted) or EXISTING (inherited from `lean_file_abs`)?
├── NEW: body is `by sorry` or `by sorry_using [deps]`
└── EXISTING: current body shape?
    ├── placeholder (`by sorry` / `by sorry_using`): keep it; align `sorry_using` with new `\cref` set if prose changed
        └── complete tactic proof: still compiles after your statement/type edits?
                ├── YES: preserve the complete proof body byte-identical to the input blueprint
                        └── NO: wholesale-replace with `by sorry` or `by sorry_using [deps]`
```
`deps` stands for the Lean names cited via `\cref` in the node's proof prose. Three sub-boundaries hold while you walk this tree:
- **Compilation is decided by the tool.** "Still compiles" is determined by `lean-lsp-mcp.lean_diagnostic_messages`, never by you.
- **Wholesale replacement is recorded, not negotiated.** When a complete proof is wholesale-replaced with a placeholder because the statement edit invalidated it, record it for the PR summary and move on **without hesitation**.
- **No partial edit to a complete-proof body.** No tactic tweak, no one-line patch, no identifier rename inside the proof.

## 2. Verification: Lean Compilation

Compile the working Lean file with `lean-lsp-mcp.lean_diagnostic_messages(file_path = "<lean_file_abs>")` and inspect the output.

- **PASS:** no diagnostics, or every emitted diagnostic is exactly one line matching the canonical "sorry" warning, with no continuation lines. Accepted variants:
  - `` <file>:<line>:<col>: warning: declaration uses `sorry` ``
  - `<file>:<line>:<col>: warning: declaration uses 'sorry'`
- **FAIL:** anything else.

If verification fails because a complete proof no longer compiles after a statement/type edit, apply the proof-body discipline: wholesale-replace that complete proof with `by sorry` or `by sorry_using [deps]`, record the downgrade, and re-run `lean-lsp-mcp.lean_diagnostic_messages`.

## 3. Write State Summary

After refinement and verification, write one merged Phase 2 summary under `## Phase Summary` in `docs/state.md` using this format.

```
[Phase 2] Refine

[Phase 2.1] Refine Summary

Edit Summary
- Illness Area 1: classification «drift | source-gap»; «nodes added/changed/deleted and the issue(s) closed»
- Illness Area 2: ...

Repair Reasoning
- Illness Area 1: for a drift fix, the invented structure removed to realign to the source; for a source-gap fix, the corrected mathematics and why it closes the gap
- Illness Area 2: ...

Complete-Proof Downgrades
- «node label / Lean name»: «one-sentence rationale»
- (none)

[Phase 2.2] Verification
- PASSED: `lean-lsp-mcp.lean_diagnostic_messages` emitted only accepted diagnostics.
```

## 6. Next

If verification passes, set `refine` to `pass`, set `deliver-pr` to `in-progress`, then read `docs/deliver/pr.md`.
