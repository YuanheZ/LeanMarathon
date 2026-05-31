#!/usr/bin/env python3
"""Slurm-backed orchestrator for the Stage 2 Worker loop.

The script owns scheduling only. It creates per-agent worktrees via
`.scripts/create-worktree.sh`, materializes runtime inputs, submits each Codex
agent as a single Slurm job, and records the resulting Codex session ids.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(os.environ.get("ORCHESTRATOR_SOURCE_ROOT", str(REPO_ROOT))).resolve()
DEFAULT_LEAN_PROJECT_ROOT = SOURCE_ROOT
LEAN_PROJECT_ROOT_LABEL = os.environ.get(
    "ORCHESTRATOR_LEAN_PROJECT_ROOT",
    str(DEFAULT_LEAN_PROJECT_ROOT if DEFAULT_LEAN_PROJECT_ROOT.exists() else SOURCE_ROOT),
)
LEAN_PROJECT_ROOT = Path(LEAN_PROJECT_ROOT_LABEL).expanduser().resolve()
SCRIPTS_DIR = REPO_ROOT / ".scripts"
CREATE_WORKTREE = SCRIPTS_DIR / "create-worktree.sh"
VERIFY_BLUEPRINT = SCRIPTS_DIR / "verify_blueprint.py"
WORKER_CONFIG = REPO_ROOT / "agents" / "Worker"
REFINER_CONFIG = REPO_ROOT / "agents" / "Refiner"
CODEX_SESSIONS_ROOT = REPO_ROOT / ".codex-session-home"
PYTHON_BIN = sys.executable

def joined_path(*items: str) -> str:
    return os.pathsep.join(item for item in items if item)


LEANMARATHON_VENV_BIN = os.environ.get("LEANMARATHON_VENV_BIN", str(SOURCE_ROOT / ".venv" / "bin"))
LEANMARATHON_NODE_BIN = os.environ.get("LEANMARATHON_NODE_BIN", "")
LEANMARATHON_ELAN_BIN = os.environ.get("LEANMARATHON_ELAN_BIN", "")
AGENT_PATH = os.environ.get(
    "LEANMARATHON_AGENT_PATH",
    joined_path(LEANMARATHON_VENV_BIN, LEANMARATHON_NODE_BIN, LEANMARATHON_ELAN_BIN, "/usr/local/bin", "/usr/bin", "/bin"),
)
ORCH_PATH = os.environ.get("LEANMARATHON_ORCH_PATH", AGENT_PATH)
SLURM_ACCOUNT = os.environ.get("LEANMARATHON_SLURM_CPU_ACCOUNT", "")
SLURM_GPU_ACCOUNT = os.environ.get("LEANMARATHON_SLURM_GPU_ACCOUNT", "")
SLURM_GPU_PARTITION = os.environ.get("LEANMARATHON_SLURM_GPU_PARTITION", "gpu")
SLURM_GPU_GRES = os.environ.get("LEANMARATHON_SLURM_GPU_GRES", "gpu:lovelace_l40:1")
SLURM_MEM_PER_CPU = os.environ.get("LEANMARATHON_SLURM_MEM_PER_CPU", "3850")
AGENT_CPUS = int(os.environ.get("AGENT_CPUS", "16"))
AGENT_TIME = os.environ.get("AGENT_TIME", "4:00:00")
AGENT_RESOURCE_MODE = os.environ.get("AGENT_RESOURCE_MODE", "cpu").strip().lower()
ORCH_CPUS = int(os.environ.get("ORCH_CPUS", "8"))
ORCH_TIME = os.environ.get("ORCH_TIME", "48:00:00")
ORCH_RESOURCE_MODE = os.environ.get("ORCH_RESOURCE_MODE", "cpu").strip().lower()
POLL_SECONDS = 120
NUMERIC_TOOL_IMPORTS = {
    item.strip()
    for item in os.environ.get("LEANMARATHON_NUMERIC_TOOLS", "").split(",")
    if item.strip()
}

TERMINAL_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "TIMEOUT",
}


def log(message: str) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[worker-loop {now}] {message}", flush=True)


def run_cmd(
    args: list[str],
    *,
    cwd: Path = REPO_ROOT,
    check: bool = True,
    text: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        text=text,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        cmd = " ".join(shlex.quote(a) for a in args)
        raise RuntimeError(
            f"command failed ({proc.returncode}): {cmd}\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )
    return proc


def load_verify_module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_blueprint", VERIFY_BLUEPRINT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {VERIFY_BLUEPRINT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_blueprint"] = module
    spec.loader.exec_module(module)
    return module


VERIFY = load_verify_module()


@dataclass(frozen=True)
class ProofNode:
    name: str
    line: int
    body_kind: str
    deps: frozenset[str]


@dataclass(frozen=True)
class ProofDag:
    nodes: list[ProofNode]
    by_name: dict[str, ProofNode]


class DagExtractionTimeout(RuntimeError):
    pass


class DagExtractionBootstrapError(RuntimeError):
    pass


@dataclass
class AgentRun:
    kind: str
    branch: str
    worktree: str
    base_commit: str | None
    slurm_job_id: str
    codex_session_id: str | None
    returncode: int | None
    state: str | None
    result_file: str
    target_node: str | None = None
    tag: str | None = None

    def audit_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "kind": self.kind,
            "branch": self.branch,
            "worktree": self.worktree,
            "base_commit": self.base_commit,
            "slurm_job_id": self.slurm_job_id,
            "codex_session_id": self.codex_session_id,
            "returncode": self.returncode,
            "slurm_state": self.state,
            "result_file": self.result_file,
        }
        if self.target_node is not None:
            record["target_node"] = self.target_node
        if self.tag is not None:
            record["tag"] = self.tag
        return record


@dataclass
class LoopState:
    audit_dir: Path
    audit: list[dict[str, Any]] = field(default_factory=list)
    final_commit: str | None = None
    phase_status: str = "running"
    proof_status: dict[str, str] = field(default_factory=dict)
    reason: str | None = None

    @property
    def result_path(self) -> Path:
        return self.audit_dir / "result.json"

    @property
    def audit_path(self) -> Path:
        return self.audit_dir / "audit.jsonl"

    def append(self, entry: dict[str, Any]) -> None:
        self.audit.append(entry)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        self.write_result()

    def write_result(self) -> None:
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "final_commit": self.final_commit,
            "phase_status": {"phase_b": self.phase_status},
            "proof_status": self.proof_status,
            "audit_log": self.audit,
            "reason": self.reason,
        }
        tmp = self.result_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.result_path)


def yaml_quote(value: str) -> str:
    return json.dumps(value)


def branch_slug(name: str, *, limit: int = 180) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    base = base or "node"
    if len(base) > limit:
        base = base[:limit].rstrip(".-") or "node"
    return base


def job_slug(value: str, *, limit: int = 80) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")[:limit] or "job"


def codex_home_slug(value: str, *, limit: int = 180) -> str:
    return job_slug(value.replace("/", "-"), limit=limit)


def validate_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def validate_paths(branch_main: str, worktrees_root: Path) -> None:
    if branch_main != "main":
        raise ValueError(
            "--branch-main must be 'main': .scripts/create-worktree.sh hardcodes origin/main "
            "and the agent PR delivery templates target base 'main'."
        )
    expected = (REPO_ROOT / ".worktrees").resolve()
    actual = worktrees_root.resolve()
    if actual != expected:
        raise ValueError(
            f"--worktrees-root must resolve to {expected}; create-worktree.sh always uses that root. "
            f"Got {actual}."
        )
    for path in (CREATE_WORKTREE, VERIFY_BLUEPRINT, WORKER_CONFIG, REFINER_CONFIG):
        if not path.exists():
            raise FileNotFoundError(path)


def target_repo_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}.git"


def normalized_git_url(url: str) -> str:
    return url.rstrip("/")


def current_origin_url() -> str:
    return run_cmd(["git", "remote", "get-url", "origin"]).stdout.strip()


def target_origin_matches(owner: str, repo: str) -> bool:
    try:
        return normalized_git_url(current_origin_url()) == normalized_git_url(target_repo_url(owner, repo))
    except Exception:
        return False


def require_target_origin(owner: str, repo: str) -> None:
    expected = target_repo_url(owner, repo)
    actual = current_origin_url()
    if normalized_git_url(actual) != normalized_git_url(expected):
        raise RuntimeError(
            f"wrong orchestration root: origin is {actual!r}, expected {expected!r}. "
            "Use --submit-self from the source root so the per-target root is prepared automatically."
        )


def head_of_main(branch_main: str, owner: str, repo: str) -> str:
    require_target_origin(owner, repo)
    run_cmd(["git", "fetch", "origin", branch_main])
    return run_cmd(["git", "rev-parse", f"origin/{branch_main}"]).stdout.strip()


def current_main_head(branch_main: str, owner: str, repo: str) -> str:
    return head_of_main(branch_main, owner, repo)


def git_show(commit: str, relpath: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{commit}:{relpath}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"could not read {relpath} at {commit}:\n{proc.stderr.decode('utf-8', errors='replace')}"
        )
    return proc.stdout


def run_with_orch_path(cmd: list[str], *, cwd: Path, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    old_path = env.get("PATH", "")
    env["PATH"] = ORCH_PATH + (f":{old_path}" if old_path else "")
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=env,
    )


def ensure_leanarchitect_built() -> None:
    marker = LEAN_PROJECT_ROOT / ".lake" / "packages" / "LeanArchitect" / ".lake" / "build" / "lib" / "lean" / "Architect.olean"
    if marker.exists():
        return

    log(f"bootstrapping LeanArchitect before DAG extraction in {LEAN_PROJECT_ROOT_LABEL}")
    try:
        proc = run_with_orch_path(["lake", "build", "Architect"], cwd=LEAN_PROJECT_ROOT, timeout=3600)
    except subprocess.TimeoutExpired as exc:
        timeout = exc.timeout if exc.timeout is not None else "unknown"
        raise DagExtractionBootstrapError(
            f"LeanArchitect bootstrap timed out after {timeout} seconds"
        ) from exc
    if proc.returncode != 0:
        details = "\n".join(
            part
            for part in (
                VERIFY._tail(proc.stdout).strip(),
                VERIFY._tail(proc.stderr).strip(),
            )
            if part
        )
        raise DagExtractionBootstrapError(
            "LeanArchitect bootstrap failed"
            + (f":\n{details}" if details else "")
        )


def build_dag(commit: str, lean_file: str) -> ProofDag:
    ensure_leanarchitect_built()
    with tempfile.TemporaryDirectory(prefix="per-node-dag-") as temp:
        temp_root = Path(temp)
        materialized = temp_root / lean_file
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_bytes(git_show(commit, lean_file))

        nodes, anomalies = VERIFY.parse_file(materialized)
        if anomalies:
            raise RuntimeError("blueprint parser anomalies:\n" + "\n".join(anomalies))

        old_path = os.environ.get("PATH", "")
        old_threads = os.environ.get("VERIFY_BLUEPRINT_LEAN_THREADS")
        old_cwd = Path.cwd()
        os.environ["PATH"] = ORCH_PATH + (f":{old_path}" if old_path else "")
        os.environ["VERIFY_BLUEPRINT_LEAN_THREADS"] = str(ORCH_CPUS)
        try:
            try:
                os.chdir(LEAN_PROJECT_ROOT)
                deps_by_name, failures = VERIFY.extract_elaborated_proof_deps([materialized], nodes)
            except subprocess.TimeoutExpired as exc:
                timeout = exc.timeout if exc.timeout is not None else "unknown"
                raise DagExtractionTimeout(
                    f"Lean elaboration-based DAG extraction timed out after {timeout} seconds"
                ) from exc
        finally:
            os.chdir(old_cwd)
            os.environ["PATH"] = old_path
            if old_threads is None:
                os.environ.pop("VERIFY_BLUEPRINT_LEAN_THREADS", None)
            else:
                os.environ["VERIFY_BLUEPRINT_LEAN_THREADS"] = old_threads
        if failures:
            raise RuntimeError("Lean elaboration-based DAG extraction failed:\n" + "\n".join(failures))

        proof_nodes: list[ProofNode] = []
        for node in nodes:
            if node.keyword not in VERIFY.PROOF_KEYWORDS or not node.lean_name:
                continue
            proof_nodes.append(
                ProofNode(
                    name=node.lean_name,
                    line=node.line_decl,
                    body_kind=node.body_kind,
                    deps=frozenset(deps_by_name.get(node.lean_name, set())),
                )
            )
        return ProofDag(nodes=proof_nodes, by_name={node.name: node for node in proof_nodes})


def unproven_nodes(dag: ProofDag) -> list[ProofNode]:
    return [node for node in dag.nodes if node.body_kind in {"by_sorry", "by_sorry_using"}]


def dynamic_leaves(dag: ProofDag) -> list[ProofNode]:
    unproven = unproven_nodes(dag)
    unproven_names = {node.name for node in unproven}
    return [node for node in unproven if node.deps.isdisjoint(unproven_names)]


def create_worktree(branch: str, config_dir: Path, owner: str, repo: str, base_commit: str) -> Path:
    worktree = REPO_ROOT / ".worktrees" / branch
    if worktree.exists():
        raise FileExistsError(f"worktree already exists: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)

    run_cmd(
        [
            "bash",
            str(CREATE_WORKTREE),
            "--branch",
            branch,
            "--config",
            str(config_dir),
            "--owner",
            owner,
            "--repo",
            repo,
        ]
    )
    actual = run_cmd(["git", "-C", str(worktree), "rev-parse", "HEAD"]).stdout.strip()
    if actual != base_commit:
        log(
            f"pinning {branch} from {actual[:12]} back to round base {base_commit[:12]} "
            "after create-worktree.sh fetched a newer main"
        )
        run_cmd(["git", "-C", str(worktree), "reset", "--hard", base_commit])
        run_cmd(["git", "-C", str(worktree), "push", "--force-with-lease", "origin", branch])
    return worktree


def ensure_worktree_file(worktree: Path, rel_path: str, base_commit: str, *, label: str) -> None:
    absolute = Path(rel_path)
    if absolute.is_absolute():
        if absolute.exists():
            return
        raise FileNotFoundError(f"{label} {rel_path!r} does not exist")
    dest = worktree / rel_path
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    for root in dict.fromkeys([REPO_ROOT, SOURCE_ROOT]):
        source = root / rel_path
        if source.exists():
            if source.is_dir():
                shutil.copytree(source, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(source, dest)
            return
    try:
        dest.write_bytes(git_show(base_commit, rel_path))
        return
    except RuntimeError as exc:
        raise FileNotFoundError(
            f"{label} {rel_path!r} is absent from {worktree}, {source}, "
            f"and commit {base_commit}"
        ) from exc


def ensure_problem_file(worktree: Path, problem_file: str, base_commit: str) -> None:
    ensure_worktree_file(worktree, problem_file, base_commit, label="problem_file")


def ensure_proof_file(worktree: Path, proof_file: str, base_commit: str) -> None:
    ensure_worktree_file(worktree, proof_file, base_commit, label="proof_file")


def replace_toml_string(text: str, key: str, value: str) -> str:
    quoted = json.dumps(value)
    pattern = re.compile(rf"(^\s*{re.escape(key)}\s*=\s*)\".*?\"", re.MULTILINE)
    new_text, count = pattern.subn(rf"\g<1>{quoted}", text)
    if count == 0:
        raise RuntimeError(f"could not find TOML key {key!r} in copied Codex config")
    return new_text


def replace_stop_hook_command(text: str, worktree: Path) -> str:
    hook = worktree / ".codex" / "hooks" / "ralph_wiggum_stop.py"
    command = (
        f"{PYTHON_BIN} {hook} "
        f"--config-dir {worktree} --workspace-dir {worktree}"
    )
    pattern = re.compile(
        r'(\[\[hooks\.Stop\.hooks\]\]\s*\ntype\s*=\s*"command"\s*\ncommand\s*=\s*)".*?"',
        re.MULTILINE,
    )
    new_text, count = pattern.subn(rf"\g<1>{json.dumps(command)}", text, count=1)
    if count == 0:
        raise RuntimeError("could not find Stop hook command in copied Codex config")
    return new_text


def replace_lean_project_path(text: str) -> str:
    project_path = str(Path(LEAN_PROJECT_ROOT_LABEL) / "lakefile.toml")
    pattern = re.compile(r'("--lean-project-path"\s*,\s*)".*?"')
    new_text, count = pattern.subn(rf"\g<1>{json.dumps(project_path)}", text)
    if count == 0:
        raise RuntimeError("could not find lean-lsp-mcp --lean-project-path in copied Codex config")
    return new_text


def replace_template_paths(text: str) -> str:
    replacements = {
        "__LEANMARATHON_ROOT__": str(SOURCE_ROOT),
        "__LEANMARATHON_PYTHON__": PYTHON_BIN,
        "__LEANMARATHON_PATH__": AGENT_PATH,
        "__LEANMARATHON_ELAN_PATH__": joined_path(LEANMARATHON_ELAN_BIN, "/usr/local/bin", "/usr/bin", "/bin"),
        "__LEANMARATHON_APPLY_PATCH_MCP__": str(SOURCE_ROOT / "mcp-servers" / "apply-patch" / "apply_patch_mcp.py"),
        "__LEANMARATHON_DAG_TRACKER_MCP__": str(SOURCE_ROOT / "mcp-servers" / "dag-tracker" / "dag_tracker_mcp.py"),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def materialize_runtime_reference_docs(worktree: Path) -> None:
    numeric_doc = worktree / "docs" / "references" / "numeric-tools.md"
    if numeric_doc.exists():
        lines = numeric_doc.read_text(encoding="utf-8").splitlines()
        filtered: list[str] = []
        row_pattern = re.compile(r"^\|\s*`([^`]+)`\s*\|")
        for line in lines:
            match = row_pattern.match(line)
            if match and match.group(1) not in NUMERIC_TOOL_IMPORTS:
                continue
            filtered.append(line)
        numeric_doc.write_text("\n".join(filtered).rstrip() + "\n", encoding="utf-8")


def patch_codex_config(worktree: Path, lean_file: str, target_node: str | None = None) -> None:
    config = worktree / ".codex" / "config.toml"
    text = config.read_text(encoding="utf-8")
    try:
        rel_dag_target = str((worktree / lean_file).resolve().relative_to(LEAN_PROJECT_ROOT))
    except ValueError:
        rel_dag_target = str(worktree / lean_file)
    text = replace_template_paths(text)
    text = replace_stop_hook_command(text, worktree)
    text = replace_lean_project_path(text)

    for key, value in {
        "GIT_BASE_DIR": str(worktree),
        "APPLY_PATCH_WORKSPACE": str(worktree),
        "APPLY_PATCH_TARGET_FILE": lean_file,
        "DAG_PROJECT_ROOT": LEAN_PROJECT_ROOT_LABEL,
        "DAG_TARGET_FILE": rel_dag_target,
    }.items():
        text = replace_toml_string(text, key, value)

    if target_node is not None:
        text = replace_toml_string(text, "APPLY_PATCH_NODE", target_node)

    config.write_text(text, encoding="utf-8")
    materialize_runtime_reference_docs(worktree)


def write_worker_inputs(
    worktree: Path,
    *,
    target_node: str,
    lean_file: str,
    problem_file: str,
    owner: str,
    repo: str,
    branch: str,
    worktrees_root: Path,
) -> None:
    content = "\n".join(
        [
            f"target_node: {yaml_quote(target_node)}",
            f"problem_file: {yaml_quote(problem_file)}",
            f"lean_file: {yaml_quote(lean_file)}",
            f"owner: {yaml_quote(owner)}",
            f"repo: {yaml_quote(repo)}",
            f"branch: {yaml_quote(branch)}",
            f"worktrees_root: {yaml_quote(str(worktrees_root))}",
            "",
        ]
    )
    (worktree / "docs" / "inputs.yml").write_text(content, encoding="utf-8")


def write_refiner_inputs(
    worktree: Path,
    *,
    lean_file: str,
    problem_file: str,
    proof_file: str,
    owner: str,
    repo: str,
    branch: str,
    worktrees_root: Path,
) -> None:
    content = "\n".join(
        [
            f"problem_file: {yaml_quote(problem_file)}",
            f"proof_file: {yaml_quote(proof_file)}",
            'issues_file: "issue/"',
            f"lean_file: {yaml_quote(lean_file)}",
            f"owner: {yaml_quote(owner)}",
            f"repo: {yaml_quote(repo)}",
            f"branch: {yaml_quote(branch)}",
            f"worktrees_root: {yaml_quote(str(worktrees_root))}",
            "",
        ]
    )
    (worktree / "docs" / "inputs.yml").write_text(content, encoding="utf-8")


def gh_json(args: list[str]) -> Any:
    proc = run_cmd(["gh", *args])
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh did not return JSON for {' '.join(args)}:\n{proc.stdout}") from exc


def list_open_issues(owner: str, repo: str) -> list[dict[str, Any]]:
    data = gh_json(
        [
            "issue",
            "list",
            "--repo",
            f"{owner}/{repo}",
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number,title",
        ]
    )
    if not isinstance(data, list):
        raise RuntimeError("gh issue list returned non-list JSON")
    return data


def compilation_issue_title(lean_file: str, commit: str) -> str:
    return "Lean file cannot compile"


def compilation_issue_body(lean_file: str, problem_file: str, branch_main: str, commit: str) -> str:
    return "\n".join(
        [
            "The Lean file cannot compile.",
            "",
            "Please repair the compilation failure so the blueprint can successfully compile.",
        ]
    )


def ensure_compilation_issue(
    *,
    owner: str,
    repo: str,
    lean_file: str,
    problem_file: str,
    branch_main: str,
    commit: str,
) -> dict[str, Any]:
    title = compilation_issue_title(lean_file, commit)
    for issue in list_open_issues(owner, repo):
        if issue.get("title") == title:
            log(f"reusing open Lean compilation issue #{issue.get('number')}: {title}")
            return {"number": int(issue["number"]), "title": title, "created": False}

    body = compilation_issue_body(lean_file, problem_file, branch_main, commit)
    proc = run_cmd(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            f"{owner}/{repo}",
            "--title",
            title,
            "--body-file",
            "-",
        ],
        input_text=body,
    )
    match = re.search(r"/issues/(\d+)", proc.stdout)
    if match:
        number = int(match.group(1))
        log(f"filed Lean compilation issue #{number}: {title}")
        return {"number": number, "title": title, "created": True}

    for issue in list_open_issues(owner, repo):
        if issue.get("title") == title:
            log(f"filed Lean compilation issue #{issue.get('number')}: {title}")
            return {"number": int(issue["number"]), "title": title, "created": True}
    raise RuntimeError(f"created issue but could not determine issue number:\n{proc.stdout}")


def render_issue_context(worktree: Path, owner: str, repo: str, issues: list[dict[str, Any]]) -> None:
    issue_dir = worktree / "issue"
    issue_dir.mkdir(parents=True, exist_ok=True)
    for old in issue_dir.glob("#*.md"):
        old.unlink()

    for item in issues:
        number = int(item["number"])
        detail = gh_json(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                f"{owner}/{repo}",
                "--json",
                "number,title,body,comments",
            ]
        )
        title = str(detail.get("title") or item.get("title") or f"Issue #{number}")
        body = str(detail.get("body") or "").rstrip()
        parts = [body] if body else ["(issue body is empty)"]
        comments = detail.get("comments")
        if isinstance(comments, list) and comments:
            parts.append("\n## Comments")
            for comment in comments:
                if not isinstance(comment, dict):
                    continue
                author = comment.get("author")
                login = author.get("login") if isinstance(author, dict) else "unknown"
                created = comment.get("createdAt") or "unknown time"
                comment_body = str(comment.get("body") or "").rstrip() or "(comment body is empty)"
                parts.append(f"\n### {login} at {created}\n\n{comment_body}")

        issue_text = (
            "```\n"
            f"title: {title}\n"
            f"number: {number}\n"
            "```\n\n"
            + "\n".join(parts).rstrip()
            + "\n"
        )
        (issue_dir / f"#{number}.md").write_text(issue_text, encoding="utf-8")


def read_agent_result(result_file: Path) -> dict[str, Any]:
    if not result_file.exists():
        return {}
    try:
        return json.loads(result_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def agent_resource_directives(agent_resource: str) -> str:
    if agent_resource == "cpu":
        return ""
    if agent_resource == "gpu":
        return "\n".join(
            [
                f"#SBATCH --partition={SLURM_GPU_PARTITION}",
                f"#SBATCH --gres={SLURM_GPU_GRES}",
            ]
        )
    raise ValueError(f"unknown agent resource mode: {agent_resource!r}")


def agent_slurm_account(agent_resource: str) -> str:
    if agent_resource == "cpu":
        return SLURM_ACCOUNT
    if agent_resource == "gpu":
        return SLURM_GPU_ACCOUNT
    raise ValueError(f"unknown agent resource mode: {agent_resource!r}")


def account_directive(account: str) -> str:
    return f"#SBATCH --account={account}" if account else ""


def leanmarathon_env_exports() -> str:
    return "\n".join(
        f"export {key}={shlex.quote(value)}"
        for key, value in sorted(os.environ.items())
        if key.startswith("LEANMARATHON_")
    )


def github_auth_bootstrap() -> str:
    return """if [[ -z "${GITHUB_TOKEN:-}" && -z "${GITHUB_PERSONAL_ACCESS_TOKEN:-}" ]] && command -v gh >/dev/null 2>&1; then
  _leanmarathon_gh_token="$(gh auth token 2>/dev/null || true)"
  if [[ -n "$_leanmarathon_gh_token" ]]; then
    export GITHUB_TOKEN="$_leanmarathon_gh_token"
    export GITHUB_PERSONAL_ACCESS_TOKEN="$_leanmarathon_gh_token"
  fi
  unset _leanmarathon_gh_token
