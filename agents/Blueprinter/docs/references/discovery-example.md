# Demonstration Example

## Retrieval Examples from Small to Large

### Small: `Finset.sum_le_sum`

**Goal:** `⊢ ∑ i ∈ s, f i ≤ ∑ i ∈ s, g i` given `∀ i ∈ s, f i ≤ g i`

**Step 1.** `search_summary("finite sum preserves less than or equal", limit=5)`

| Rank | Name |
|------|------|
| 1 | `Summable.sum_le_tsum_set` — partial vs total sum |
| ... | |
| 5 | `Finset.sum_le_sum` — Monotonicity of Finite Sums |

**Step 2.** `get_source_code` — rank 5 matches; ranks 1–4 are infinite-sum variants.

### Small: `intervalIntegral.integral_nonneg` (generality mismatch)

**Goal:** `⊢ 0 ≤ ∫ x in a..b, f x` given `∀ x, 0 ≤ f x`

**Step 1.** `search_summary("integral of a nonneg function is nonneg", limit=5)`

| Rank | Name |
|------|------|
| 3 | `MeasureTheory.integral_nonneg` — for measure-theoretic integrals (`∫ x, f x ∂μ`) |
| 5 | `intervalIntegral.integral_nonneg` — for interval integrals (`∫ x in a..b, f x`) |

**Step 2.** `get_source_code` — rank 3 is wrong integral type; rank 5 is the correct match.

### Medium: Cayley-Hamilton (`Matrix.aeval_self_charpoly`)

**Goal:** prove that a matrix satisfies its characteristic polynomial

**Step 1.** `search_summary("Cayley-Hamilton theorem matrix satisfies its characteristic polynomial", limit=5)`

| Rank | Name |
|------|------|
| 1 | `LinearMap.minpoly_dvd_charpoly` — divisibility version |
| 2 | `Matrix.charpoly` — definition, not the theorem |
| 3 | `Matrix.aeval_self_charpoly` — **the theorem** |
| 5 | `LinearMap.aeval_self_charpoly` — endomorphism version |

**Step 2.** `get_source_code(Matrix.aeval_self_charpoly)`:

```lean
theorem aeval_self_charpoly (M : Matrix n n R) : aeval M M.charpoly = 0
```

Rank 3 is the matrix version; rank 5 is the equivalent for linear maps. Verification selects the right formulation.

### Medium: Sylow's First Theorem

**Step 1.** `search_summary("Sylow theorem existence of p-subgroup", limit=5)`

| Rank | Name |
|------|------|
| 1 | `Sylow.exists_subgroup_card_pow_prime` — generalization |
| 2 | `IsPGroup.exists_le_sylow` — extension of a p-subgroup |
| 3 | `Sylow` — the type definition |
| 4 | `Sylow.inhabited` — existence via `Inhabited` |
| 5 | `Sylow.nonempty` — existence via `Nonempty` |

**Step 2.** Multiple formulations exist — `get_source_code` on ranks 1, 4, 5 determines which matches your goal's type.

### Medium: Chinese Remainder Theorem

**Step 1.** `search_summary("Chinese remainder theorem ring isomorphism", limit=5)`

| Rank | Name |
|------|------|
| 1 | `Ideal.quotientMulEquivQuotientProd` — for coprime ideals (product) |
| 2 | `Ideal.quotientInfEquivQuotientProd` — for coprime ideals (intersection) |
| 4 | `IsDedekindDomain.quotientEquivPiFactors` — Dedekind domain version |
| 5 | `ZMod.equivPi` — ℤ/nℤ version |

**Step 2.** Four different formulations at different levels of generality. `get_source_code` on each determines which matches your algebraic context.

### Large: Lebesgue Dominated Convergence

**Step 1.** `search_summary("Lebesgue dominated convergence theorem", limit=5)`

| Rank | Name |
|------|------|
| 1 | `MeasureTheory.tendsto_integral_of_dominated_convergence` — **the theorem** |
| 3 | `MeasureTheory.hasSum_integral_of_dominated_convergence` — series version |
| 4 | `MeasureTheory.tendsto_integral_filter_of_dominated_convergence` — filter version |

**Step 2.** `get_source_code(MeasureTheory.tendsto_integral_of_dominated_convergence)`:

```lean
theorem tendsto_integral_of_dominated_convergence {F : ℕ → α → G} {f : α → G} (bound : α → ℝ)
    (F_measurable : ∀ n, AEStronglyMeasurable (F n) μ)
    (bound_integrable : Integrable bound μ)
    (h_bound : ∀ n, ∀ᵐ a ∂μ, ‖F n a‖ ≤ bound a)
    (h_lim : ∀ᵐ a ∂μ, Tendsto (fun n => F n a) atTop (𝓝 (f a))) :
    Tendsto (fun n => ∫ a, F n a ∂μ) atTop (𝓝 <| ∫ a, f a ∂μ)
```

The type signature reveals the exact hypotheses needed. Ranks 3–5 are variants for series and filters.

### Large: Stone-Weierstrass Approximation

**Step 1.** `search_summary("Stone-Weierstrass theorem polynomial approximation", limit=5)`

| Rank | Name |
|------|------|
| 2 | `exists_polynomial_near_of_continuousOn` — concrete polynomial version |
| 5 | `ContinuousMap.subalgebra_topologicalClosure_eq_top_of_separatesPoints` — **general version** |

**Step 2.** `get_source_code` on rank 5:

```lean
theorem subalgebra_topologicalClosure_eq_top_of_separatesPoints
    (A : Subalgebra ℝ C(X, ℝ)) (w : A.SeparatesPoints) : A.topologicalClosure = ⊤
```

Rank 2 is the concrete corollary (polynomials on `[a,b]`); rank 5 is the general version (subalgebras of `C(X, ℝ)`). Verification determines which level of generality fits.

### Large: Hilbert Basis Theorem

**Step 1.** `search_summary("Hilbert basis theorem Noetherian polynomial ring", limit=5)`

| Rank | Name |
|------|------|
| 1 | `Polynomial.isNoetherianRing` — univariate |
| 2 | `MvPolynomial.isNoetherianRing` — multivariate |

**Step 2.** `get_source_code(Polynomial.isNoetherianRing)`:

```lean
protected theorem Polynomial.isNoetherianRing [inst : IsNoetherianRing R] :
    IsNoetherianRing R[X]
```

Clean match. Rank 2 is the multivariate generalization.

## Why verification matters

| Scale | Example | Correct rank | Why verification matters |
|-------|---------|-------------|--------------------------|
| Small | `Finset.sum_le_sum` | 5 | Ranks 1–4 were infinite-sum variants |
| Small | `intervalIntegral.integral_nonneg` | 5 | Rank 3 was wrong integral type |
| Medium | Cayley-Hamilton | 3 | Rank 1 was divisibility, rank 5 was LinearMap version |
| Medium | Chinese Remainder | 1–5 | Four formulations at different generality levels |
| Large | Dominated Convergence | 1 | Ranks 3–5 were filter/series variants |
| Large | Stone-Weierstrass | 2 or 5 | Concrete polynomial vs general subalgebra version |
| Large | Hilbert Basis | 1 | Rank 2 was multivariate generalization |

## Patterns 

- Small lemmas often require scanning past generality mismatches (infinite vs finite, measure vs interval).
- Medium and large theorems often have **multiple formulations** — the verification step selects the one matching the proof context.
