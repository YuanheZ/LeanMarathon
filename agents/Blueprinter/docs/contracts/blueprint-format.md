# Hard Rules - Lean Blueprint Formatting

## The LeanArchitect `@[blueprint]` Format

```lean
@[blueprint "«latexEnv»:«label»"
  (statement := /-- «LaTeX statement» -/)
  (proof := /-- «LaTeX proof text with \cref{} citations» -/)
  (title := /-- «LaTeX title» -/)
  (latexEnv := "«definition or lemma or theorem»")]
«keyword» «lean_name» «params» : «type» := by
  «sorry or sorry_using [dep1, dep2, ...]»
```

A **production-ready** blueprint file is a Lean file containing a sequence of **nodes**. Each node is an `@[blueprint ...]` attribute followed by exactly one declaration whose keyword is one of:
- **Definitional** (global context, not part of the proof DAG): `def`, `abbrev`, `structure`, `inductive`, `class`, `instance`. Definitional nodes omit the `proof` field.
- **Proof** (live in the DAG): `lemma`, `theorem`.

The production-ready blueprint file must **strictly** follow the **hard formatting rules** below.

## Rule 1: Node Well-Formedness

### Source-level rules (apply to the whole file):

1. No declaration uses a **forbidden keyword** (`axiom`, `example`, `opaque`).
2. Every top-level declaration with an allowed keyword is preceded by an `@[blueprint ...]` attribute (no bare declarations). A blueprint node may also carry other Lean attributes (e.g. `@[simp]`, `@[ext]`, `@[reducible]`) by combining into the blueprint bracket:
   ```lean
   @[simp, blueprint "lem:foo" ...]
   lemma foo : ... := ...
   ```
3. No `namespace` blocks. Every declaration is top-level with a fully descriptive name. For typeclass instances that must not leak to importers, use `local instance` inside `section`, e.g.,
   ```lean
   section
   
   @[blueprint "def:foo-inhab"
     (statement := /-- ... -/)
     (title := /-- ... -/)
     (latexEnv := "definition")]
   local instance foo_inhab : Inhabited Foo := ⟨0⟩

   end
   ```
4. No `mutual ... end` blocks. Each declaration must stand alone at column 0 of the file (not nested inside any `mutual` block that groups mutually recursive declarations). **Forbidden:**
   ```lean
   mutual
     @[blueprint "def:even" ...] def even : Nat → Bool | 0 => true | n+1 => odd n
     @[blueprint "def:odd"  ...] def odd  : Nat → Bool | 0 => false | n+1 => even n
   end
   ```
5. Consecutive blueprint nodes are separated by at least one blank line. Equivalently, every node except the final node has a blank line after its declaration before the next `@[blueprint ...]` attribute begins.

### Per-node rules:
6. Each declaration must be named so its label and Lean name can be matched. Anonymous declarations (e.g. `instance : Foo := …` without a name) are forbidden.
7. The attribute's `statement` field is present and non-empty.
8. The attribute's `title` field is present and non-empty.
9. For `lemma` and `theorem`, the `proof` field is present and non-empty. Definitional nodes need no `proof` field.
10. The `statement`, `title`, and `proof` text bodies have balanced `{`/`}` (unescaped).
11. For `lemma` and `theorem`, the declaration body is exactly one of:
    - a multiline placeholder proof:
     ```lean
     := by
       sorry
     ```
    - a multiline `sorry_using` placeholder proof:
     ```lean
     := by
       sorry_using [name₁, name₂, …]
     ```

    Same-line placeholder forms such as `:= by sorry` and `:= by sorry_using [...]` are forbidden. Mixed forms (e.g. `by intro; sorry`, `by sorry; trivial`, multiple `sorry_using` in branched tactics) and term-mode `:= sorry` are forbidden.
    
