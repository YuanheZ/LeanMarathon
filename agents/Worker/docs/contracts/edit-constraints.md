# Hard Rules - Edit Constraints

This contract governs only edits to the working Lean blueprint file named by `lean_file` in `docs/inputs.yml`. It defines the permitted editable spans inside that file; every other span of that Lean file is frozen. Use the configured `apply-patch` MCP server for every permitted Lean edit.

## Target Editable Region

Let `T` be the assigned target node. The portion of the Lean blueprint file around `T` is partitioned into frozen spans and editable spans as shown below.
```lean
«frozen previous node»
«editable: exactly one initially blank line; replace this line to insert helpers»
@[blueprint "lem:T"              -- frozen: attribute head, label, kind
  (statement := /-- editable -/) -- editable: statement text body only
  (proof := /-- editable -/)     -- editable: proof text body only
  (title := /-- editable -/)     -- editable: title text body only
  (latexEnv := "lemma")]         -- frozen: field name and value
lemma T ... : ... := by          -- frozen for placeholder proofs: statement through standalone `by`
  «editable proof placeholder line/block»
«frozen for T: separator blank line owned by the next node's insertion anchor»
@[blueprint "lem:next"           -- frozen: next node begins here
  ...
```

The editable parts are only:
1. initially, the single blank-line insertion anchor immediately before `T`;
2. the text inside `T`'s `statement`, `proof`, and `title` doc comments;
3. `T`'s Lean proof placeholder/body. Only the placeholder line/block below the frozen target declaration header is editable. After you replace the placeholder with a proof attempt, every line of that proof body below the frozen header is editable, up to and including the final proof-body line.

**Boundary and indentation rules:** Do not append after the initial placeholder; replace the editable placeholder line/block instead. After the initial placeholder line/block has been replaced by proofs, an end-boundary insertion must contain at least one nonblank proof-body line, and every nonblank inserted line must be indented. Whitespace-only mutations of the separator line and top-level declarations after `T` are not part of `T`'s editable region. Any new nonblank line introduced at the start of a proof-body line must be indented.

Replacing the single blank-line insertion anchor may insert a finite block of local fresh nodes before `T`. After such fresh nodes exist, the editable local refinement area is the inserted block from the original anchor up to the current `@[blueprint ...]` attribute of `T`.

Any edit outside the target node's editable region will be rejected by the mcp server deterministically.

The patch tool enforces ranges, not semantic well-formedness of text content. Inside editable doc-comment text, do not insert comment delimiters such as `/-`, `/--`, or `-/`, or any other content that would break the surrounding blueprint syntax.

## Inserted Content

The insertion/refinement area before `T` is the only place where local fresh declarations may be inserted. The semantic rules for those nodes are defined in `docs/contracts/local-refinement.md`; their required format is defined in `docs/contracts/blueprint-format.md`.