fi
if [[ -n "${GITHUB_TOKEN:-}" && -z "${GITHUB_PERSONAL_ACCESS_TOKEN:-}" ]]; then
  export GITHUB_PERSONAL_ACCESS_TOKEN="$GITHUB_TOKEN"
fi
if [[ -n "${GITHUB_PERSONAL_ACCESS_TOKEN:-}" && -z "${GITHUB_TOKEN:-}" ]]; then
  export GITHUB_TOKEN="$GITHUB_PERSONAL_ACCESS_TOKEN"
fi"""


def make_agent_job_script(
    *,
    job_file: Path,
    job_name: str,
    branch: str,
    worktree: Path,
    result_file: Path,
    codex_home: Path,
    agent_resource: str = AGENT_RESOURCE_MODE,
) -> None:
    account = agent_slurm_account(agent_resource)
    account_line = account_directive(account)
    resource_directives = agent_resource_directives(agent_resource)
    env_exports = leanmarathon_env_exports()
    script = f"""#!/usr/bin/env bash
{account_line}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={AGENT_CPUS}
#SBATCH --mem-per-cpu={SLURM_MEM_PER_CPU}
{resource_directives}
#SBATCH --time={AGENT_TIME}
#SBATCH --job-name={job_name}
#SBATCH --output={shlex.quote(str(job_file.with_suffix(".out")))}
#SBATCH --error={shlex.quote(str(job_file.with_suffix(".err")))}

