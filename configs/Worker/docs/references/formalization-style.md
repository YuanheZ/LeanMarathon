# Formalization Style

- **No Lean comments.** Inside formal declaration bodies and proof bodies, write code only: no `--`, `/- ... -/`, `/-- ... -/`, or blank/comment padding before placeholders. The required blueprint prose fields (`statement`, `proof`, `title`) are the only place for explanations. Placeholder proof bodies must start immediately with `sorry` or `sorry_using [...]`.
- **No unused parameters** For unused parameters in the type signature, **DO NOT** add `_` to make it implicit, e.g., `hn` -> `_hn`. You must directly remove it.
