# dag-tracker MCP Server

`dag-tracker` is a stdio MCP server for querying dependency context from one
LeanArchitect blueprint file.

The server reads the target Lean file from:

```text
DAG_TARGET_FILE
```

`DAG_TARGET_FILE` may be absolute or relative to `DAG_PROJECT_ROOT`. If
`DAG_PROJECT_ROOT` is unset, it defaults to the LeanMarathon repository root
inferred from this server's location.

The proof DAG is built with the same parser and Lean elaborator dependency
probe used by `.scripts/verify_blueprint.py`: proof nodes are `lemma` and
`theorem` declarations, and an edge `A -> B` means `B` depends on `A`.
Definitional nodes are global context and are not proof-DAG vertices.

## Tools

All tools take exactly one argument:

```json
{"lean_name": "target_lean_name"}
```

The target must be a blueprint `lemma` or `theorem` node.

- `admissible_external_nodes`: returns proof nodes that can be cited by a
  local refinement of the target without creating a cycle. Nodes are marked
  `visible` when declared before the target and `invisible` otherwise.
- `parent_nodes`: returns the target node's direct upstream proof dependencies.
- `child_nodes`: returns proof nodes that directly depend on the target node.
- `global_definitional_context`: returns all definitional blueprint nodes with
  `latexEnv := "definition"`, including their Lean name, keyword, and
  `visible`/`invisible` class relative to the target declaration.

## Codex Config

Example registration:

```toml
[mcp_servers.dag-tracker]
command = "python3"
args = ["mcp-servers/dag-tracker/dag_tracker_mcp.py"]
startup_timeout_sec = 120
tool_timeout_sec = 600
enabled_tools = [
  "admissible_external_nodes",
  "parent_nodes",
  "child_nodes",
  "global_definitional_context",
]

[mcp_servers.dag-tracker.env]
DAG_PROJECT_ROOT = "<absolute path to LeanMarathon>"
DAG_TARGET_FILE = "<path to LeanMarathon/Main.lean, relative to DAG_PROJECT_ROOT>"
PATH = "<Lean bin path>:/usr/local/bin:/usr/bin:/bin"
PYTHONUTF8 = "1"
```

## Verification

```bash
.venv/bin/python3 mcp-servers/dag-tracker/dag_tracker_mcp.py --self-test
.venv/bin/python3 -m py_compile mcp-servers/dag-tracker/dag_tracker_mcp.py
```
