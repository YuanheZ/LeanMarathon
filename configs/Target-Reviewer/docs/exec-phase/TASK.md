# Target Verification against Problem Source

## Purpose

Audit the Lean blueprint targets against the canonical problem source. This phase has two responsibilities:
1. Verify coverage: every mathematical claim in `problem_file_abs` that needs to be proved is represented by a `theorem` declaration in `lean_file_abs`.
2. Verify formalization fidelity: each `theorem` declaration faithfully states the corresponding source claim. A misformalized statement is one that type-checks but does not represent the intended mathematical claim.

## Stance

**Be skeptical.** Treat both coverage and formalization as unverified until you have checked the source claims against all `theorem` declarations.

## Required Inputs & Context

This phase requires `problem_file_abs` and `lean_file_abs` from `docs/inputs.yml`.

Read in this order:
1. Read the canonical problem source.
2. Read all Lean `theorem` declarations.

## 1. Build Understanding from Context

Work through the questions below. Their purpose is to put you in a position to recognize misformalization when you audit it; they are not a deliverable.

1. What does the canonical problem source state?
2. What are the source's quantifiers, types, and domains, in fully explicit form?
3. What implicit hypotheses does the source rely on that must be made explicit in Lean?
4. What are the source's conclusions, in fully explicit form?

## 2. Coverage Check

Every claim in `problem_file_abs` must be covered by a `theorem` declaration. Everything else in the blueprint is `definition` or `lemma` in service of these targets.

If the source phrases a target as a question, read it as asking the blueprint to prove the statement inside the question, and check that the Lean theorem states that same statement with the same hypotheses, domains, quantifiers, and conclusion.

## 3. Falsification Attempt on the Lean Statement

Audit each `theorem` node's Lean statement and actively try to break it, rather than checking whether it superficially fits. Look for any way the Lean statement fails to match what it is supposed to be. The patterns below are common shapes such failures take — useful as examples, not as the boundary of what counts. A defect that fits none of them is still a defect.
- **too weak** — its conclusion does not discharge what downstream needs, or (for theorems) does not match the canonical conclusion;
- **too strong** — its hypotheses are not implied by what upstream provides, or (for theorems) it claims more than the canonical source;
- **wrongly quantified** — wrong domain, wrong index type, wrong scope of universals or existentials;
- **missing a required hypothesis** — a precondition the specification requires is absent;
- **carries an impossible (vacuous) hypothesis** — a precondition no input can satisfy, making the statement trivially true;
- **proves the wrong conclusion** — the conclusion is well-formed but is not the one the specification calls for;
- **mismatched formalization** — a Mathlib API call, definitional node, or cast denotes a different mathematical object than the actual needs.

## Termination

This phase has only two admissible outcomes. Use the tree below to decide which applies.
```
Do you find any missing source claim, unsupported extra `theorem` target, or misformalized `theorem` statement?
├──> Yes: go to `docs/deliver/issue.md`.
└──> No: clean exit.
```
