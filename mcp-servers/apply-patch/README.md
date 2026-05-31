# apply-patch MCP Server

This directory contains a stdio MCP server that exposes an `apply_patch` tool
without invoking Bash or any subprocess for patch application.

The implementation in `apply_patch_mcp.py` is a Python port of the relevant
parts of OpenAI Codex's Rust `codex-rs/apply-patch` crate. The current sync
target is:

```text
openai/codex rust-v0.124.0
```

## Codex Config

The server is registered in Codex's project config:

```text
.codex/config.toml
```

The MCP server name is:

```text
apply-patch
```

It exposes two tools:

```text
apply_patch
apply_patch_dry_run
```

The target file is a structured MCP argument:

```text
path = "relative/or/absolute/file"
```

Paths are always resolved against the configured `APPLY_PATCH_WORKSPACE`.
There is no `cwd` tool argument.

For configured-target application scenarios, set the single primary target in
`.codex/config.toml`:

```text
APPLY_PATCH_TARGET_FILE = "relative/or/absolute/file"
```

`APPLY_PATCH_TARGET_FILE` may be absolute or relative. Relative paths are
resolved against `APPLY_PATCH_WORKSPACE`. The resolved target must stay inside
the workspace, must exist, and must be a regular non-symlink file. For
LeanArchitect worker agents, this is the only configured Lean file.

To allow additional non-Lean files, set `APPLY_PATCH_OTHER_FILES` to a JSON
string array, comma-separated list, or newline-separated list:

```text
APPLY_PATCH_OTHER_FILES = '["docs/state.md","docs/delivery.yml"]'
```

Every listed file is resolved against `APPLY_PATCH_WORKSPACE`; it must stay
inside the workspace, must exist, must be a regular non-symlink file, and must
not have a `.lean` suffix, case-insensitively. Lean files belong only in
`APPLY_PATCH_TARGET_FILE`. Empty file entries are rejected.

When only `APPLY_PATCH_TARGET_FILE` is set, the MCP schema requires only
`patch`. The configured target has priority, and raw MCP requests that try to
smuggle a different `path` are rejected defensively.

When `APPLY_PATCH_OTHER_FILES` is nonempty, the MCP schema requires both
`path` and `patch`. The requested `path` may be absolute or relative, but it
must resolve to `APPLY_PATCH_TARGET_FILE` or one of the configured non-Lean
files.

The patch body contains only update chunks:

```text
*** Begin Patch
@@
-old line
+new line
*** End Patch
```

The server intentionally does not accept file-operation markers inside the
patch body:

```text
*** Add File:
*** Delete File:
*** Update File:
*** Move to:
```

This keeps the tool scoped to editing one existing regular file per call.

## Node-Local Editing Restrictions

For LeanArchitect worker agents, the server can restrict edits to one target
blueprint node by setting:

```text
APPLY_PATCH_NODE = "lean_name_of_target_node"
```

`APPLY_PATCH_NODE` requires `APPLY_PATCH_TARGET_FILE`, and that target must be
a `.lean` file. When `APPLY_PATCH_NODE` is set, only that single Lean target
is parsed as a LeanArchitect blueprint file. The value must be the Lean
declaration name of a blueprint node. Patches to configured non-Lean files do
not receive node-local range checks. Patches to the Lean target are rejected
unless every actual changed span lies inside one of the target node's editable
areas:

1. the single blank-line gap immediately before the target node's
   `@[blueprint ...]` attribute;
2. the target node's `statement := /-- ... -/` text body;
3. the target node's `proof := /-- ... -/` text body;
4. the target node's `title := /-- ... -/` text body;
5. the target node's Lean proof body. For placeholder proofs written as `by`
   followed by `sorry` or `sorry_using [...]` after comments are masked, only
   the placeholder line/block after the standalone `by` is editable; the
   declaration line containing `:= by` is frozen. For non-placeholder proofs,
   the editable proof-body range begins after `:=` and ends at the end of the
   final proof-body line. The separator blank line before the next node is not
   part of this proof-body range.

Pure insertions exactly at the proof-body end boundary are rejected for
placeholder proofs. To extend a placeholder proof, replace the editable
placeholder line/block with the new indented proof body. For complete
non-placeholder proofs whose first code line is a standalone `by`, indented
end-boundary continuation lines are allowed; unindented insertions there are
still rejected. This keeps top-level declarations and separator ownership out
of the previous node's proof body.

Any new nonblank line introduced at the start of a proof-body line must be
indented. This prevents top-level declarations from being inserted before or in
place of a placeholder line while still allowing same-line proof-token rewrites.

The blank-line gap is an insertion anchor. This gap's start offset is recorded
at server startup as the helper-area anchor. Replacing that one blank line may
insert any finite block of text before the target. After inserted text exists,
later patches may edit or remove any text from that anchor up to the current
target attribute. The server also records hashes of the file prefix before the
helper-area anchor and of the frozen projection of the target file. If frozen
content changes after startup, the server rejects node-local edits and the MCP
server must be restarted.

The separator blank line before a node belongs to that node's helper insertion
anchor, not to the previous node's proof body.

The server does not enforce helper naming, helper declaration kind, blueprint
well-formedness, doc-comment content validity, or proof-DAG policy. Those
checks belong to separate verifier or CI layers. This server only enforces
editable areas.

If `APPLY_PATCH_NODE` is unset, the configured Lean file remains editable but
without node-local range checks.

## Updating After Codex Upgrades

When Codex is upgraded, check whether upstream `apply_patch` changed and port
only the relevant behavior.

1. Check the installed Codex version:

```bash
npm list -g @openai/codex --depth=0
```

2. Fetch the matching upstream tag:

```bash
git clone --depth 1 --branch rust-vX.Y.Z https://github.com/openai/codex.git /tmp/openai-codex-rust-vX.Y.Z
```

3. Compare these upstream files:

```text
codex-rs/apply-patch/src/parser.rs
codex-rs/apply-patch/src/seek_sequence.rs
codex-rs/apply-patch/src/lib.rs
```

The main functions to track are:

```text
parse_patch
parse_update_file_chunk
seek_sequence
derive_new_contents_from_chunks
compute_replacements
apply_replacements
```

You usually do not need to port:

```text
codex-rs/apply-patch/src/invocation.rs
codex-rs/arg0/src/lib.rs
```

Those files handle shell heredoc detection and `arg0` dispatch. This MCP
server receives structured MCP tool calls directly, so it does not need that
shell compatibility layer.

## Verification

Run these checks after any update:

```bash
.venv/bin/python3 mcp-servers/apply-patch/apply_patch_mcp.py --self-test
.venv/bin/python3 -m py_compile mcp-servers/apply-patch/apply_patch_mcp.py
.venv/bin/python3 -c 'import tomllib; tomllib.load(open(".codex/config.toml", "rb")); print("toml ok")'
```

## Security Notes

The server is intentionally narrow:

- no Bash
- no subprocess execution
- no network access in server code
- writes constrained to `APPLY_PATCH_WORKSPACE`
- optional configured-file lock via `APPLY_PATCH_TARGET_FILE` plus `APPLY_PATCH_OTHER_FILES`
- at most one configured Lean file, and it must be `APPLY_PATCH_TARGET_FILE`
- no add/delete/move grammar accepted in patch bodies
- target file supplied as structured MCP input
- raw MCP calls may pass only `path` and `patch` as tool arguments
- symlink targets are rejected
- non-regular files are rejected
- patch paths that escape the workspace root are rejected
- patch paths containing NUL bytes are rejected

Keep those constraints intact when syncing future upstream behavior.
