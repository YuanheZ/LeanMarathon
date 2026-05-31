# Reframing Answer-Based Problems as Proofs

When the input is a *solution* to an answer-based problem (e.g., "Find all functions...", "Determine the value of...", "What is the maximum..."), you must reframe it as a proof-based problem before decomposition.

## Why Reframing is Necessary

LeanArchitect blueprints are dependency graphs of *theorems* and *definitions*. A "solution" that says "the answer is 42" is not a theorem. The theorem is: "The answer is 42, and here is why." Lean requires a statement (the type) and a proof (the term). So we need both.

## Reframing Patterns

### Pattern 1: Existence and Uniqueness

**Problem:** "Find all functions $f : \mathbb{R} \to \mathbb{R}$ satisfying $f(x+y) = f(x)f(y)$."

**Solution says:** "The solutions are $f(x) = 0$ and $f(x) = e^{cx}$ for $c \in \mathbb{R}$."

**Reframed as proof structure:**

```
def:solution-set     — Define S = {f | f = 0 ∨ ∃ c, f = exp(c·x)}
lem:forward          — If f satisfies the equation, then f ∈ S
  lem:f-zero-case    — If f(0) = 0 then f = 0
  lem:f-exp-case     — If f(0) = 1 then f = exp(c·x) for some c
lem:backward         — Every f ∈ S satisfies the equation
thm:characterization — f satisfies the equation ↔ f ∈ S
```

**Template:**
```lean
@[blueprint "thm:main-characterization"
  (statement := /-- A function $f : \mathbb{R} \to \mathbb{R}$ satisfies
    $f(x+y) = f(x)f(y)$ for all $x, y \in \mathbb{R}$ if and only if
    $f = 0$ or $f(x) = e^{cx}$ for some $c \in \mathbb{R}$. -/)
  (latexEnv := "theorem")]
theorem main_characterization (f : ℝ → ℝ) :
    (∀ x y, f (x + y) = f x * f y) ↔ «formal condition» := by
  /-- The forward direction follows from \cref{lem:forward}.
      The backward direction is \cref{lem:backward}. -/
  sorry_using [forward, backward]
```

### Pattern 2: Optimization / Extremal Value

**Problem:** "Find the maximum value of $\sum a_i b_i$ subject to..."

**Solution says:** "The maximum is $M$, achieved when..."

**Reframed as proof structure:**

```
def:extremal-config  — Define the configuration achieving the maximum
lem:achieves-value   — The extremal configuration gives value M
lem:upper-bound      — No configuration exceeds M
thm:maximum          — The maximum is exactly M
```

**Template:**
```lean
@[blueprint "thm:maximum-value"
  (statement := /-- The maximum of $\sum_{i=1}^n a_i b_i$ subject to
    «constraints» is $M$, achieved when «conditions». -/)
  (latexEnv := "theorem")]
theorem maximum_value : «IsGreatest or sSup formulation» := by
  /-- We show the upper bound in \cref{lem:upper-bound} and
      achievability in \cref{lem:achieves-value}. -/
  sorry_using [upper_bound, achieves_value]
```

### Pattern 3: Determine a Specific Value

**Problem:** "Compute $\int_0^1 \frac{\ln(1+x)}{x} dx$."

**Solution says:** "The integral equals $\pi^2/12$."

**Reframed:**

```
lem:series-expansion — Express integrand as power series
lem:term-by-term     — Justify term-by-term integration
lem:series-sum       — Evaluate the resulting series
thm:integral-value   — The integral equals π²/12
```

### Pattern 4: Combinatorial / Counting

**Problem:** "How many ways can you tile a 2×n board with dominoes?"

**Solution says:** "The answer is the $n$-th Fibonacci number."

**Reframed:**

```
def:tiling-count     — Define T(n) as the number of tilings
lem:base-cases       — T(1) = 1, T(2) = 2
lem:recurrence       — T(n) = T(n-1) + T(n-2) for n ≥ 3
thm:equals-fibonacci — T(n) = Fib(n+1)
```

### Pattern 5: Competition "Prove that..."

Many competition problems are already proof-based ("Prove that for all primes p..."). These require minimal reframing — just ensure the statement is a proper universal theorem:

```lean
@[blueprint "thm:competition-result"
  (statement := /-- For every prime $p > 3$, ... -/)
  (latexEnv := "theorem")]
theorem competition_result (p : ℕ) (hp : Nat.Prime p) (hp3 : 3 < p) : «conclusion» := by
  ...
```

### Pattern 6: Construction Problems

**Problem:** "Construct a set $S \subset \mathbb{R}$ that is uncountable but has measure zero."

**Reframed:**

```
def:cantor-set       — Define the Cantor set
lem:uncountable       — The Cantor set is uncountable
lem:measure-zero      — The Cantor set has Lebesgue measure zero
thm:construction      — There exists an uncountable set of measure zero
```

## General Reframing Principles

1. **The answer becomes part of the theorem statement.** Don't hide it — state it explicitly.

2. **Existence and characterization are separate.** If the problem asks "find all X", you need both "every solution is of form Y" (forward) and "every Y is a solution" (backward).

3. **Optimality requires two directions.** "The maximum is M" means "M is achieved" AND "nothing exceeds M."

4. **Constructions need verification.** "Construct X with property P" becomes "Define X" + "Prove X has property P."

5. **The main theorem uses iff (↔) or equality (=) whenever possible.** This is stronger and more useful than one-directional implications.
