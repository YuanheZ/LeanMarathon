# Phase 4 - Formalization

## Required Inputs

This phase requires `target_node`, `lean_file`, and `lean_file_abs` from `docs/inputs.yml`.

## Required Contracts

Before editing, read:

1. `docs/contracts/edit-constraints.md`
2. `docs/contracts/local-refinement.md`
3. `docs/contracts/blueprint-format.md`
4. `docs/contracts/latex-quality.md`
5. `docs/references/formalization-style.md`
6. `docs/grounding/SKILL.md`

## Reference Docs — Consult on Demand

The docs below are **not** read up front. Consult a doc only when the situation it covers arises, and read only the part you need.

- `docs/references/lean-lsp-tools.md` — the Lean LSP tool API (`lean_diagnostic_messages`, `lean_goal`, `lean_multi_attempt`, `lean_profile_proof`). Consult a tool's entry before you call it, for its parameters and return shape.
- `docs/references/performance-optimization.md` — **500 lines, token-heavy. Do not read whole.** Consult when a proof or tactic compiles slowly or times out. **Grep by symptom:** match your observed failure — WHNF / `isDefEq` timeout, deterministic (nested-application) timeout, declaration-level timeout, slow `simp` — to its Quick Reference table, then read only that section.
- `docs/references/proof-refactoring.md` — **846 lines, token-heavy. Do not read whole.** Consult when a proof body grows long or repeats structure. **Grep by topic:** locate the refactoring pattern you need from its decision tree, then read only that pattern.

## Objective

Formalize the assigned target node inside its editable region. The target node's formal Lean statement is fixed. Complete the target directly, or complete it using fresh local refinement nodes when useful. Update editable proof text fields when needed so they accurately describe the final formal result and proof.

If fresh local nodes are introduced, the local refinement must be self-contained in the sense of `docs/contracts/local-refinement.md`: the assigned target node is the unique terminal node, every fresh local node is wired into the local DAG, and every external proof dependency is an existing blueprint proof node declared earlier in the file.

## Local Refinement Decision Rule

Use local refinement only to complete the target. Fresh local nodes are allowed when they help decompose the proof, but every fresh local node must also be complete before delivery. Do not create placeholder local nodes or deliver any unfinished local node.

## Curing Gaps in the Proof Text

The target node's `(proof := /-- ... -/)` text is a natural-language proof derived from a fallible source. It may be incomplete, hand-waved, or contain a flawed step. A gap or flaw in the proof text is **not, by itself, a blocker**: cure it by introducing complete local refinement nodes inside the target editable region, exactly as for any decomposable proof. If the proof needs a helper result the blueprint does not already provide, add it as a fresh local node and complete it — an absent or later-declared upstream helper is never a reason to file an issue. "I cured a gap in the proof text with local refinement" is the expected outcome.

File an issue only when the obstruction is genuinely beyond this phase's reach: the target's fixed formal statement is misformalized, false, or cannot be proved at all. Record the gap and your local cure in the Phase 4 state summary.

## Phase Boundaries

**Target-Region-Only Edit.** This phase grants no extra permission to reshape the blueprint, change formal Lean statements, bypass proof obligations, or edit outside the target editable region. Required `docs/state.md` updates are also allowed.

**Proof Search Flexibility.** This phase intentionally does not prescribe a fixed tactic workflow. Use the proof text, local context, Mathlib retrieval, Lean feedback, and local refinement as needed, while staying inside the boundary.

## Write State Summary

When this phase finishes, append this block under `## Phase Summary` in `docs/state.md`:

```
[Phase 4] Formalization
- Proof approach: «the overall strategy»
- Local refinement nodes introduced: «labels and why each was needed» | (none — direct proof)
- Proof-text gaps encountered and how cured locally: «the gap, and the local refinement that closed it» | (none)
- If filing an issue: the concrete evidence that the target statement is misformalized, false, or genuinely unprovable
- Verdict: pass | fail
```

## Termination

This phase has only two admissible outcomes:
```
Can this phase finish while obeying every global boundary and hard contract?
├──> Yes: produce a complete proof, set `formalization` to `pass`, write the `[Phase 4]` summary block, set `deliver-pr` to `in-progress`, then go to `docs/deliver/pr.md`.
└──> No: set `formalization` to `fail`, write the `[Phase 4]` summary block, set `deliver-issue` to `in-progress`, then go to `docs/deliver/issue.md`.
```

**Remarks:**
- Successful completion means the target has a complete direct proof or a complete proof using fresh local refinement nodes. In all cases, the formal Lean statement is unchanged. If fresh local nodes exist, every one is inside the editable region, wired into the target's local DAG, and complete. The final editable text fields accurately describe the final formal result and proof, the target and any local refinement satisfy `docs/contracts/edit-constraints.md`, `docs/contracts/local-refinement.md`, `docs/contracts/blueprint-format.md`, and `docs/contracts/latex-quality.md`, and Lean diagnostics report no errors and no warnings caused by this phase.
- If completion would require violating any global boundary or hard contract, you must stop formalization, exit from this phase, and go to `docs/deliver/issue.md`.
- Do not file an issue merely because the proof appears large or difficult. File an issue only for concrete blockers.
