# Phase 1 - Understand

Before starting this phase, set `understand` to `in-progress` in `docs/state.md`.

## Required Inputs

This phase requires `problem_file_abs` and `proof_file_abs`, derived from `docs/inputs.yml`.

Read `problem_file_abs` and `proof_file_abs` **fully**.

## 1. Identify target theorems

Every claim in `problem_file_abs` becomes a `theorem` declaration. Everything else in the blueprint is `definition` or `lemma` in service of these targets.

**Decision:**
```
Any target answer-based (e.g., "find all", "determine the value")?
├── No  → use the target statements directly.
└── Yes → read `docs/references/reframing.md`, then use the reframed targets.
```

## 2. Identify mathematical domains

List the domains involved (analysis, algebra, combinatorics, number theory, etc.).

## 3. Assess proof quality

For each target, note:
- Logical gaps
- Hand-waves ("it is easy to see", "by a standard argument")
- Incorrect steps
- Missing cases

These are not problems to fix. Record them and move on.

## 4. Write State Summary

Write one merged Phase 1 summary under `## Phase Summary` in `docs/state.md` using this format.

```
[Phase 1] Understand

[Phase 1.1] Target Theorems
- T1: «one-line statement summary»
- T2: «one-line statement summary»

[Phase 1.2] Mathematical Domains
- «domain»
- «domain»

[Phase 1.3] Proof Quality
- «step/location in proof_file_abs» → «concise flaw summary»
- «step/location in proof_file_abs» → «concise flaw summary»
- (none found)
```

## 5. Next

Set `understand` to `pass`, set `grounding` to `in-progress`, then read `docs/exec-phases/grounding/TASK.md`.
