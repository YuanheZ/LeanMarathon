# Final Delivery - Issue

Open an issue when Phase 4 cannot complete the target while obeying `AGENTS.md` and the hard contracts because of a concrete blocker, or when Phase 1/2 finds evidence that the target statement is wrong.

Do not open an issue merely because the proof appears large, difficult, or missing convenient upstream helper nodes. Do not request a new upstream parent/helper lemma as the blocker or required resolution. If helper facts are needed and no concrete blocker prevents it, introduce complete local refinement nodes inside the target editable region. The issue's `## Evidence` section must reflect the local-cure attempt recorded in the Phase 4 state summary — file the issue after a genuine local-cure attempt, never in place of one.

Issue delivery is terminal. Do not continue to a later phase after deciding that an issue is required.

All GitHub operations in this phase go through the MCP sandbox. The reachable surface is exactly one tool:

| Side | Tools |
|---|---|
| GitHub | `github.issue_write` |

There are no Git operations in this delivery path.

Use the runtime values from `docs/inputs.yml`:
- `target_node`
- `owner`
- `repo`

## Open the Issue

Before starting this delivery path, set `deliver-issue` to `in-progress` in `docs/state.md`.

1. **Build the issue title.** The title has a fixed template:
   ```
   Blocked blueprint node: <target_node>
   ```

2. **Build the issue body.** The body has exactly four sections, in this order. Fill the placeholders from the failed phase, using concrete evidence from the problem file, Lean diagnostics, numerical counterexample, missing visibility result, invalid runtime input, unrecoverable tool/CI failure, hard-contract violation, or other blocker.

   ```markdown
   ## Target

   `<target_node>`

   ## Problem

   <explanation of the defect or blocker>

   ## Evidence

   <specific source comparison, Lean diagnostic, numerical counterexample, missing visibility result, or other concrete blocker; do not use a size estimate as issue evidence>

   ## Required Resolution

   <smallest correction needed before this agent can continue; this must identify a concrete defect and must not be a request to add/prove a convenient upstream parent/helper lemma>
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
   Capture the returned `url` as `$URL`. The tool returns `id` and `url`; derive the issue number `$N` from the final numeric path segment of `$URL`.

## Termination

After opening the issue:
1. Set `deliver-issue` to `complete` in `docs/state.md`.
2. Replace the entire contents of `docs/delivery.yml` with exactly this YAML shape:
   ```yaml
   kind: issue
   owner: "<owner>"
   repo: "<repo>"
   number: <N>
   url: "<URL>"
   ```
   The file must be a single YAML mapping with exactly these five top-level keys: `kind`, `owner`, `repo`, `number`, and `url`. Do not append to the placeholder, merge with old contents, duplicate keys, include additional key, or leave any final key value empty/null/none.

The final assistant message must be exactly one line, with no Markdown formatting and no surrounding prose:
```text
ISSUE_OPENED + ISSUE_NUMBER_RECORDED
```