set +e
export PATH={shlex.quote(AGENT_PATH)}
{env_exports}
{github_auth_bootstrap()}
export AGENT_CPUS={AGENT_CPUS}
export AGENT_TIME={shlex.quote(AGENT_TIME)}
export LEANMARATHON_NUMERIC_TOOLS={shlex.quote(os.environ.get("LEANMARATHON_NUMERIC_TOOLS", ""))}
export VERIFY_BLUEPRINT_LEAN_THREADS={AGENT_CPUS}
export LEAN_LSP_THREADS={AGENT_CPUS}
export DAG_TRACKER_LEAN_THREADS={AGENT_CPUS}
export LEANMARATHON_SLURM_MEM_PER_CPU={shlex.quote(str(SLURM_MEM_PER_CPU))}
export LEANMARATHON_TOTAL_MEM_MB=$((AGENT_CPUS * LEANMARATHON_SLURM_MEM_PER_CPU))
REAL_CODEX_HOME="${{CODEX_HOME:-$HOME/.codex}}"
export CODEX_HOME={shlex.quote(str(codex_home))}
mkdir -p "$CODEX_HOME"
if [[ -f "$REAL_CODEX_HOME/auth.json" ]]; then
  ln -sf "$REAL_CODEX_HOME/auth.json" "$CODEX_HOME/auth.json"
