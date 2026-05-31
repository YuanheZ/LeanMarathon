# Decomposition Rubric

The goal is not merely to explain the proof to a human. The goal is to choose a declaration graph that is easy to formalize, easy to debug, and cheap to repair when a local statement is wrong.

This rubric incorporates Lean-grounded refactoring cues: choose boundaries where a future Lean proof would have a clean intermediate goal, and avoid boundaries that only expose temporary syntax or tangled local context.

## Survey the proof before splitting

Before naming any declarations, do one structural pass over the source proof.

Mark candidate breakpoints wherever a future Lean proof would likely have a clean, reusable intermediate goal. The count is not fixed — it follows from the proof's structure.

Good breakpoints often occur:

- after a long preliminary estimate, normalization, or algebraic setup
- after an auxiliary object is introduced and its basic properties are settled
- after a major case split closes
- after the argument changes mathematical domain
- immediately before or after a major imported theorem is applied
- after a recurring notation conversion has been completed once and for all

Bad breakpoints often occur:

- in the middle of a `calc` chain or dense local simplification
- in the middle of one branch of a case split
- where the extracted helper would need ten or more ad hoc parameters
- where the statement depends on a later local choice
- where the helper would merely restate a local `let` binding with no stable mathematical meaning
- where the context is so tangled that the extracted statement has no natural standalone interpretation

If no clean breakpoint appears, keep the argument together.

## Use the three-layer decomposition

### 1. Concept nodes

Use concept nodes for the mathematical ideas that a human would mention in a seminar proof:

- define the invariant, auxiliary function, extremal object, or inductive quantity
- prove the structural lemma that drives the argument
- state the main theorem

These nodes should explain the proof at the idea level.

### 2. Interface nodes

Use interface nodes for statements that are mathematically routine but formalization-sensitive:

- domain and codomain bookkeeping
- “within” versus “global” variants of continuity or differentiability
- set-membership and boundary conditions
- coercions, finiteness hypotheses, or algebraic structure assumptions
- exact formulations of standard theorems from the library
- conversions between two recurring notational forms

These nodes often decide whether the entire blueprint formalizes smoothly. Keep them small and local.

### 3. Cleanup nodes

Use cleanup nodes for short rewrites, canonical normal forms, algebraic simplifications, or small summation and indexing conversions.

Do not create cleanup nodes merely to atomize the proof. Create them when a rewrite is likely to be reused, likely to fail in Lean, or likely to obscure the main proof if left inline.

## Lean-grounded extraction patterns

### 1. Large preliminary block

If the main argument begins with a long preliminary estimate, normalization, or setup computation, extract it.

**Reason**: the theorem should become visible immediately, and a preliminary block is often the first part that fails during formalization.

### 2. Domain separation

If one proof mixes distinct mathematical domains, separate those layers.

Typical examples:

- algebra followed by topology
- combinatorics followed by analysis
- local differential identities followed by global compactness or integration
- arithmetic bounds followed by permutation or indexing arguments

**Reason**: each helper should live at one mathematical abstraction level whenever possible.

### 3. Repetitive structure and symmetry

Extract when you see:

- near-duplicate proofs for left and right sides
- forward and backward directions with the same skeleton
- repeated symmetric arguments
- the same case-split pattern applied to different objects
- a single long case split that proves a standalone fact, even if it appears only once

The key question is not “Is this text repeated verbatim?” but “Is the proof pattern repeated or large enough that it deserves a named fact?”

A single 30-line case analysis that proves a reusable identity is usually better as its own node than as inline proof text.

### 4. Witness extraction

If the argument repeatedly extracts witnesses from existential statements or repeatedly packages choices with side conditions, isolate that work in its own node.

Use a definition node when the witness itself is the reusable object.

Use a lemma node when the reusable content is the existence statement or the properties of the witness.

### 5. Property bundling

If several properties are naturally proved together and always used together, bundle them into one node.

Bundle only when the properties share hypotheses and have a common purpose.

Do not bundle if the properties are likely to be used independently or if different hypotheses govern them.

#### Example. Package reusable conclusion bundles before reuse

If a lemma proves the existence of data carrying several properties and later nodes need those properties as assumptions, introduce a definition node for that bundled interface before you reuse it.

The right pattern is:

- one definition node packaging the relevant properties as a predicate, structure, or named bundle;
- one lemma or theorem asserting existence of data satisfying that package; and
- later nodes depending on the package definition, not on the phrase “the conclusion of \cref{...}”.

**Reason**: Lean declarations depend on explicit statement interfaces. A prior proof is not itself a reusable ambient container.

#### 6. Keep one canonical formulation per node

If the source offers two equivalent formulations of the same idea, choose one as the node statement and move the alternative to a separate equivalence lemma or proposition.

This is especially important for definitional nodes. A definition with an appended “equivalently” clause forces the downstream formalizer to guess which formulation should become the actual Lean declaration.

### 7. Notation conversion and interface normalization

If the same conversion between two formulations appears multiple times, create a small interface or cleanup node.

Typical examples:

- set-builder notation versus structured predicates
- two equivalent indexings of the same sum
- global versus within-set formulations
- a local coercion or subtype view that repeatedly obscures the mathematics

These nodes are often cheap mathematically but disproportionately valuable in Lean.

### 8. “All equal, pick one” separation

When the argument shows that all admissible representatives coincide and then chooses one representative, separate the two roles.

