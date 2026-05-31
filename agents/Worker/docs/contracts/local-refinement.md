# Hard Rules - Local DAG Refinement

Let the full blueprint proof graph be $G=(V,E)$, where each vertex is a blueprint `lemma`/`theorem` node and an edge $\texttt{A}\to\texttt{B}$ means that $\texttt{B}$ cites $\texttt{A}$. Definitional nodes are global context and are not vertices of this proof graph. 

Suppose $\texttt{T}\in V$ is the target node. A local refinement of `T` introduces a finite local proof DAG

$$
R_\texttt{T}=(H_\texttt{T}\cup\{\texttt{T}\}, E_\texttt{T}),
$$

where $H_\texttt{T}$ is the finite set of local fresh nodes introduced for `T`.

## Valid Local Refinement

A local refinement is valid only if:
- `T`'s formal Lean statement is unchanged;
- every fresh node in $H_\texttt{T}$ is a well-formed blueprint node satisfying `docs/contracts/blueprint-format.md`;
- $R_\texttt{T}$ is a DAG;
- `T` is the unique terminal node of $R_\texttt{T}$;
- every fresh node $\texttt{h}\in H_\texttt{T}$ appears before `T` in the Lean file;
- the external global DAG outside $H_\texttt{T}\cup\{\texttt{T}\}$ is unchanged;
- every edge into a fresh node or into `T` comes only from $H_\texttt{T}$ or from an existing blueprint proof node declared earlier in the Lean file.

## Complete Refinement

A valid local refinement must be complete.

A direct proof of `T` is the degenerate complete case with $H_\texttt{T}=\emptyset$.

A complete refinement has no `sorry` or `sorry_using` in `T` or in any fresh local proof node.

## Citing Existing Nodes

Besides other nodes in $H_\texttt{T}$, a fresh local node or `T` may cite any existing blueprint `lemma`/`theorem` node declared earlier in the Lean file. File order is the only constraint, and Lean enforces it: a name can be cited only after it is declared. The originally generated parent list of `T` is not ground truth — cite whatever earlier nodes the proof actually needs.

If the proof needs a helper result that does not exist, or that exists only later in the file, **add it as a fresh local node** in $H_\texttt{T}$ before `T` and complete it. A missing or out-of-order upstream helper is never a blocker and is never a reason to file an issue.

Existing definitional nodes are global context. They may be referenced only when already in Lean scope, and they must not be edited.

## Final Local State

At successful termination:
- the target outcome is complete directly or complete with fresh local nodes;
- every fresh local helper declaration satisfies the blueprint format contract;
- every `lemma`/`theorem` dependency used by a complete local proof is reflected by a matching `\cref{...}` citation in the corresponding proof text, and every non-definitional `\cref{...}` citation in that proof text is actually used by the Lean proof;
- `T`'s text fields accurately describe the final formal result and proof.
