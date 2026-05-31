# Final Delivery - Pull Request

Open a PR for the refined blueprint file that closes every input issue.

All git and GitHub operations in this phase go through the hybrid MCP sandbox. The reachable surface is exactly five tools:

| Side | Tools |
|---|---|
| Git | `git.git_set_working_dir`, `git.git_add`, `git.git_commit`, `git.git_push` |
| GitHub | `github.create_pull_request` |

Use the runtime values and derived paths from `docs/inputs.yml`:
- `lean_file`
- `worktree`
- `lean_file_abs`
- `owner`
- `repo`
- `branch`

Use the issue list from `issues_file_abs` (file or `issue/` directory), the fix plan from `[Phase 1.3]`, and complete-proof downgrades from `[Phase 2.1]`.

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
   git.git_commit(message = "Refine blueprint: closes #<N1>, #<N2>, …")
   ```
   **Note:** The `files` argument is relative to the session working directory, so `lean_file` - not `lean_file_abs` - is correct here. The commit message mirrors the PR title (step 4): one line, lists every input issue number.

3. **Push:**
   ```
   git.git_push()
   ```

4. **Open the PR.** The title and body have a fixed template; fill the placeholders from `[Phase 1.3]`, `[Phase 2.1]`, and the issue list in `issues_file_abs`.

   **Title** (≤ 70 chars; truncate trailing issue numbers with `…` if it overflows):
   ```
   Refine blueprint: closes #<N1>, #<N2>, …
   ```

   **Body** — exactly three sections, in this order:

   ```markdown
   ## Summary

   - «one bullet per distinct entry in `[Phase 1.3]` — target + description + the issue(s) it closes»
   - «if any previously-complete proof was downgraded to `by sorry` / `by sorry_using [deps]` because its statement change invalidated it, list each such node here with a one-sentence rationale»

   ## Closes

   Closes #<N1>
   Closes #<N2>
   …

   ## Verification

   Auto-merge on `verify-blueprint` success.
   ```

   **Why each `Closes #<N>` line is on its own line:** GitHub's auto-close linkifier is most reliable when each reference is a standalone token on its own line. Comma-separated `Closes #1, #2` also works in current GitHub, but the line-per-issue form is bullet-proof across API versions and preserves linkification inside squash-merge commit messages.

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
COMPLETE
```
