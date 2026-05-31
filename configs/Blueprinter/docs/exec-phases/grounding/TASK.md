# Phase 2 - Mathlib Grounding

## Required Context

Read:
1. `docs/references/api-example.md` as the good example for Pipelines 1 and 2 (DAR/SGR).
2. `docs/references/discovery-example.md` as the good example for Pipeline 3 (SAV).

## Hard constraint: restrict `lean-explore` search scope

Every call to a `lean-explore` search tool **must** pass the `packages` argument restricting the search to the canonical core + Mathlib set:
```json
"packages": ["Batteries", "Init", "Lean", "Mathlib", "Std"]
```

## 1. Mathlib API Identification

To identify the accurate Mathlib API for each mathematical concept, use both retrieval pipelines. Neither alone is sufficient — DAR discovers dependencies the summaries hide, SGR discovers identifiers the dependency graph misses.

### Pipeline 1: Dependency-Augmented Retrieval (DAR)

> `search_summary` → `get_dependencies` → re-`search_summary` novel names

#### Algorithm

```
results ← search_summary(query, limit=k)
for r in top-n results:
    deps ← get_dependencies(r.id)
novel ← deps \ {names in results}  # filter boilerplate (HAdd, Eq, etc.)
for name in novel:
    hits ← search_summary(name, limit=k)
for h in hits:
    get_source_code(h.id)  # extract type signatures for formalization
```

---

### Pipeline 2: Source-Grounded Retrieval (SGR)

> `search_summary` → `get_source_code` → extract identifiers from type signature → re-`search_summary`

#### Algorithm

```
results ← search_summary(query, limit=k)
for r in top-n results:
    src ← get_source_code(r.id)
    identifiers ← extract_lean_names(src.type_signature)
novel ← identifiers \ {names in results}
for name in novel:
    hits ← search_summary(name, limit=k)
for h in hits:
    get_source_code(h.id)  # extract type signatures for formalization
```

---

## 2. Existing Result Discovery

For each intermediate step in the source proof — from small utility lemmas to large theorems — search whether Mathlib already has the result. Use Pipeline 3 for each step.

### Pipeline 3: Search-and-Verify (SAV)

> `search_summary` using a detailed description of proof step → `get_source_code` to verify type signature matches

#### Algorithm

```
query ← describe(proof_step)
results ← search_summary(query, limit=k)
for r in top-n results:
    src ← get_source_code(r.id)
    if matches(src.type_signature, proof_step):
        return (r.name, match_type)
```

## 3. Write State Summary

Write one merged Phase 2 summary under `## Phase Summary` in `docs/state.md` using this format.

```
[Phase 2] Mathlib Grounding

[Phase 2.1] Mathlib API Surface
  «concept»:
  - «Mathlib name» — «one-line description»
    signature: «type signature»
  - «Mathlib name» — «one-line description»
    signature: «type signature»

[Phase 2.2] Mathlib Existing Results
  - «proof step» → exact: «Mathlib name», signature: «...»
  - «proof step» → stronger: «Mathlib name», differs: «...»
  - «proof step» → weaker: «Mathlib name», missing: «...»
  - «proof step» → not found
```

## 4. Next

Set `grounding` to `pass`, set `draft` to `in-progress`, then read `docs/exec-phases/draft/TASK.md`.