12. Definitional nodes (`def`/`abbrev`/`structure`/`inductive`/`class`/`instance`) contain **no** `sorry` or `sorry_using` token anywhere in the signature or body. Definitions must be complete. (Tokens inside string literals and comments are not counted.)
13. No field name (`statement`, `title`, `proof`, `latexEnv`) appears more than once in the same `@[blueprint ...]` attribute.

## Rule 2: `latexEnv` Consistency

The `latexEnv` field must equal exactly one of `"definition"`, `"lemma"`, `"theorem"`, and must match the Lean keyword:

| Lean keyword | required `latexEnv` |
|---|---|
| `def`, `abbrev`, `structure`, `inductive`, `class`, `instance` | `"definition"` |
| `lemma` | `"lemma"` |
| `theorem` | `"theorem"` |

The following modifiers are allowed to appear before the keyword:

| **Whitelist** |
| --- |
|`noncomputable` |
|`private` |
|`local` |

## Rule 3: Label–Name Normalization

For each node:

1. The label prefix must be one of `def:`, `lem:`, `thm:`.
2. The label prefix must match the declaration kind: `def:` ↔ a definitional keyword (`def`/`abbrev`/`structure`/`inductive`/`class`/`instance`); `lem:` ↔ `lemma`; `thm:` ↔ `theorem`.
3. The Lean name must equal the label with the environment prefix stripped and every `-` replaced by `_`:
   - `def:my-thing`  →  Lean name `my_thing`
   - `lem:foo-bar-baz`  →  Lean name `foo_bar_baz`
   - `thm:main-result`  →  Lean name `main_result`
  
## Rule 4: Unique Node Name

No two nodes share the same Lean name `«lean_name»`.

## Rule 5: `sorry_using` Consistency

Definitional nodes (all six of `def`/`abbrev`/`structure`/`inductive`/`class`/`instance`) are **global context** and are excluded from the proof DAG. A placeholder proof body of a `lemma`/`theorem` is either `sorry` or `sorry_using [name₁, name₂, …]` on the indented line/block after the declaration header's standalone `by`.

For every node `N`:

1. **No comments inside `sorry_using` lists.** The substring between `[` and `]` in `sorry_using [...]` must contain no `--` or `/-` markers.
2. **Resolves to a node.** Each name in `sorry_using` is the Lean name of a `@[blueprint]`-tagged node in the file.
3. **Excludes definitional nodes.** No name in `sorry_using` resolves to a definitional node (any of the six definitional keywords).
4. **Topological order.** Each name in `sorry_using` is declared *strictly earlier* in the file than `N`.
5. **Two-way `\cref` ↔ deps parity.** Let `C` = the set of Lean names of `lemma`/`theorem` nodes whose label appears in a `\cref{...}` citation inside `N`'s `proof` field. Let `S` (the **deps** set) be:
   - **Placeholder body** (`by` followed by `sorry` / `sorry_using [...]`): `S` = the `sorry_using` list.

   Require `S = C`. Definitional `\cref{def:...}` citations are exempt either way.
6. **Cref labels resolve.** Every label appearing in a `\cref{...}` (or `\Cref{...}`) inside `N`'s `proof` **or** `statement` field is the label of some blueprint node in the file.

Both `\cref{lem:foo}` and `\Cref{lem:foo}` are recognized; comma-separated forms like `\cref{lem:a, lem:b}` are split into individual labels. Combined attribute syntax `@[simp, blueprint "lem:foo" …]` and whitespace inside `@[ blueprint … ]` are both supported.

## Rule 6: Lemma Closeness (Critical!)

For every `lemma` node `L`, some later `lemma` or `theorem` must "use" `L`. A node `N` uses `L` if `L` appears in `N`'s in-blueprint Lean-elaborated proof dependencies. For placeholder bodies, this is the `sorry_using` list.

Theorem nodes are exempt from being a "redundant" target. Definitions are global context.

A `lemma` that is never used downstream signals either a redundant node or a missing dependency in some consumer — both are author errors.