Extract the mathematical equality or uniqueness statement.

Keep the arbitrary proof-engineering choice of representative in a short local step or in a definition node, not in the same lemma as the real mathematical content.

## Choose between definition and lemma

Use a definition node when the extracted material primarily names a reusable object, bundle, predicate, normalization, or standing construction.

Use a lemma node when the extracted material proves a fact about already named objects.

If a prospective helper would depend on an unnamed local `let`, temporary notation, or a fragile expression whose exact syntactic form may change, do not create a brittle lemma around that syntax.

Instead, do one of the following:

- promote the underlying object to its own definition node
- isolate the interface fact in a small bridge lemma stated without temporary syntax
- keep the step inline if it has no stable standalone meaning

## Split a node when any of the following occurs

Split when the proof changes mathematical mode, such as algebra to topology, combinatorics to number theory, or local computation to global compactness.

Split when the argument introduces an auxiliary object that is reused later.

Split when necessity and sufficiency use different ideas.

Split when existence and uniqueness use different ideas.

Split when the proof branches into genuinely different cases.

Split when a single node would otherwise mix a conceptual step with a library-interface step.

Split when one difficult placeholder would block many downstream nodes.

Split when a claim is likely true only after strengthening or weakening hypotheses.

Split when the same proof pattern appears on several inputs and the abstract common fact can be stated cleanly.

Split when several properties are always produced and consumed together.

## Do not split automatically

Do not split a one-line deduction just to increase node count.

Do not split a node if the resulting subnode would have no independent mathematical meaning, no repair value, and no likely formalization value.

Do not create decorative lemmas whose only purpose is to restate a previous sentence.

Do not extract a fragment that sits in the middle of a calculation unless the extracted statement has clean standalone meaning.

Do not extract a helper whose signature is dominated by temporary notation, repeated local parameters, or hidden context that should have been promoted to definitions.

## Use these patterns by problem type

### Classification or “find all” problems

Create:

- one node restating the target as an exact classification theorem
- one or more necessity lemmas
- one or more sufficiency lemmas
- a short final theorem combining them

If the candidate set is explicit, separate “every solution lies in S” from “every element of S is a solution.”

If one direction mainly performs witness construction while the other performs verification, keep those directions separate.

### Extremal or inequality problems

Create:

- one bound lemma
- one equality-case lemma if equality is nontrivial
- one theorem that packages the final statement

If normalization or homogeneity is essential, isolate it as a definition or preliminary lemma.

If the proof contains a long symmetric argument on two sides or several repeated local estimates, extract the shared pattern.

### Constructive existence problems

Create:

- one definition node for the constructed object
- one lemma verifying the object is well defined, if needed
- one lemma proving the desired property
- one uniqueness lemma only if uniqueness matters

If the construction repeatedly extracts witnesses or repackages auxiliary choices, isolate that mechanism.

### Induction or recursion problems

Create:

- one definition node for the recursive quantity or invariant if reused
- one lemma for the induction step if the step itself has internal structure
- separate base-case lemmas only if they are delicate or reused

If the induction proof already has a clean linear shape and the induction structure is the whole mathematical content, do not over-refactor it.

### Research-level analysis or geometry problems

Usually separate:

- setup and auxiliary objects
- regularity lemmas
- derivative or local-identity lemmas
- integration, compactness, or global-passage lemmas
- final assembly theorem

Expect interface nodes to matter. Library alignment is often the difference between a usable and unusable blueprint.

If the proof contains repeated conversions between local and global formulations, isolate those conversions early.

## Keep the final theorem light

A good final theorem proof should mostly cite earlier nodes and perform only minimal assembly.

If the main theorem proof is still long, revisit the graph. Either the supporting lemmas are too weak, or the theorem is hiding multiple ideas.

## Lean-side self-check before finalizing

Before returning the blueprint, ask:

- Could each node plausibly become a standalone Lean declaration using only earlier nodes?
- Does any node still require too many explicit parameters because a reusable object was never promoted to a definition node?
- Does any repeated case analysis or conversion remain inline in more than one place?
- Does any node hide both the mathematical content and the proof-engineering choice of representative?
- Does any definition node still carry two equivalent formulations instead of one canonical interface?
- Does any later statement depend on “the conclusion of \cref{...}” instead of on explicit hypotheses or a packaged definition node?
- Is the final theorem mostly assembly rather than fresh derivation?

If the answer to any question is no, adjust the graph before polishing the prose.

## Anti-patterns

Avoid monolithic proofs with many inline claims.

Avoid nodes that simultaneously define an object, prove its regularity, and use it to conclude the main theorem.

Avoid proofs whose real dependency graph cannot be read from the citations.

Avoid fragile global statements when a small local bridge lemma would suffice.

Avoid letting one unresolved node contaminate ten downstream statements when it could have been isolated earlier.

Avoid generic placeholder names such as `helper1`, `step2`, `part_one`, or `tmp`.

Avoid extracting helpers whose only real content is a local `let` binding or temporary syntactic arrangement.

Avoid a definition node that states one formulation and then appends “equivalently” with a second formulation.

Avoid theorem-shaped assumption bundles such as “assume that these parameters satisfy the conclusion of \cref{...}”. Package the reusable interface in a definition node instead.

Avoid over-generalized nodes with bloated parameter lists and weak mathematical identity.
