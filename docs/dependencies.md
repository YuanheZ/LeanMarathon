# Dependencies

LeanMarathon v0.1 expects these tool versions:

| Tool | Version |
|---|---|
| Codex CLI | `0.128.0` |
| `lean-lsp-mcp` | `0.26.2` |
| `lean-explore` | `1.2.1` |
| `github-mcp-server` | `0.32.0` |
| `git-mcp-server` | `2.10.5` |

Lean itself is not pinned by LeanMarathon. The user installs Lean/Lake/Elan,
provides tool paths through environment variables, and passes
`--lean-project-root /path/to/lean-project` during `leanmarathon init`.
That project root must contain `lakefile.toml`, `lake-manifest.json`, and
`lean-toolchain`; its `.lake` cache is used by local Lean MCP/DAG tooling.

| Variable | Meaning |
|---|---|
| `LEANMARATHON_VENV_BIN` | Python virtual environment `bin` directory containing Python MCP tools. |
| `LEANMARATHON_NODE_BIN` | Node.js `bin` directory containing Codex and Node MCP tools. |
| `LEANMARATHON_ELAN_BIN` | Lean/Elan `bin` directory containing `lake` and `lean`. |

PDF-reading packages are required:

| Import |
|---|
| `pdfplumber` |
| `fitz` |
| `pdfminer.high_level` |
| `pypdf` |
| `PyPDF2` |
| `pypdfium2` |

Numerical packages are optional. Pass installed imports with repeated
`--numeric-tool` options during `leanmarathon init`; agent worktrees keep only
those rows in `docs/references/numeric-tools.md`.