fi
if [[ -f "$REAL_CODEX_HOME/config.toml" ]]; then
  cp "$REAL_CODEX_HOME/config.toml" "$CODEX_HOME/config.toml"
else
  : > "$CODEX_HOME/config.toml"
fi
python3 - "$CODEX_HOME/config.toml" {shlex.quote(str(worktree))} <<'PY'
import json
import re
import sys
from pathlib import Path

config = Path(sys.argv[1])
worktree_path = Path(sys.argv[2])
worktree = str(worktree_path)
target_header = f"[projects.{{json.dumps(worktree)}}]"

lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
kept = []
index = 0
while index < len(lines):
    if lines[index].strip() == target_header:
        index += 1
        while index < len(lines) and not lines[index].lstrip().startswith("["):
            index += 1
        continue
    kept.append(lines[index])
    index += 1

while kept and not kept[-1].strip():
    kept.pop()
if kept:
    kept.append("")
kept.extend([target_header, 'trust_level = "trusted"', ""])

features_header = "[features]"
out = []
found_features = False
in_features = False
saw_hooks = False
for line in kept:
    stripped = line.strip()
    if stripped == features_header:
        found_features = True
        in_features = True
        saw_hooks = False
        out.append(line)
        continue
    if in_features and stripped.startswith("["):
        if not saw_hooks:
            out.append("codex_hooks = true")
        in_features = False
    if in_features and re.match(r"^(?:hooks|codex_hooks)\\s*=", stripped):
        if not saw_hooks:
            out.append("codex_hooks = true")
            saw_hooks = True
        continue
    out.append(line)
if in_features and not saw_hooks:
    out.append("codex_hooks = true")
if not found_features:
    if out and out[-1].strip():
        out.append("")
    out.extend([features_header, "codex_hooks = true", ""])
config.write_text("\\n".join(out), encoding="utf-8")
PY
cd {shlex.quote(str(worktree))}
START_TS="$(date +%s)"
codex exec "Begin from Phase 1"
RC=$?
if [[ "$RC" -eq 0 ]]; then
python3 - {shlex.quote(str(worktree))} <<'PY'
import json
import subprocess
import sys
from pathlib import Path

import yaml

worktree = Path(sys.argv[1])
delivery_path = worktree / "docs" / "delivery.yml"
if not delivery_path.exists():
    print("delivery guard: docs/delivery.yml is missing after successful Codex exit", file=sys.stderr)
    sys.exit(1)

try:
    delivery = yaml.safe_load(delivery_path.read_text(encoding="utf-8"))
except Exception as exc:
    print("delivery guard: could not parse docs/delivery.yml: %s" % exc, file=sys.stderr)
    sys.exit(1)

if not isinstance(delivery, dict):
    print("delivery guard: docs/delivery.yml is not a mapping", file=sys.stderr)
    sys.exit(1)

kind = delivery.get("kind")
if kind == "issue":
    sys.exit(0)
