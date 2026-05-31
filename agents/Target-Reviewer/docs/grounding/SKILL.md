# Mathlib Grounding — Just-In-Time (JIT) Retrieval

## Hard constraint: restrict `lean-explore` search scope

Every call to a `lean-explore` search tool **must** pass the `packages` argument restricting the search to the canonical core + Mathlib set:

```json
"packages": ["Batteries", "Init", "Lean", "Mathlib", "Std"]
```

## Choose the retrieval tier

Use the optimal retrieval tier that answers the current question.

- **Flexible exploration** is for ordinary retrieval. Use any combination of `search_summary`, `search`, `get_source_code`, `get_docstring`, `get_module`, `get_dependencies`, or `get_description` in whatever order provides what you need.
- **Pipeline 1 (DAR)** and **Pipeline 2 (SGR)** are structured API-discovery workflows. Use them when you are about to express a nontrivial concept, need confidence that you have the correct surrounding declarations, or flexible exploration leaves the relevant API unclear. DAR discovers dependencies the summaries hide; SGR discovers identifiers the dependency graph misses. Worked example: `docs/grounding/example/api-example.md`.

## Pipeline 1: Dependency-Augmented Retrieval (DAR)

> `search_summary` → `get_dependencies` → re-`search_summary` on novel names

```
results ← search_summary(query, limit=k)
for r in top-n results:
    deps ← get_dependencies(r.id)
novel ← deps \ {names in results}   # filter boilerplate (HAdd, Eq, etc.)
for name in novel:
    hits ← search_summary(name, limit=k)
for h in hits:
    get_source_code(h.id)            # extract type signatures for formalization
```

## Pipeline 2: Source-Grounded Retrieval (SGR)

> `search_summary` → `get_source_code` → extract identifiers from the type signature → re-`search_summary`

```
results ← search_summary(query, limit=k)
for r in top-n results:
    src ← get_source_code(r.id)
    identifiers ← extract_lean_names(src.type_signature)
novel ← identifiers \ {names in results}
for name in novel:
    hits ← search_summary(name, limit=k)
for h in hits:
    get_source_code(h.id)
```
