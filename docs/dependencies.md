# Dependencies

LeanMarathon v0.1 expects these tool versions:

| Tool | Expected version |
|---|---|
| Codex CLI | `0.128.0` |
| `lean-lsp-mcp` | `0.26.2` |
| `lean-explore` | `1.2.1` |
| `github-mcp-server` | `0.32.0` |
| `git-mcp-server` | `2.10.5` |

Lean itself is user-provided. LeanMarathon does not pin the Lean version. The
user provides a Lean project root containing `lakefile.toml`,
`lake-manifest.json`, and `lean-toolchain` through `.leanmarathon.local.toml`
or `--lean-project-root`.

That Lean project root is used for local Lean tooling, `.lake` cache state,
Lean LSP, and DAG extraction. Agent worktrees are created under:

```text
<lean_project_root>/.leanmarathon-worktrees/<owner>/<repo>/
```

Important local config fields:

| Local config field | Meaning |
|---|---|
| `paths.venv_bin` | Python virtual environment `bin` directory. |
| `paths.node_bin` | Node.js `bin` directory containing Codex and Node MCP tools. |
| `paths.elan_bin` | Lean/Elan `bin` directory containing `lake` and `lean`. |
| `paths.agent_path` | Optional full PATH override for agent jobs. |
| `paths.orchestrator_path` | Optional full PATH override for orchestrator jobs. |
| `lean.project_root` | Default Lean project root containing Lake metadata. |

LeanMarathon ships local MCP servers for `apply-patch` and `dag-tracker`.
These external MCP servers must be installed separately:

```text
lean-lsp-mcp
lean-explore
github-mcp-server
git-mcp-server
```

PDF-reading packages are required:

| Import |
|---|
| `pdfplumber` |
| `fitz` |
| `pdfminer.high_level` |
| `pypdf` |
| `PyPDF2` |
| `pypdfium2` |

Numerical packages are optional and auto-detected during `leanmarathon init`.
There is no `--numeric-tool` option. Installed rows from LeanMarathon's known
numeric package table are exposed to agents in `docs/references/numeric-tools.md`.