if kind != "pr":
    print("delivery guard: unknown delivery kind %r" % (kind,), file=sys.stderr)
    sys.exit(1)

owner = delivery.get("owner")
repo = delivery.get("repo")
number = delivery.get("number")
if not isinstance(owner, str) or not isinstance(repo, str) or not isinstance(number, int):
    print("delivery guard: PR delivery record has invalid owner/repo/number", file=sys.stderr)
    sys.exit(1)

proc = subprocess.run(
    [
        "gh",
        "pr",
        "view",
        str(number),
        "--repo",
        "%s/%s" % (owner, repo),
        "--json",
        "state,mergedAt",
    ],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
if proc.returncode != 0:
    print("delivery guard: could not verify PR #%s merge status: %s" % (number, proc.stderr.strip()), file=sys.stderr)
    sys.exit(1)

try:
    pr = json.loads(proc.stdout)
except json.JSONDecodeError as exc:
    print("delivery guard: could not parse PR #%s merge status: %s" % (number, exc), file=sys.stderr)
    sys.exit(1)

if pr.get("state") == "MERGED" and pr.get("mergedAt"):
    sys.exit(0)

print("delivery guard: PR #%s is not merged; preserving worktree and branch" % number, file=sys.stderr)
sys.exit(1)
PY
GUARD_RC=$?
if [[ "$GUARD_RC" -ne 0 ]]; then
  RC="$GUARD_RC"
fi
fi
python3 - "$CODEX_HOME" {shlex.quote(str(result_file))} "$RC" "$START_TS" <<'PY'
import json
import sys
from pathlib import Path

codex_home = Path(sys.argv[1])
result = Path(sys.argv[2])
rc = int(sys.argv[3])
start_ts = int(sys.argv[4])
sessions = []
history = codex_home / "history.jsonl"
if history.exists():
    with history.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("text") != "Begin from Phase 1":
                continue
            try:
                ts = int(item.get("ts", 0))
            except (TypeError, ValueError):
                ts = 0
            if ts >= start_ts - 10 and item.get("session_id"):
                sessions.append(str(item["session_id"]))

payload = {{
    "returncode": rc,
    "codex_session_id": sessions[-1] if sessions else None,
    "session_candidates": sessions,
}}
result.parent.mkdir(parents=True, exist_ok=True)
tmp = result.with_suffix(result.suffix + ".tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
tmp.replace(result)
PY

cd {shlex.quote(str(REPO_ROOT))}
if [[ "$RC" -eq 0 ]]; then
  echo "Cleaning worktree branch {shlex.quote(branch)} at {shlex.quote(str(worktree))}" >&2
  if git worktree remove --force {shlex.quote(str(worktree))}; then
    git branch -D {shlex.quote(branch)} || true
    git push origin --delete {shlex.quote(branch)} || true
  else
    echo "warning: failed to remove worktree {shlex.quote(str(worktree))}" >&2
  fi
else
  echo "Skipping worktree cleanup for {shlex.quote(branch)} because job did not reach a verified terminal delivery" >&2
fi

python3 - "$CODEX_HOME" <<'PY'
import shutil
import sys
from pathlib import Path

codex_home = Path(sys.argv[1])
sessions = codex_home / "sessions"
if not codex_home.exists():
    sys.exit(0)

if sessions.exists():
    for item in sessions.rglob("*"):
        if item.is_symlink():
            item.unlink(missing_ok=True)
        elif item.is_file() and item.suffix != ".jsonl":
            item.unlink(missing_ok=True)

for child in list(codex_home.iterdir()):
    if child == sessions:
        continue
    if child.is_symlink() or child.is_file():
        child.unlink(missing_ok=True)
    elif child.is_dir():
        shutil.rmtree(child, ignore_errors=True)

if sessions.exists():
    for item in sorted((p for p in sessions.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            item.rmdir()
        except OSError:
            pass
PY
exit "$RC"
"""
    job_file.write_text(script, encoding="utf-8")
    job_file.chmod(0o755)


def submit_job(job_file: Path) -> str:
    proc = run_cmd(["sbatch", "--parsable", str(job_file)])
    return proc.stdout.strip().split(";", 1)[0]


def slurm_state(job_id: str) -> tuple[str | None, str | None]:
    squeue = subprocess.run(
        ["squeue", "-j", job_id, "-h", "-o", "%T"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if squeue.returncode == 0 and squeue.stdout.strip():
        return squeue.stdout.strip().splitlines()[0], None

    sacct = subprocess.run(
        ["sacct", "-j", job_id, "--format=JobID,State,ExitCode", "-n", "-P"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if sacct.returncode == 0:
        for line in sacct.stdout.splitlines():
            parts = line.split("|")
            if len(parts) >= 3 and parts[0] == job_id:
                return parts[1].split()[0], parts[2]
    return None, None


def wait_for_jobs(job_ids: list[str], poll_seconds: int) -> dict[str, tuple[str | None, str | None]]:
    remaining = set(job_ids)
    states: dict[str, tuple[str | None, str | None]] = {}
    while remaining:
        for job_id in list(remaining):
            state, exit_code = slurm_state(job_id)
            if state in TERMINAL_STATES:
                states[job_id] = (state, exit_code)
                remaining.remove(job_id)
        if remaining:
            log(f"waiting for Slurm jobs: {', '.join(sorted(remaining))}")
            time.sleep(poll_seconds)
    return states


def launch_agents(
    handles: list[dict[str, Any]],
    *,
    audit_dir: Path,
    poll_seconds: int,
    agent_resource: str = AGENT_RESOURCE_MODE,
) -> list[AgentRun]:
    if not handles:
        return []
    jobs_dir = audit_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    submitted: list[tuple[dict[str, Any], str, Path]] = []
    for handle in handles:
        label = handle.get("target_node") or handle.get("tag") or handle["branch"]
        job_dir = jobs_dir / job_slug(handle["kind"]) / job_slug(label, limit=180)
        job_dir.mkdir(parents=True, exist_ok=True)
        job_file = job_dir / "job.sbatch"
        result_file = job_dir / "result.json"
        codex_home = CODEX_SESSIONS_ROOT / codex_home_slug(handle["branch"])
        make_agent_job_script(
            job_file=job_file,
            job_name=job_slug(f"leanmarathon-{handle['kind']}-{label}", limit=60),
            branch=handle["branch"],
            worktree=Path(handle["worktree"]),
            result_file=result_file,
            codex_home=codex_home,
            agent_resource=agent_resource,
        )
        job_id = submit_job(job_file)
        log(f"submitted {handle['kind']} {label} as Slurm job {job_id}")
        submitted.append((handle, job_id, result_file))

    states = wait_for_jobs([job_id for _, job_id, _ in submitted], poll_seconds)
    runs: list[AgentRun] = []
    for handle, job_id, result_file in submitted:
        result = read_agent_result(result_file)
        state, _exit_code = states.get(job_id, (None, None))
        run = AgentRun(
            kind=handle["kind"],
            branch=handle["branch"],
            worktree=handle["worktree"],
            base_commit=handle.get("base_commit"),
            slurm_job_id=job_id,
            codex_session_id=result.get("codex_session_id"),
            returncode=result.get("returncode"),
            state=state,
            result_file=str(result_file),
            target_node=handle.get("target_node"),
            tag=handle.get("tag"),
        )
        runs.append(run)
        if run.returncode == 0:
            if run.state != "COMPLETED":
                log(
                    f"{run.kind} job {job_id} for {handle.get('target_node') or handle.get('tag')} "
                    f"delivered successfully with Slurm state={run.state}; continuing"
                )
            continue
        if run.state != "COMPLETED" or run.returncode not in (0, None):
            raise RuntimeError(
                f"{run.kind} job {job_id} for {handle.get('target_node') or handle.get('tag')} "
                f"ended with state={run.state}, returncode={run.returncode}; see {result_file}"
            )
    return runs


def preallocate_worker(
    *,
    round_id: int,
    target_node: str,
    owner: str,
    repo: str,
    worktrees_root: Path,
    lean_file: str,
    problem_file: str,
    base_commit: str,
) -> dict[str, Any]:
    branch = f"round-{round_id}/{branch_slug(target_node)}"
    worktree = create_worktree(branch, WORKER_CONFIG, owner, repo, base_commit)
    ensure_problem_file(worktree, problem_file, base_commit)
    patch_codex_config(worktree, lean_file, target_node=target_node)
    write_worker_inputs(
        worktree,
        target_node=target_node,
        lean_file=lean_file,
        problem_file=problem_file,
        owner=owner,
        repo=repo,
        branch=branch,
        worktrees_root=worktrees_root,
    )
    return {
        "kind": "Worker",
        "target_node": target_node,
        "branch": branch,
        "worktree": str(worktree),
        "base_commit": base_commit,
    }


def preallocate_refiner(
    *,
    tag: str,
    owner: str,
    repo: str,
    worktrees_root: Path,
    lean_file: str,
    problem_file: str,
    proof_file: str,
    base_commit: str,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    round_match = re.fullmatch(r"round-(\d+)", tag)
    branch = f"refiner/round-{round_match.group(1)}" if round_match else f"refiner/{branch_slug(tag)}"
    worktree = create_worktree(branch, REFINER_CONFIG, owner, repo, base_commit)
    ensure_problem_file(worktree, problem_file, base_commit)
    ensure_proof_file(worktree, proof_file, base_commit)
    render_issue_context(worktree, owner, repo, issues)
    patch_codex_config(worktree, lean_file)
    write_refiner_inputs(
        worktree,
        lean_file=lean_file,
        problem_file=problem_file,
        proof_file=proof_file,
        owner=owner,
        repo=repo,
        branch=branch,
        worktrees_root=worktrees_root,
    )
    return {
        "kind": "Refiner",
        "tag": tag,
        "branch": branch,
        "worktree": str(worktree),
        "base_commit": base_commit,
        "issue_numbers": [int(issue["number"]) for issue in issues],
    }


def batch(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def open_blocker_titles(owner: str, repo: str) -> set[str]:
    try:
        return {str(issue.get("title") or "") for issue in list_open_issues(owner, repo)}
    except Exception as exc:
        log(f"could not fetch open issues for proof_status classification: {exc}")
        return set()


def classify_proofs(commit: str, lean_file: str, owner: str, repo: str) -> dict[str, str]:
    dag = build_dag(commit, lean_file)
    blocker_titles = open_blocker_titles(owner, repo)
    status: dict[str, str] = {}
    for node in dag.nodes:
        if node.body_kind not in {"by_sorry", "by_sorry_using"}:
            status[node.name] = "proven"
        elif f"Blocked blueprint node: {node.name}" in blocker_titles:
            status[node.name] = "permanently_blocked"
        else:
            status[node.name] = "still_sorry"
    return status


def classify_proofs_safely(commit: str, lean_file: str, owner: str, repo: str) -> dict[str, str]:
    try:
        return classify_proofs(commit, lean_file, owner, repo)
    except Exception as exc:
        log(f"could not classify proof status at {commit[:12]}: {exc}")
        return {}


def stage2_audit_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    runs_root = REPO_ROOT / ".orchestrator-runs"
    if not runs_root.exists():
        return entries
    for path in sorted(runs_root.glob("**/audit.jsonl")):
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("phase") == "B" and isinstance(entry.get("round"), int):
                    entry["_audit_path"] = str(path)
                    entries.append(entry)
    return entries


def parse_start_round(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"", "auto"}:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError("--start-round must be a positive integer when provided") from exc


def infer_start_round(args: argparse.Namespace) -> int:
    explicit = parse_start_round(args.start_round)
    if explicit is not None:
        return explicit

    entries = stage2_audit_entries()
    if not entries:
        log("start round auto: no previous Stage 2 audit found; using round 1")
        return 1

    latest_round = max(int(entry["round"]) for entry in entries)
    latest_entries = [entry for entry in entries if int(entry["round"]) == latest_round]
    latest_kinds = {str(entry.get("kind") or "") for entry in latest_entries}
    try:
        open_issues = list_open_issues(args.owner, args.repo)
    except Exception as exc:
        log(f"start round auto: could not fetch open issues ({exc}); using round {latest_round + 1}")
        return latest_round + 1

    issue_waiting_round = (
        bool(open_issues)
        and "refiner" not in latest_kinds
        and any(kind in latest_kinds for kind in {"workers", "compile_check_failed"})
    )
    if issue_waiting_round:
        log(
            f"start round auto: latest round {latest_round} has open issues and no refiner record; "
            f"resuming round {latest_round}"
        )
        return latest_round

    next_round = latest_round + 1
    log(f"start round auto: latest recorded Stage 2 round is {latest_round}; using round {next_round}")
    return next_round


def run_refiner_for_open_issues(
    *,
    round_id: int,
    args: argparse.Namespace,
    worktrees_root: Path,
    audit_dir: Path,
    base_commit: str,
    state: LoopState,
    guaranteed_issues: list[dict[str, Any]] | None = None,
) -> AgentRun | None:
    open_issues = list_open_issues(args.owner, args.repo)
    if guaranteed_issues:
        seen = {int(issue["number"]) for issue in open_issues}
        for issue in guaranteed_issues:
            number = int(issue["number"])
            if number not in seen:
                open_issues.append({"number": number, "title": issue.get("title") or f"Issue #{number}"})
                seen.add(number)
    if not open_issues:
        return None

    issue_numbers = [int(issue["number"]) for issue in open_issues]
    log(
        f"round {round_id}: open issues present; launching refiner for {issue_numbers} "
        f"from {base_commit[:12]}"
    )
    refiner_handle = preallocate_refiner(
        tag=f"round-{round_id}",
        owner=args.owner,
        repo=args.repo,
        worktrees_root=worktrees_root,
        lean_file=args.lean_file,
        problem_file=args.problem_file,
        proof_file=args.proof_file,
        base_commit=base_commit,
        issues=open_issues,
    )
    refiner_run = launch_agents(
        [refiner_handle],
        audit_dir=audit_dir / f"round-{round_id}" / "refiner",
        poll_seconds=args.poll_seconds,
        agent_resource=args.agent_resource,
    )[0]
    state.append(
        {
            "phase": "B",
            "round": round_id,
            "kind": "refiner",
            "item": refiner_run.audit_record(),
        }
    )
    return refiner_run


def per_node_loop(args: argparse.Namespace) -> LoopState:
    worktrees_root = Path(args.worktrees_root)
    validate_positive("--n", args.n)
    validate_positive("--max-rounds", args.max_rounds)
    start_round = infer_start_round(args)
    validate_positive("--start-round", start_round)
    if start_round > args.max_rounds:
        raise ValueError(
            f"--start-round ({start_round}) must be <= --max-rounds ({args.max_rounds})"
        )
    validate_paths(args.branch_main, worktrees_root)

    audit_dir = Path(args.audit_dir) if args.audit_dir else default_audit_dir()
    state = LoopState(audit_dir=audit_dir)
    state.write_result()

    base = current_main_head(args.branch_main, args.owner, args.repo)
    commit = base
    log(f"starting Phase B from origin/{args.branch_main} at {commit}")

    for round_id in range(start_round, args.max_rounds + 1):
        round_base = current_main_head(args.branch_main, args.owner, args.repo)
        if round_base != commit:
            log(
                f"round {round_id}: refreshing round base from {commit[:12]} "
                f"to current origin/{args.branch_main} {round_base[:12]}"
            )
        commit = round_base

        pre_round_refiner = run_refiner_for_open_issues(
            round_id=round_id,
            args=args,
            worktrees_root=worktrees_root,
            audit_dir=audit_dir,
            base_commit=commit,
            state=state,
        )
        if pre_round_refiner is not None:
            new_commit = current_main_head(args.branch_main, args.owner, args.repo)
            if new_commit == commit:
                state.final_commit = commit
                state.phase_status = "stuck"
                state.reason = "phase B: pre-round open-issue refiner made no progress"
                state.proof_status = classify_proofs_safely(commit, args.lean_file, args.owner, args.repo)
                state.append({"phase": "B", "round": round_id, "kind": "stuck", "reason": state.reason})
                return state
            log(
                f"round {round_id}: pre-round refiner advanced origin/{args.branch_main} "
                f"from {commit[:12]} to {new_commit[:12]}"
            )
            commit = new_commit

        log(f"round {round_id}: extracting Lean elaboration DAG at {commit[:12]}")
        try:
            dag = build_dag(commit, args.lean_file)
        except DagExtractionTimeout as exc:
            log(f"round {round_id}: {exc}; exiting without refiner dispatch")
            state.final_commit = commit
            state.phase_status = "stuck"
            state.reason = str(exc)
            state.proof_status = {}
            state.append(
                {
                    "phase": "B",
                    "round": round_id,
                    "kind": "dag_extraction_timeout",
                    "commit": commit,
                    "reason": state.reason,
                }
            )
            return state
        except DagExtractionBootstrapError as exc:
            log(f"round {round_id}: {exc}; exiting without refiner dispatch")
            state.final_commit = commit
            state.phase_status = "stuck"
            state.reason = str(exc)
            state.proof_status = {}
            state.append(
                {
                    "phase": "B",
                    "round": round_id,
                    "kind": "dag_extraction_bootstrap_failed",
                    "commit": commit,
                    "reason": state.reason,
                }
            )
            return state
        except Exception as exc:
            log(f"round {round_id}: Lean file did not compile before worker dispatch: {exc}")
            issue = ensure_compilation_issue(
                owner=args.owner,
                repo=args.repo,
                lean_file=args.lean_file,
                problem_file=args.problem_file,
                branch_main=args.branch_main,
                commit=commit,
            )
            state.append(
                {
                    "phase": "B",
                    "round": round_id,
                    "kind": "compile_check_failed",
                    "commit": commit,
                    "issue": issue,
                }
            )
            refiner_base = current_main_head(args.branch_main, args.owner, args.repo)
            if refiner_base != commit:
                log(
                    f"round {round_id}: origin/{args.branch_main} advanced during compile-failure handling "
                    f"from {commit[:12]} to {refiner_base[:12]}"
                )
            run_refiner_for_open_issues(
                round_id=round_id,
                args=args,
                worktrees_root=worktrees_root,
                audit_dir=audit_dir,
                base_commit=refiner_base,
                state=state,
                guaranteed_issues=[issue],
            )
            new_commit = current_main_head(args.branch_main, args.owner, args.repo)
            if new_commit == commit:
                state.final_commit = commit
                state.phase_status = "stuck"
                state.reason = "phase B: no progress after Lean compilation refiner"
                state.proof_status = classify_proofs_safely(commit, args.lean_file, args.owner, args.repo)
                state.append({"phase": "B", "round": round_id, "kind": "stuck", "reason": state.reason})
                return state
            commit = new_commit
            continue

        unproven = unproven_nodes(dag)
        if not unproven:
            state.final_commit = commit
            state.phase_status = "done"
            state.proof_status = classify_proofs(commit, args.lean_file, args.owner, args.repo)
            state.append({"phase": "B", "round": round_id, "kind": "done", "commit": commit})
            return state

        leaves = dynamic_leaves(dag)
        if not leaves:
            state.final_commit = commit
            state.phase_status = "stuck"
            state.reason = "phase B: unproven induced subgraph has no dynamic leaves"
            state.proof_status = classify_proofs_safely(commit, args.lean_file, args.owner, args.repo)
            state.append({"phase": "B", "round": round_id, "kind": "stuck", "reason": state.reason})
            return state

        ordered = leaves  # file order from verify_blueprint.parse_file
        log(
            f"round {round_id}: {len(unproven)} unproven proof nodes, "
            f"dispatching {len(ordered)} dynamic leaves"
        )

        handles = [
            preallocate_worker(
                round_id=round_id,
                target_node=node.name,
                owner=args.owner,
                repo=args.repo,
                worktrees_root=worktrees_root,
                lean_file=args.lean_file,
                problem_file=args.problem_file,
                base_commit=commit,
            )
            for node in ordered
        ]

        worker_runs: list[AgentRun] = []
        for index, group in enumerate(batch(handles, args.n), start=1):
            log(f"round {round_id}: launching worker batch {index} with {len(group)} jobs")
            worker_runs.extend(
                launch_agents(
                    group,
                    audit_dir=audit_dir / f"round-{round_id}",
                    poll_seconds=args.poll_seconds,
                    agent_resource=args.agent_resource,
                )
            )
        state.append(
            {
                "phase": "B",
                "round": round_id,
                "kind": "workers",
                "base_commit": commit,
                "items": [run.audit_record() for run in worker_runs],
            }
        )

        post_workers_commit = current_main_head(args.branch_main, args.owner, args.repo)
        if post_workers_commit != commit:
            log(
                f"round {round_id}: worker merges advanced origin/{args.branch_main} "
                f"from {commit[:12]} to {post_workers_commit[:12]}"
            )

        run_refiner_for_open_issues(
            round_id=round_id,
            args=args,
            worktrees_root=worktrees_root,
            audit_dir=audit_dir,
            base_commit=post_workers_commit,
            state=state,
        )

        new_commit = current_main_head(args.branch_main, args.owner, args.repo)
        if new_commit == commit:
            state.final_commit = commit
            state.phase_status = "stuck"
            state.reason = "phase B: no progress (main did not advance)"
            state.proof_status = classify_proofs_safely(commit, args.lean_file, args.owner, args.repo)
            state.append({"phase": "B", "round": round_id, "kind": "stuck", "reason": state.reason})
            return state
        commit = new_commit

    state.final_commit = commit
    state.proof_status = classify_proofs_safely(commit, args.lean_file, args.owner, args.repo)
    if state.proof_status and all(value == "proven" for value in state.proof_status.values()):
        state.phase_status = "done"
        state.reason = None
        state.append({"phase": "B", "kind": "done", "commit": commit})
    else:
        state.phase_status = "stuck"
        state.reason = f"max_rounds ({args.max_rounds}) exhausted"
        state.append({"phase": "B", "kind": "stuck", "reason": state.reason})
    return state


def default_audit_dir() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / ".orchestrator-runs" / f"worker-loop-{stamp}"


def target_orchestration_root(owner: str, repo: str) -> Path:
    return SOURCE_ROOT / ".orchestrator-repos" / branch_slug(owner) / branch_slug(repo)


def copy_path_fresh(source: Path, dest: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    if dest.exists() or dest.is_symlink():
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, dest)
    else:
        shutil.copy2(source, dest)


def source_relative_input_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        return path
    try:
        return path.resolve().relative_to(SOURCE_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"absolute input path {value!r} is outside the orchestration source root {SOURCE_ROOT}; "
            "pass a relative path or place the file under the source root"
        ) from exc


def copy_runtime_input_to_target(value: str, target_root: Path) -> str:
    if Path(value).is_absolute():
        if not Path(value).exists():
            raise FileNotFoundError(value)
        return value
    rel_path = source_relative_input_path(value)
    source = SOURCE_ROOT / rel_path
    if source.exists():
        copy_path_fresh(source, target_root / rel_path)
    return str(rel_path)


def prepare_target_orchestration_root(args: argparse.Namespace) -> Path:
    target_root = target_orchestration_root(args.owner, args.repo)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    expected_origin = target_repo_url(args.owner, args.repo)

    if not target_root.exists():
        log(f"creating per-target orchestration root at {target_root}")
        run_cmd(["git", "clone", expected_origin, str(target_root)], cwd=SOURCE_ROOT)
    elif not (target_root / ".git").exists():
        raise RuntimeError(f"target orchestration root exists but is not a git repo: {target_root}")

    run_cmd(["git", "-C", str(target_root), "remote", "set-url", "origin", expected_origin])
    run_cmd(["git", "-C", str(target_root), "fetch", "origin", args.branch_main])
    branch_check = run_cmd(
        ["git", "-C", str(target_root), "rev-parse", "--verify", args.branch_main],
        check=False,
    )
    if branch_check.returncode == 0:
        run_cmd(["git", "-C", str(target_root), "checkout", args.branch_main])
    else:
        run_cmd(["git", "-C", str(target_root), "checkout", "-b", args.branch_main, f"origin/{args.branch_main}"])
    run_cmd(["git", "-C", str(target_root), "pull", "--ff-only", "origin", args.branch_main])

    scripts_dir = target_root / ".scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_ROOT / ".scripts" / "per_node_worker_loop.py", scripts_dir / "per_node_worker_loop.py")
    shutil.copy2(SOURCE_ROOT / ".scripts" / "create-worktree.sh", scripts_dir / "create-worktree.sh")
    shutil.copy2(SOURCE_ROOT / ".scripts" / "verify_blueprint.py", scripts_dir / "verify_blueprint.py")

    copy_path_fresh(SOURCE_ROOT / "agents" / "Worker", target_root / "agents" / "Worker")
    copy_path_fresh(SOURCE_ROOT / "agents" / "Refiner", target_root / "agents" / "Refiner")
    copy_runtime_input_to_target(args.problem_file, target_root)
    copy_runtime_input_to_target(args.proof_file, target_root)
    return target_root


def remove_forwarded_option(items: list[str], option: str) -> list[str]:
    result: list[str] = []
    index = 0
    prefix = option + "="
    while index < len(items):
        item = items[index]
        if item == option:
            index += 2
            continue
        if item.startswith(prefix):
            index += 1
            continue
        result.append(item)
        index += 1
    return result


def set_forwarded_option(items: list[str], option: str, value: str) -> list[str]:
    result = remove_forwarded_option(items, option)
    result.extend([option, value])
    return result


def delegated_submit_self(args: argparse.Namespace) -> str | None:
    if target_origin_matches(args.owner, args.repo):
        return None

    target_root = prepare_target_orchestration_root(args)
    forwarded = list(sys.argv[1:])
    forwarded = set_forwarded_option(
        forwarded,
        "--problem-file",
        copy_runtime_input_to_target(args.problem_file, target_root),
    )
    forwarded = set_forwarded_option(
        forwarded,
        "--proof-file",
        copy_runtime_input_to_target(args.proof_file, target_root),
    )
    forwarded = set_forwarded_option(forwarded, "--worktrees-root", str(target_root / ".worktrees"))
    forwarded = remove_forwarded_option(forwarded, "--audit-dir")

    env = os.environ.copy()
    env["ORCHESTRATOR_SOURCE_ROOT"] = str(SOURCE_ROOT)
    env["ORCHESTRATOR_LEAN_PROJECT_ROOT"] = LEAN_PROJECT_ROOT_LABEL
    proc = subprocess.run(
        [PYTHON_BIN, str(target_root / ".scripts" / "per_node_worker_loop.py"), *forwarded],
        cwd=str(LEAN_PROJECT_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(
            f"delegated submit-self failed in {target_root} with exit {proc.returncode}"
        )
    for line in reversed(proc.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        job_id = payload.get("slurm_job_id")
        if isinstance(job_id, str):
            return job_id
    return ""


def submit_self(args: argparse.Namespace) -> str:
    delegated_job = delegated_submit_self(args)
    if delegated_job is not None:
        return delegated_job

    audit_dir = Path(args.audit_dir) if args.audit_dir else default_audit_dir()
    audit_dir.mkdir(parents=True, exist_ok=True)

    forwarded: list[str] = []
    for raw in sys.argv[1:]:
        if raw != "--submit-self":
            forwarded.append(raw)
    if "--audit-dir" not in forwarded:
        forwarded.extend(["--audit-dir", str(audit_dir)])

    script_path = audit_dir / "orchestrator.sbatch"
    command = " ".join([shlex.quote(sys.executable), shlex.quote(str(Path(__file__).resolve())), *map(shlex.quote, forwarded)])
    account = agent_slurm_account(ORCH_RESOURCE_MODE)
    account_line = account_directive(account)
    resource_directives = agent_resource_directives(ORCH_RESOURCE_MODE)
    env_exports = leanmarathon_env_exports()
    script = f"""#!/usr/bin/env bash
{account_line}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={ORCH_CPUS}
#SBATCH --mem-per-cpu={SLURM_MEM_PER_CPU}
{resource_directives}
#SBATCH --time={ORCH_TIME}
#SBATCH --job-name=leanmarathon-worker-loop
#SBATCH --output={shlex.quote(str(audit_dir / "orchestrator.out"))}
#SBATCH --error={shlex.quote(str(audit_dir / "orchestrator.err"))}

set -euo pipefail
export PATH={shlex.quote(ORCH_PATH)}
{env_exports}
{github_auth_bootstrap()}
export ORCHESTRATOR_SOURCE_ROOT={shlex.quote(str(SOURCE_ROOT))}
export ORCHESTRATOR_LEAN_PROJECT_ROOT={shlex.quote(LEAN_PROJECT_ROOT_LABEL)}
export ORCH_CPUS={ORCH_CPUS}
export ORCH_TIME={shlex.quote(ORCH_TIME)}
export ORCH_RESOURCE_MODE={shlex.quote(ORCH_RESOURCE_MODE)}
export AGENT_CPUS={AGENT_CPUS}
export AGENT_TIME={shlex.quote(AGENT_TIME)}
export AGENT_RESOURCE_MODE={shlex.quote(args.agent_resource)}
export LEANMARATHON_NUMERIC_TOOLS={shlex.quote(os.environ.get("LEANMARATHON_NUMERIC_TOOLS", ""))}
cd {shlex.quote(str(LEAN_PROJECT_ROOT))}
exec {command}
"""
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)
    job_id = submit_job(script_path)
    print(json.dumps({"slurm_job_id": job_id, "audit_dir": str(audit_dir), "script": str(script_path)}))
    return job_id


def dry_run(args: argparse.Namespace) -> None:
    worktrees_root = Path(args.worktrees_root)
    validate_paths(args.branch_main, worktrees_root)
    commit = current_main_head(args.branch_main, args.owner, args.repo)
    dag = build_dag(commit, args.lean_file)
    payload = {
        "commit": commit,
        "unproven": [node.name for node in unproven_nodes(dag)],
        "dynamic_leaves": [node.name for node in dynamic_leaves(dag)],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch-main", default="main")
    parser.add_argument("--worktrees-root", default=str(REPO_ROOT / ".worktrees"))
    parser.add_argument("--lean-file", default="LeanMarathon/Main.lean")
    parser.add_argument("--problem-file", required=True)
    parser.add_argument("--proof-file", required=True)
    parser.add_argument("--n", type=int, required=True, help="maximum concurrent Workers")
    parser.add_argument("--max-rounds", type=int, required=True)
    parser.add_argument(
        "--start-round",
        default="auto",
        help="first round id for resumed runs; omit for audit-based auto resume",
    )
    parser.add_argument("--audit-dir")
    parser.add_argument("--poll-seconds", type=int, default=POLL_SECONDS)
    parser.add_argument(
        "--agent-resource",
        choices=("cpu", "gpu"),
        default=AGENT_RESOURCE_MODE,
        help="Slurm resource mode for worker/refiner jobs; gpu requests one A100",
    )
    parser.add_argument("--submit-self", action="store_true", help="submit the orchestrator itself as a Slurm job")
    parser.add_argument("--dry-run", action="store_true", help="only extract the current DAG frontier")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.submit_self:
        submit_self(args)
        return 0
    if args.dry_run:
        dry_run(args)
        return 0
    state = per_node_loop(args)
    state.write_result()
    print(json.dumps(json.loads(state.result_path.read_text(encoding="utf-8")), indent=2, sort_keys=True))
    return 0 if state.phase_status == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
