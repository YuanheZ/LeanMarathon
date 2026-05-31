# Phase 3 - Check and Repair the Statement Text

## Required Contracts

Before editing, read:

1. `docs/contracts/edit-constraints.md`
2. `docs/contracts/latex-quality.md`

This phase requires `target_node` from `docs/inputs.yml`, the target node's Lean statement, and its current `(statement := /-- ... -/)` text.

## Objective

Compare the formal Lean statement with the target node's statement text, i.e. `(statement := /-- ... -/)`, against the LaTeX quality writing contract at `docs/contracts/latex-quality.md`.

The English statement is aligned only if it satisfies the contract and describes exactly the formal Lean statement. Repair it if it is vague, misleading, incomplete, stronger than the Lean statement, weaker than the Lean statement, or false as prose.

The repaired English must describe exactly the formal Lean statement: **no more and no less.** Do not use the English repair step for illegal behaviours, e.g., change the intended mathematics, conceal a suspected Lean statement error, or add claims not present in the Lean declaration type.

## Phase Boundary

**Statement-Text-Only Edit.** This phase may edit only the target node's `(statement := /-- ... -/)` text body, and only if repair is necessary. Required `docs/state.md` updates are also allowed. Do not edit the formal Lean declaration, proof body, proof text, title text, local refinement area, or any other file.

## Write State Summary

When this phase finishes, append this block under `## Phase Summary` in `docs/state.md`:

```
[Phase 3] Statement Text
- Outcome: unchanged | repaired — «what was vague/misleading/incomplete, and how it was fixed»
```

## Termination

This phase has only two admissible outcomes. Use the tree below to decide which applies.
```
Does the statement text already describe exactly the formal Lean statement and satisfy the LaTeX quality contract?
├──> Yes: set `polish` to `pass`, write the `[Phase 3]` summary block, set `formalization` to `in-progress`, then go to `docs/exec-phases/formalization/TASK.md`.
└──> No: edit the `(statement := /-- ... -/)` text only, then set `polish` to `pass`, write the `[Phase 3]` summary block, set `formalization` to `in-progress`, then go to `docs/exec-phases/formalization/TASK.md`.
```
