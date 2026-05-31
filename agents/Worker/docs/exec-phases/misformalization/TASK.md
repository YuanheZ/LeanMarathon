# Phase 1 - Misformalization Check

Before starting this phase, set `misformalization` to `in-progress` in `docs/state.md`.

## Purpose

Catch errors in the target node's Lean formal statement before wasting time proving them. A misformalized statement is one that type-checks but does not faithfully represent the intended mathematical claim.

## Stance

**Be skeptical.** Your default assumption is that the formal statement is wrong until you have verified all required checks below.

## Verification Target

The artifact under test is the **target node's formal Lean statement**. Nothing else.

The target node's `(statement := /-- ... -/)` text is generated output, produced by the same process that produced the formal Lean. It can be consulted as a *hint* about author intent, but it cannot validate the formal Lean: if they agree, they may both be wrong; if they disagree, you do not yet know which is wrong.

The same skepticism applies, in lesser degree, to upstream and downstream nodes' generated text. Their formal Lean statements are more trustworthy than their English, but neither is ground truth.

## Required Inputs & Context

This phase requires `target_node`, `lean_file_abs`, and `problem_file_abs` from `docs/inputs.yml`.

Before reading upstream or downstream context, call `dag-tracker.parent_nodes` and `dag-tracker.child_nodes` with `target_node` (for example, `{"lean_name":"T"}`). Use those returned Lean names as the parent and child node lists.

Read in this order:
1. The target node's Lean statement and `(statement := /-- ... -/)`.
2. Each parent node's Lean statement and `(statement := /-- ... -/)`.
3. Each child node's Lean statement and `(statement := /-- ... -/)`.
4. Read the canonical problem source.

## Objective

Verification has two ingredients: an understanding of what this statement is supposed to be, drawn from the context above, and a falsification stance applied to the Lean statement. They are not separate steps producing separate artifacts — they are two faces of one cognitive operation.

### Build Understanding from Context

Work through the questions below. Their purpose is to put you in a position to recognize misformalization when you audit it; they are not a deliverable.

1. What does the canonical problem source state?
2. What are the source's quantifiers, types, and domains, in fully explicit form?
3. What implicit hypotheses does the source rely on that must be made explicit in Lean?
4. Why does the target node exist in the proof architecture?
5. What is available from upstream as hypothesis?
6. What conclusion does downstream require, and in what form?

### Falsification Attempt on the Lean Statement

Audit the Lean statement and actively try to break it, rather than checking whether it superficially fits. Look for any way the Lean statement fails to match what it is supposed to be. The patterns below are common shapes such failures take — useful as examples, not as the boundary of what counts. A defect that fits none of them is still a defect.
- **too weak** — its conclusion does not discharge what downstream needs, or (for theorems) does not match the canonical conclusion;
- **too strong** — its hypotheses are not implied by what upstream provides, or (for theorems) it claims more than the canonical source;
- **wrongly quantified** — wrong domain, wrong index type, wrong scope of universals or existentials;
- **missing a required hypothesis** — a precondition the specification requires is absent;
- **carries an impossible (vacuous) hypothesis** — a precondition no input can satisfy, making the statement trivially true;
- **proves the wrong conclusion** — the conclusion is well-formed but is not the one the specification calls for;
- **mismatched formalization** — a Mathlib API call, definitional node, or cast denotes a different mathematical object than the actual needs.

## Phase Boundary

**Read-Only Check.** Do not edit the Lean file, the target prose fields, or any docs other than required `docs/state.md` updates. Do not treat the target node's generated statement text as ground truth.

## Write State Summary

When this phase finishes, append this block under `## Phase Summary` in `docs/state.md`:

```
[Phase 1] Misformalization
- Intended statement (from problem source + parent/child nodes): «what the formal statement should say»
- Falsification attempts: «the failure patterns checked, and what each showed»
- Verdict: pass | fail — «the specific defect found, or why none was found»
```

## Termination

This phase has only two admissible outcomes. Use the tree below to decide which applies.
```
Do you find any issue with the formal Lean statement?
├──> Yes: set `misformalization` to `fail`, write the `[Phase 1]` summary block, set `deliver-issue` to `in-progress`, then go to `docs/deliver/issue.md`.
└──> No: set `misformalization` to `pass`, write the `[Phase 1]` summary block, set `numeric` to `in-progress`, then go to `docs/exec-phases/numeric/TASK.md`.
```