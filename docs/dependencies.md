# Dependencies

LeanMarathon v0.1 expects these tool versions:

| Tool | Version |
|---|---|
| Codex CLI | `0.128.0` |
| `lean-lsp-mcp` | `0.26.2` |
| `lean-explore` | `1.2.1` |
| `github-mcp-server` | `0.32.0` |
| `git-mcp-server` | `2.10.5` |

Lean itself is not pinned by LeanMarathon. The user installs Lean/Lake/Elan and
records tool paths plus the default Lean project root in `.leanmarathon.local.toml`.
Passing `--lean-project-root /path/to/lean-project` during `leanmarathon init`
overrides the local default for one target.
That project root must contain `lakefile.toml`, `lake-manifest.json`, and
`lean-toolchain`; its `.lake` cache is used by local Lean MCP/DAG tooling.

| Local config field | Meaning |
|---|---|
| `paths.venv_bin` | Python virtual environment `bin` directory containing Python MCP tools. |
| `paths.node_bin` | Node.js `bin` directory containing Codex and Node MCP tools. |
| `paths.elan_bin` | Lean/Elan `bin` directory containing `lake` and `lean`. |
| `lean.project_root` | Default Lean project root containing `lakefile.toml`. |

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
