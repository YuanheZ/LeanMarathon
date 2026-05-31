# Final Delivery - Pull Request

Open a PR for the completed blueprint node. A PR must deliver a complete proof of the assigned target. The assigned target and every fresh local refinement node introduced for it must contain no `sorry` and no `sorry_using`.

All git and GitHub operations in this phase go through the hybrid MCP sandbox. The reachable surface is exactly five tools:

| Side | Tools |
|---|---|
| Git | `git.git_set_working_dir`, `git.git_add`, `git.git_commit`, `git.git_push` |
| GitHub | `github.create_pull_request` |

Use the runtime values and derived paths from `docs/inputs.yml`:
- `target_node`
- `lean_file`
- `worktree`
- `lean_file_abs`
- `owner`
- `repo`
- `branch`

## Open the PR

Before starting this delivery path, set `deliver-pr` to `in-progress` in `docs/state.md`.

1. **Bind the git session to the worktree.** First call must pass the canonical absolute path exactly:
   ```
   git.git_set_working_dir(
     path = "<worktree from docs/inputs.yml>",
     includeMetadata = true
   )
   ```
   Capture from the response: `branches.current`, `branches.upstream`, `branches.ahead`, `branches.behind`, `status.is_clean`.

2. **Stage and commit the blueprint file:**
   ```
   git.git_add(files = ["<lean_file from docs/inputs.yml>"])
   git.git_commit(message = "Complete blueprint node: <target_node>")
   ```
   **Note:** The `files` argument is relative to the session working directory, so `lean_file` — not `lean_file_abs` — is correct here. The commit message mirrors the PR title (step 4).

3. **Push:**
   ```
   git.git_push()
   ```

4. **Open the PR.** The title and body have a fixed template; fill the placeholders from the final work: whether the target was completed directly or with fresh local nodes, any fresh local nodes introduced, and any edited `statement`, `proof`, or `title` text fields.

   **Title** (≤ 70 chars; use `target_node`):
   ```
   Complete blueprint node: <target_node>
   ```

   **Body** — exactly two sections, in this order:

   ```markdown
   ## Summary

   - «complete proof for `target_node`, directly or using fresh local nodes»
   - «fresh local nodes introduced, if any»
   - «editable text fields repaired, if any»

   ## Verification

   Auto-merge on `verify-blueprint` success.
   ```

   Call:
   ```
   github.create_pull_request(
     owner = "<owner from docs/inputs.yml>",
     repo  = "<repo from docs/inputs.yml>",
     head  = "<branch from docs/inputs.yml>",
     base  = "main",
     title = "<title from template above>",
     body  = "<body from template above>"
   )
   ```
   Capture the returned `number` as `$N`.

## Termination

After opening the PR:
1. Set `deliver-pr` to `complete` in `docs/state.md`.
2. Replace the entire contents of `docs/delivery.yml` with exactly this YAML shape:
   ```yaml
   kind: pr
   owner: "<owner>"
   repo: "<repo>"
   number: <N>
   url: "https://github.com/<owner>/<repo>/pull/<N>"
   ```
   The file must be a single YAML mapping with exactly these five top-level keys: `kind`, `owner`, `repo`, `number`, and `url`. Do not append to the placeholder, merge with old contents, duplicate keys, include additional key, or leave any final key value empty/null/none.

The final assistant message must be exactly one line, with no Markdown formatting and no surrounding prose:
```text
PR_OPENED + PR_NUMBER_RECORDED
```
