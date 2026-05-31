# Final Delivery - Issue

All GitHub operations in this phase go through the MCP sandbox. The reachable surface is exactly one tool:

| Side | Tools |
|---|---|
| GitHub | `github.issue_write` |

There are no Git operations in this delivery path.

Use the runtime values from `docs/inputs.yml`:
- `owner`
- `repo`

## Open the Issue

1. **Build the issue title.** The title has a fixed template:
   ```
   Blueprint target review
   ```

2. **Build the issue body.** The body has exactly four sections. Report every failed coverage or formalization check needed to make the blueprint match the problem source using the following fixed template.

   ```markdown
   ## Coverage Findings

   <missing source claims, unsupported extra theorem targets, or `None`>

   ## Formalization Findings

   <theorem statements that do not faithfully formalize their source claim, or `None`>

   ## Evidence

   <specific source-to-Lean comparisons, quoted identifiers, hypotheses, conclusions, domains, quantifiers, or counterexamples>

   ## Required Resolution

   <smallest blueprint correction needed for complete source coverage and faithful theorem statements>
   ```

3. **Open the issue:**
   ```
   github.issue_write(
     method = "create",
     owner  = "<owner from docs/inputs.yml>",
     repo   = "<repo from docs/inputs.yml>",
     title  = "<title from template above>",
     body   = "<body from template above>"
   )
   ```

## Termination

Exit with the following final assistant message which must be exactly one line with no Markdown formatting and no surrounding prose:
```text
ISSUE_OPENED
```
