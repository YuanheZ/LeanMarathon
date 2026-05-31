# Hard Rules - Annals-Quality LaTeX Writing

The NL content `(statement := /-- ... -/)` and `(proof := /-- ... -/)` must meet the editorial standard of the *Annals of Mathematics*:

- **Complete hypotheses.** Every assumption is stated explicitly. No "obvious" omissions.
- **Precise language.** "Let $f : U \to F$ be $C^n$" not "let $f$ be smooth."
- **Proper quantifiers.** Universal/existential quantifiers are explicit and correctly scoped.
- **Standard notation.** Follow conventions of the relevant mathematical field.
- **Proof structure.** The proof text of each node must be written with full rigour and clarity: every step is explicitly justified (no "by computation" or "straightforward"), every dependency is cited via `\cref{}`, and quantifiers and hypotheses are spelled out. The text must contain ONLY the proof itself—no internal commentary, alternative approaches, or failed attempts. The level of detail must be sufficient for an expert to verify the logical chain without filling in any unstated reasoning. These quality requirements apply to whatever content the node legitimately contains; they do not authorise inventing reasoning absent from the source.
- **Honesty About Source.** For a node with **preserved** complete proof, the Lean proof body is the ground truth: every `\cref` in the proof text must correspond to a `lemma`/`theorem` the Lean proof body uses to close the goal, and every such dependent must appear in the proof text. For placeholder-bodied nodes, the proof text's `\cref` set and the `sorry_using` list must agree. Do not silently repair flaws unless an input issue explicitly asks for that repair; unrequested repair violates the **No scope creep** boundary in `AGENTS.md`.
- **Citations.** Every dependency is cited via `\cref{}`. If a proof uses a lemma or definition, the proof text must reference it.
