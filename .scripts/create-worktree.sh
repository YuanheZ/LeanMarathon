#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  echo "Usage: bash $0 --branch <name> --config <path> [--worktrees-root <path>] [--extra <path>] [--owner <owner> --repo <repo>]"
  echo ""
  echo "Required:"
  echo "  --branch <name>   Name for the new working branch"
  echo "  --config <path>   Directory whose contents are copied into the worktree"
  echo ""
  echo "Optional:"
  echo "  --worktrees-root <path>  Directory that will contain created worktrees"
  echo "  --extra  <path>   Additional directory whose contents are copied into the worktree"
  echo "  --owner  <owner>  GitHub owner/org to push to (e.g. MyGitHubName)"
  echo "  --repo   <repo>   GitHub repo name to push to (e.g. LeanMarathon)"
  echo ""
  echo "If --owner and --repo are both given, the local 'origin' remote"
  echo "must already point to https://github.com/<owner>/<repo>.git."
  echo ""
  echo "How to clean: git worktree remove --force <worktrees-root>/<name> && git branch -D <name> && git push origin --delete <name>"
  exit 1
}

BRANCH=""
CONFIG_PATH=""
EXTRA_PATH=""
WORKTREES_ROOT=""
OWNER=""
REPO=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch) BRANCH="${2:-}";       shift 2 ;;
    --config) CONFIG_PATH="${2:-}";  shift 2 ;;
    --worktrees-root) WORKTREES_ROOT="${2:-}"; shift 2 ;;
    --extra)  EXTRA_PATH="${2:-}";   shift 2 ;;
    --owner)  OWNER="${2:-}";        shift 2 ;;
    --repo)   REPO="${2:-}";         shift 2 ;;
    -h|--help) usage ;;
    *) echo "Error: unknown argument '$1'"; usage ;;
  esac
done

# Required args
[[ -z "$BRANCH" ]]      && { echo "Error: --branch is required"; usage; }
[[ -z "$CONFIG_PATH" ]] && { echo "Error: --config is required"; usage; }

# --owner and --repo must be provided together
if [[ -n "$OWNER" && -z "$REPO" ]] || [[ -z "$OWNER" && -n "$REPO" ]]; then
  echo "Error: --owner and --repo must be provided together"
  exit 1
fi

if [[ -z "$WORKTREES_ROOT" ]]; then
  WORKTREES_ROOT="${REPO_ROOT}/.worktrees"
fi
mkdir -p "$WORKTREES_ROOT"
WORKTREES_ROOT="$(cd "$WORKTREES_ROOT" && pwd)"
WORKTREE_DIR="${WORKTREES_ROOT}/${BRANCH}"

# Validate config path and resolve to absolute (so it survives `cd` later)
if [[ ! -d "$CONFIG_PATH" ]]; then
  echo "Error: config path '$CONFIG_PATH' does not exist"
  exit 1
fi
CONFIG_PATH="$(cd "$CONFIG_PATH" && pwd)"

# Validate and resolve extra path up-front too
if [[ -n "$EXTRA_PATH" ]]; then
  if [[ ! -d "$EXTRA_PATH" ]]; then
    echo "Error: extra path '$EXTRA_PATH' does not exist"
    exit 1
  fi
  EXTRA_PATH="$(cd "$EXTRA_PATH" && pwd)"
fi

# Validate that this local orchestration root belongs to the requested target
# repo. Git remotes are shared by every worktree attached to REPO_ROOT, so this
# script must never mutate origin for a different target repo.
if [[ -n "$OWNER" && -n "$REPO" ]]; then
  EXPECTED_ORIGIN="https://github.com/${OWNER}/${REPO}.git"
  ACTUAL_ORIGIN="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"
  if [[ "$ACTUAL_ORIGIN" != "$EXPECTED_ORIGIN" ]]; then
    echo "Error: this orchestration root has origin '$ACTUAL_ORIGIN', expected '$EXPECTED_ORIGIN'."
    echo "Run from the per-target orchestration root for ${OWNER}/${REPO}."
    exit 1
  fi
fi
BASE_REF="origin/main"

# Fetch latest main so the new branch is based on up-to-date remote state,
# not on whatever commit the parent repo's HEAD happens to point at.
echo "Fetching origin/main..."
git -C "$REPO_ROOT" fetch origin main

# Create worktree, explicitly basing the new branch on the fetched main.
echo "Creating worktree at ${WORKTREE_DIR} on branch '${BRANCH}' (from ${BASE_REF})..."
mkdir -p "$(dirname "$WORKTREE_DIR")"
git -C "$REPO_ROOT" worktree add "$WORKTREE_DIR" -b "$BRANCH" "$BASE_REF"

# Enable sparse checkout (non-cone): only files under LeanMarathon/
echo "Configuring sparse checkout..."
cd "$WORKTREE_DIR"
git sparse-checkout set --no-cone '/LeanMarathon/**'

# Copy all config files/folders, including dotfiles
cp -r "${CONFIG_PATH}/." "${WORKTREE_DIR}/"
echo "Copied config files from ${CONFIG_PATH}"

# Copy extra files/folders if provided
if [[ -n "$EXTRA_PATH" ]]; then
  cp -r "${EXTRA_PATH}/." "${WORKTREE_DIR}/"
  echo "Copied extra files from ${EXTRA_PATH}"
fi

# Decide push target
if [[ -n "$OWNER" && -n "$REPO" ]]; then
  PUSH_LABEL="${OWNER}/${REPO}"
  echo "Pushing branch '${BRANCH}' to origin (${PUSH_LABEL})..."
  git -C "$WORKTREE_DIR" push -u origin "$BRANCH"
else
  PUSH_LABEL="origin"
  echo "Pushing branch '${BRANCH}' to origin..."
  git -C "$WORKTREE_DIR" push -u origin "$BRANCH"
fi

echo ""
echo "Worktree ready at: ${WORKTREE_DIR}"
echo "  Branch:  ${BRANCH}"
echo "  Visible: LeanMarathon/"
echo "  Config:  copied from ${CONFIG_PATH}"
echo "  Remote:  pushed to ${PUSH_LABEL}/${BRANCH}"
