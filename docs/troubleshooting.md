# Troubleshooting

## GitHub says the account is suspended

If CI fails during `actions/checkout` or `git fetch` with `Your account is
suspended`, the workflow has not reached Lean. Wait for GitHub service recovery
or resolve the account restriction before relaunching orchestration.

## No workflow runs appear

Push a no-content commit to the PR branch or close/reopen the PR to trigger
`pull_request_target`.

## Worktrees accumulate

Use `leanmarathon status` to find active branches. Merged successful agent jobs
clean their worktrees automatically; failed jobs preserve them for debugging.
