# Demonstration Example

## Background

When formalizing the multivariate Taylor's theorem in integral form, a insufficient search use `deriv` instead of `derivWithin` for functions on closed intervals `[a,b]`. The statements compiled but were unprovable — Mathlib's Taylor API is built entirely on `Within` variants (`taylorWithinEval`, `iteratedDerivWithin`). The error can only be caught after automated proving failed and manual inspection revealed the systematic issue, which is a large waste of cost.

**Root cause:** shallow retrieval or confident in-weight hallucination.

## Why Shallow Retrieval Fails

Searching `"derivative"` at depth 5:

| Rank | Name | `Within`? |
|------|------|-----------|
| 1 | `PowerSeries.derivative` | No |
| 2 | `derivWithin_const_add_fun` | Yes (but not the definition) |
| 3 | **`deriv`** | **No** |
| 4 | `Polynomial.derivative` | No |
| 5 | `Polynomial.derivative_smul` | No |

An LLM sees `deriv` at rank 3, uses it for the formalization, and produces statements that compile but are unprovable on closed intervals. Neither DAR nor SGR was applied — no expansion step occurred.

## Pipeline 1: Dependency-Augmented Retrieval (DAR)

**Step 1.** `search_summary("Taylor theorem", limit=5)`

| Rank | Name | Signals `Within`? |
|------|------|--------------------|
| 1 | `taylor_tendsto` | No |
| 2 | `taylor_mean_remainder_bound` | No |
| 3 | `taylor_mean_remainder_lagrange` | No |
| 4 | `exists_taylor_mean_remainder_bound` | No |
| 5 | `taylor_mean_remainder_lagrange_iteratedDeriv` | No |

None of the names or descriptions mention `Within`.

**Step 2.** `get_dependencies` on top 3 results:

| Theorem | Key dependencies |
|---------|-----------------|
| `taylor_tendsto` | **`taylorWithinEval`**, `ContDiffOn`, `nhdsWithin` |
| `taylor_mean_remainder_bound` | **`iteratedDerivWithin`**, **`taylorWithinEval`**, `ContDiffOn` |
| `taylor_mean_remainder_lagrange` | **`iteratedDerivWithin`**, **`taylorWithinEval`**, `DifferentiableOn` |

Novel names discovered: **`iteratedDerivWithin`**, **`taylorWithinEval`**.

**Step 3.** `search_summary("iteratedDerivWithin", limit=5)` returns:

| Rank | Name |
|------|------|
| 1 | `iteratedDerivWithin` — Iterated Derivative Within a Set |
| 2 | `iteratedFDerivWithin` — Iterated Frechet Derivative Within a Set |
| 3 | `iteratedDerivWithin_add` |
| 4 | `iteratedDerivWithin_mul` |
| 5 | `iteratedDerivWithin_congr` |

**Step 4.** `get_source_code` on the key discoveries:

```lean
def iteratedDerivWithin (n : ℕ) (f : 𝕜 → F) (s : Set 𝕜) (x : 𝕜) : F :=
  (iteratedFDerivWithin 𝕜 n f s x : (Fin n → 𝕜) → F) fun _ : Fin n => 1

noncomputable def taylorWithinEval (f : ℝ → E) (n : ℕ) (s : Set ℝ) (x₀ x : ℝ) : E :=
  PolynomialModule.eval x (taylorWithin f n s x₀)
```

The type signatures reveal the `s : Set` parameter that distinguishes these from `iteratedDeriv` / `taylorEval`. This is the correct API to write the correct formalization.

**Result:** Full `Within` API discovered with exact type signatures.

## Pipeline 2: Source-Grounded Retrieval (SGR)

**Step 1.** Same as DAR: `search_summary("Taylor theorem", limit=5)`.

**Step 2.** `get_source_code` of `taylor_mean_remainder_lagrange` (rank 3):

```lean
theorem taylor_mean_remainder_lagrange {f : ℝ → ℝ} {x x₀ : ℝ} {n : ℕ}
    (hx : x₀ < x)
    (hf : ContDiffOn ℝ n f (Icc x₀ x))
    (hf' : DifferentiableOn ℝ (iteratedDerivWithin n f (Icc x₀ x)) (Ioo x₀ x)) :
    ∃ x' ∈ Ioo x₀ x, f x - taylorWithinEval f n (Icc x₀ x) x₀ x =
      iteratedDerivWithin (n + 1) f (Icc x₀ x) x' * (x - x₀) ^ (n + 1) / (n + 1)! := ...
```

Identifiers extracted from the type signature: `ContDiffOn`, **`iteratedDerivWithin`**, `Icc`, `DifferentiableOn`, `Ioo`, **`taylorWithinEval`**.

**Step 3.** Re-search `"taylorWithinEval"`:

| Rank | Name |
|------|------|
| 1 | `taylorWithinEval` — Evaluation of the Taylor Polynomial |
| 2 | `taylorWithin` — Taylor Polynomial within a Set |
| 3 | `taylorWithinEval_self` — Evaluation at the Base Point |
| 4 | `taylorWithinEval_succ` — Recursive Evaluation |
| 5 | `taylor_within_apply` — Evaluation of the Taylor Polynomial |

**Step 4.** `get_source_code` on the key discoveries (same output as DAR Step 4 — `iteratedDerivWithin` and `taylorWithinEval` definitions with their `s : Set` parameters).

**Result:** Same `Within` API discovered with exact type signatures.
