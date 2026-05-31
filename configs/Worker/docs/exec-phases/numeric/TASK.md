# Phase 2 - Numerical Falsification

## Purpose

Catch errors in the target node's formal Lean statement by stress-testing the statement via concrete numerical simulations.

## Required Input

This phase requires `target_node` from `docs/inputs.yml` and the target node's Lean statement.

## Conditional Required Context

If the statement is numerically verifiable, you must read these references before running any simulation:
1. `docs/references/numeric-tools.md`
2. `docs/references/compute.md`

## Objective

The artifact under test is the **target node's formal Lean statement**. By the time this phase runs, that statement has passed misformalization check, so it can be treated as a faithful encoding of the intended claim. Your job here is to stress-test the claim itself.

### Numerical Falsification Attempt

If the Lean statement is numerically verifiable, try to break it with numerical simulations. Before testing, ask yourself:
```
how could this Lean statement fail?
```
Let that question drive the simulations you set up and attempt to find any evidence that refutes the statement.

If the Lean statement is not numerically verifiable, state that explicitly in your output:
```
Numerical falsification: not verifiable.
```

## Performance Expectations

For numerically verifiable claims, do not default to scalar Python with only standard-library packages such as `math`. Prefer suitable specialized numerical packages from the workspace environment.

Do not default to plain brute-force search. Prefer an efficient formulation using vectorized, compiled, parallelized, JIT-compiled, or otherwise optimized computation when such a formulation is available.

## Phase Boundary

**Read-Only Numerical Simulation with Runtime Cap.** Do not edit files other than required `docs/state.md` updates, write scripts, install packages, or access anything outside the workspace. `python3` is provided by the workspace virtual environment. Run self-contained commands only and every numerical simulation command must have an explicit wall-clock cap of at most five minutes, in the form:
```
timeout 300s python3 -c "..."
```

## Write State Summary

When this phase finishes, append this block under `## Phase Summary` in `docs/state.md`:

```
[Phase 2] Numerical Falsification
- Numerically verifiable: yes | no — «why»
- Simulations run: «what was set up, the parameters, and the results»
- Verdict: pass | fail — «counterexample found, or why the statement survived»
```

## Termination

This phase has only three admissible outcomes. Use the tree below to decide which applies.
```
If the Lean statement is numerically verifiable?
├──> Yes: Does the Lean statement pass all numerical simulation you run?
│     ├──> Yes: set `numeric` to `pass`, write the `[Phase 2]` summary block, set `polish` to `in-progress`, then go to `docs/exec-phases/polish/TASK.md`
│     └──> No: set `numeric` to `fail`, write the `[Phase 2]` summary block, set `deliver-issue` to `in-progress`, then go to `docs/deliver/issue.md`
└──> No: set `numeric` to `pass`, write the `[Phase 2]` summary block, set `polish` to `in-progress`, then go to `docs/exec-phases/polish/TASK.md`
```
