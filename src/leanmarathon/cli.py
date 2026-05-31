from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


SYSTEM_ROOT = Path(__file__).resolve().parents[2]
LOCAL_CONFIG_PATH = Path(
    os.environ.get("LEANMARATHON_CONFIG", str(SYSTEM_ROOT / ".leanmarathon.local.toml"))
).expanduser()


def load_local_config() -> dict[str, Any]:
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    with LOCAL_CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


LOCAL_CONFIG = load_local_config()


def local_cfg(path: tuple[str, ...], default: Any = "") -> Any:
    current: Any = LOCAL_CONFIG
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def env_or_cfg(env_name: str, path: tuple[str, ...], default: str = "") -> str:
    value = os.environ.get(env_name)
    if value is not None:
        return value
    configured = local_cfg(path, default)
    return "" if configured is None else str(configured)


LOCAL_VENV_BIN = env_or_cfg("LEANMARATHON_VENV_BIN", ("paths", "venv_bin"), str(SYSTEM_ROOT / ".venv" / "bin"))
LOCAL_NODE_BIN = env_or_cfg("LEANMARATHON_NODE_BIN", ("paths", "node_bin"))
LOCAL_ELAN_BIN = env_or_cfg("LEANMARATHON_ELAN_BIN", ("paths", "elan_bin"))
LOCAL_AGENT_PATH = env_or_cfg("LEANMARATHON_AGENT_PATH", ("paths", "agent_path"))
LOCAL_ORCH_PATH = env_or_cfg("LEANMARATHON_ORCH_PATH", ("paths", "orchestrator_path"))
LOCAL_SLURM_CPU_ACCOUNT = env_or_cfg("LEANMARATHON_SLURM_CPU_ACCOUNT", ("slurm", "cpu_account"))
LOCAL_SLURM_GPU_ACCOUNT = env_or_cfg("LEANMARATHON_SLURM_GPU_ACCOUNT", ("slurm", "gpu_account"))
LOCAL_SLURM_GPU_PARTITION = env_or_cfg("LEANMARATHON_SLURM_GPU_PARTITION", ("slurm", "gpu_partition"), "gpu")
LOCAL_SLURM_GPU_GRES = env_or_cfg("LEANMARATHON_SLURM_GPU_GRES", ("slurm", "gpu_gres"), "gpu:lovelace_l40:1")
LOCAL_SLURM_MEM_PER_CPU = env_or_cfg("LEANMARATHON_SLURM_MEM_PER_CPU", ("slurm", "mem_per_cpu"), "3850")
LOCAL_LEAN_PROJECT_ROOT = env_or_cfg("LEANMARATHON_LEAN_PROJECT_ROOT", ("lean", "project_root"))
DEFAULT_LEAN_PROJECT_ROOT = Path(LOCAL_LEAN_PROJECT_ROOT).expanduser().resolve() if LOCAL_LEAN_PROJECT_ROOT else None
DEFAULT_PATH = os.pathsep.join(
    item
    for item in [
        LOCAL_VENV_BIN,
        LOCAL_NODE_BIN,
        LOCAL_ELAN_BIN,
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    if item
)
REQUIRED_TOOL_VERSIONS = {
    "codex": "0.128.0",
    "lean-explore": "1.2.1",
    "lean-lsp-mcp": "0.26.2",
    "github-mcp-server": "0.32.0",
    "git-mcp-server": "2.10.5",
}
NUMERIC_TOOL_IMPORTS = [
    "numpy",
    "scipy",
    "sympy",
    "numba",
    "torch",
    "mpmath",
    "pandas",
    "matplotlib",
    "networkx",
    "pulp",
    "ortools",
    "highspy",
    "pysat",
    "cvxpy",
    "osqp",
    "clarabel",
    "sklearn",
    "faiss",
]
PDF_TOOL_IMPORTS = ["pdfplumber", "fitz", "pdfminer.high_level", "pypdf", "PyPDF2", "pypdfium2"]


def run(
    args: list[str],
    *,
    cwd: Path = SYSTEM_ROOT,
    env: dict[str, str] | None = None,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env["PATH"] = DEFAULT_PATH + (":" + merged_env["PATH"] if merged_env.get("PATH") else "")
    if env:
        merged_env.update(env)
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            env=merged_env,
            text=True,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        proc = subprocess.CompletedProcess(args=args, returncode=127, stdout="", stderr=str(exc))
    if check and proc.returncode != 0:
        rendered = " ".join(args)
        raise SystemExit(
            f"command failed ({proc.returncode}): {rendered}\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )
    return proc


def log(message: str) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[LeanMarathon {now}] {message}", flush=True)


def repo_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}.git"


def target_root(owner: str, repo: str) -> Path:
    return SYSTEM_ROOT / ".orchestrator-repos" / owner / repo


def target_state_root(owner: str, repo: str) -> Path:
    return SYSTEM_ROOT / ".leanmarathon-targets" / owner / repo


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


def remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def rel_to_source(path: Path, source_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(source_root.resolve()))
    except ValueError:
        return path.name


def default_runtime_proof_path(proof_file: Path) -> str:
    if proof_file.is_dir():
        return "inputs/proof"
    return f"inputs/proof/{proof_file.name}"


def write_text_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def write_target_gitignore(root: Path) -> None:
    write_text_if_changed(
        root / ".gitignore",
        "\n".join(
            [
                "# Ignore everything by default.",
                "*",
                "",
                "# Lean project files.",
                "!.gitignore",
                "!lakefile.toml",
                "!lake-manifest.json",
                "!lean-toolchain",
                "!LeanMarathon/",
                "!LeanMarathon/**",
                "# CI.",
                "!.github/",
                "!.github/workflows/",
                "!.github/workflows/verify-blueprint.yml",
                "!.github/workflows/warmup-cache.yml",
                "",
            ]
        ),
    )


def write_base_lean(root: Path, lean_file: str) -> None:
    write_text_if_changed(
        root / lean_file,
        "\n".join(
            [
                "import Mathlib",
                "import Architect",
                "",
                "set_option linter.all false",
                "set_option maxHeartbeats 500000",
                "",
            ]
        ),
    )


def toml_quote(value: str) -> str:
    return json.dumps(value)


def toml_string_list(values: list[str]) -> str:
    return "[" + ", ".join(toml_quote(value) for value in values) + "]"


def normalize_repeated(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for item in raw.split(","):
            value = item.strip()
            if value and value not in seen:
                seen.add(value)
                out.append(value)
    return out


def detect_importable_numeric_tools() -> list[str]:
    detected: list[str] = []
    for module in NUMERIC_TOOL_IMPORTS:
        try:
            if importlib.util.find_spec(module) is not None:
                detected.append(module)
        except (ImportError, ModuleNotFoundError, ValueError):
            continue
    return detected


def write_project_config(
    root: Path,
    *,
    owner: str,
    repo: str,
    lean_file: str,
    problem_file: str,
    proof_file: str,
    auto_resource: str,
    auto_cpus: int,
    auto_time: str,
    stage1_orchestrator_resource: str,
    stage1_orchestrator_cpus: int,
    stage1_orchestrator_time: str,
    orchestrator_resource: str,
    orchestrator_cpus: int,
    orchestrator_time: str,
    agent_resource: str,
    agent_cpus: int,
    agent_time: str,
    batch_size: int,
    max_rounds: int,
    max_review_rounds: int,
    lean_project_root: Path,
    numeric_tools: list[str],
) -> None:
    write_text_if_changed(
        root / "config.toml",
        "\n".join(
            [
                "[github]",
                f"owner = {toml_quote(owner)}",
                f"repo = {toml_quote(repo)}",
                'branch_main = "main"',
                "",
                "[project]",
                f"lean_file = {toml_quote(lean_file)}",
                f"problem_file = {toml_quote(problem_file)}",
                f"proof_file = {toml_quote(proof_file)}",
                f"lean_project_root = {toml_quote(str(lean_project_root))}",
                "",
                "[hpc.auto]",
                f"resource = {toml_quote(auto_resource)}",
                f"cpus = {auto_cpus}",
                f"time = {toml_quote(auto_time)}",
                "",
                "[hpc.stage1_orchestrator]",
                f"resource = {toml_quote(stage1_orchestrator_resource)}",
                f"cpus = {stage1_orchestrator_cpus}",
                f"time = {toml_quote(stage1_orchestrator_time)}",
                "",
                "[hpc.stage2_orchestrator]",
                f"resource = {toml_quote(orchestrator_resource)}",
                f"cpus = {orchestrator_cpus}",
                f"time = {toml_quote(orchestrator_time)}",
                "",
                "[hpc.agent]",
                f"resource = {toml_quote(agent_resource)}",
                f"cpus = {agent_cpus}",
                f"time = {toml_quote(agent_time)}",
                f"batch_size = {batch_size}",
                "",
                "[stage1]",
                f"max_review_rounds = {max_review_rounds}",
                "",
                "[stage2]",
                f"max_rounds = {max_rounds}",
                "",
                "[capabilities]",
                f"numeric_tools = {toml_string_list(numeric_tools)}",
                "",
            ]
        ),
    )


def load_config(root: Path) -> dict[str, Any]:
    path = root / "config.toml"
    if not path.exists():
        legacy = root / ".leanmarathon" / "config.toml"
        if legacy.exists():
            path = legacy
    if not path.exists():
        raise SystemExit(f"missing LeanMarathon config: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_target_config(owner: str, repo: str) -> dict[str, Any]:
    state_path = target_state_root(owner, repo)
    if (state_path / "config.toml").exists():
        return load_config(state_path)
    return load_config(target_root(owner, repo))


def cfg_get(config: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    current: Any = config
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def ensure_github_repo(owner: str, repo: str, private: bool) -> None:
    view = run(["gh", "repo", "view", f"{owner}/{repo}", "--json", "nameWithOwner"], check=False)
    if view.returncode == 0:
        log(f"GitHub repo exists: {owner}/{repo}")
        return
    visibility = "--private" if private else "--public"
    log(f"creating GitHub repo {owner}/{repo}")
    run(["gh", "repo", "create", f"{owner}/{repo}", visibility])


def ensure_target_clone(owner: str, repo: str) -> Path:
    root = target_root(owner, repo)
    root.parent.mkdir(parents=True, exist_ok=True)
    expected = repo_url(owner, repo)
    if root.exists() and (root / ".git").exists():
        run(["git", "remote", "set-url", "origin", expected], cwd=root)
        run(["git", "fetch", "origin"], cwd=root, check=False)
        return root
    if root.exists():
        raise SystemExit(f"target root exists but is not a git repo: {root}")
    run(["git", "clone", expected, str(root)], cwd=SYSTEM_ROOT)
    return root


def copy_core_project_files(root: Path, lean_project_root: Path) -> None:
    for name in ("lakefile.toml", "lake-manifest.json", "lean-toolchain"):
        copy_path_fresh(lean_project_root / name, root / name)
    workflows = root / ".github" / "workflows"
    copy_path_fresh(SYSTEM_ROOT / "workflows" / "verify-blueprint.yml", workflows / "verify-blueprint.yml")
    copy_path_fresh(SYSTEM_ROOT / "workflows" / "warmup-cache.yml", workflows / "warmup-cache.yml")


def commit_and_push_initial(root: Path) -> None:
    run(["git", "checkout", "-B", "main"], cwd=root)
    ensure_git_identity(root)
    run(["git", "add", "."], cwd=root)
    status = run(["git", "status", "--porcelain"], cwd=root).stdout.strip()
    if status:
        run(["git", "commit", "-m", "Initialize LeanMarathon target"], cwd=root)
    else:
        log("target repo has no initialization changes to commit")
    run(["git", "push", "-u", "origin", "main"], cwd=root)


def ensure_git_identity(root: Path) -> None:
    name = run(["git", "config", "user.name"], cwd=root, check=False).stdout.strip()
    email = run(["git", "config", "user.email"], cwd=root, check=False).stdout.strip()
    if not name:
        run(["git", "config", "user.name", "LeanMarathon"], cwd=root)
    if not email:
        run(["git", "config", "user.email", "leanmarathon@example.invalid"], cwd=root)


def command_init(args: argparse.Namespace) -> int:
    owner = args.owner
    repo = args.repo
    if not args.lean_project_root:
        raise SystemExit("--lean-project-root is required unless lean.project_root is set in .leanmarathon.local.toml")
    lean_project_root = Path(args.lean_project_root).expanduser().resolve()
    if not lean_project_root.is_dir():
        raise SystemExit(f"Lean project root does not exist: {lean_project_root}")
    for name in ("lakefile.toml", "lake-manifest.json", "lean-toolchain"):
        if not (lean_project_root / name).exists():
            raise SystemExit(f"Lean project root is missing {name}: {lean_project_root}")
    problem_src = Path(args.problem_file).expanduser().resolve()
    proof_src = Path(args.proof_file).expanduser().resolve()
    if not problem_src.exists():
        raise SystemExit(f"problem file does not exist: {problem_src}")
    if not proof_src.exists():
        raise SystemExit(f"proof file/path does not exist: {proof_src}")
    ensure_github_repo(owner, repo, private=not args.public)
    root = ensure_target_clone(owner, repo)

    state_root = target_state_root(owner, repo)
    state_root.mkdir(parents=True, exist_ok=True)
    target_problem = args.target_problem_file or "inputs/problem.txt"
    target_proof = args.target_proof_file or default_runtime_proof_path(proof_src)
    numeric_tools = detect_importable_numeric_tools()

    copy_core_project_files(root, lean_project_root)
    write_target_gitignore(root)
    remove_path(root / "source")
    remove_path(root / ".leanmarathon")
    write_base_lean(root, args.lean_file)
    runtime_problem = (state_root / target_problem).resolve()
    runtime_proof = (state_root / target_proof).resolve()
    copy_path_fresh(problem_src, runtime_problem)
    copy_path_fresh(proof_src, runtime_proof)
    write_project_config(
        state_root,
        owner=owner,
        repo=repo,
        lean_file=args.lean_file,
        problem_file=str(runtime_problem),
        proof_file=str(runtime_proof),
        auto_resource=args.auto_resource,
        auto_cpus=args.auto_cpus,
        auto_time=args.auto_time,
        stage1_orchestrator_resource=args.stage1_orchestrator_resource,
        stage1_orchestrator_cpus=args.stage1_orchestrator_cpus,
        stage1_orchestrator_time=args.stage1_orchestrator_time,
        orchestrator_resource=args.orchestrator_resource,
        orchestrator_cpus=args.orchestrator_cpus,
        orchestrator_time=args.orchestrator_time,
        agent_resource=args.agent_resource,
        agent_cpus=args.agent_cpus,
        agent_time=args.agent_time,
        batch_size=args.batch_size,
        max_rounds=args.max_rounds,
        max_review_rounds=args.max_review_rounds,
        lean_project_root=lean_project_root,
        numeric_tools=numeric_tools,
    )
    commit_and_push_initial(root)
    print(root)
    return 0


def stage_orchestrator_values(config: dict[str, Any], stage: str) -> tuple[str, str, str]:
    if stage == "stage1":
        section = "stage1_orchestrator"
        fallback = {"resource": "cpu", "cpus": 1, "time": "48:00:00"}
    elif stage == "stage2":
        section = "stage2_orchestrator"
        fallback = {
            "resource": cfg_get(config, ("hpc", "orchestrator", "resource"), "cpu"),
            "cpus": cfg_get(config, ("hpc", "orchestrator", "cpus"), 8),
            "time": cfg_get(config, ("hpc", "orchestrator", "time"), "48:00:00"),
        }
    else:
        raise ValueError(f"unknown stage: {stage}")
    return (
        str(cfg_get(config, ("hpc", section, "resource"), fallback["resource"])),
        str(cfg_get(config, ("hpc", section, "cpus"), fallback["cpus"])),
        str(cfg_get(config, ("hpc", section, "time"), fallback["time"])),
    )


def runtime_env(config: dict[str, Any]) -> dict[str, str]:
    lean_project_root = cfg_get(config, ("project", "lean_project_root"), None)
    if not lean_project_root:
        if DEFAULT_LEAN_PROJECT_ROOT is None:
            raise SystemExit("missing project.lean_project_root in LeanMarathon target config")
        lean_project_root = str(DEFAULT_LEAN_PROJECT_ROOT)
    numeric_tools = cfg_get(config, ("capabilities", "numeric_tools"), [])
    return {
        "ORCHESTRATOR_SOURCE_ROOT": str(SYSTEM_ROOT),
        "ORCHESTRATOR_LEAN_PROJECT_ROOT": lean_project_root,
        "LEANMARATHON_VENV_BIN": LOCAL_VENV_BIN,
        "LEANMARATHON_NODE_BIN": LOCAL_NODE_BIN,
        "LEANMARATHON_ELAN_BIN": LOCAL_ELAN_BIN,
        "LEANMARATHON_SLURM_CPU_ACCOUNT": LOCAL_SLURM_CPU_ACCOUNT,
        "LEANMARATHON_SLURM_GPU_ACCOUNT": LOCAL_SLURM_GPU_ACCOUNT,
        "LEANMARATHON_SLURM_GPU_PARTITION": LOCAL_SLURM_GPU_PARTITION,
        "LEANMARATHON_SLURM_GPU_GRES": LOCAL_SLURM_GPU_GRES,
        "LEANMARATHON_SLURM_MEM_PER_CPU": LOCAL_SLURM_MEM_PER_CPU,
        "LEANMARATHON_NUMERIC_TOOLS": ",".join(str(item) for item in numeric_tools),
    }


def orchestrator_env(config: dict[str, Any], *, stage: str = "stage2") -> dict[str, str]:
    orch_resource, orch_cpus, orch_time = stage_orchestrator_values(config, stage)
    env = {
        **runtime_env(config),
        "ORCH_RESOURCE_MODE": orch_resource,
        "ORCH_CPUS": orch_cpus,
        "ORCH_TIME": orch_time,
        "AGENT_RESOURCE_MODE": str(cfg_get(config, ("hpc", "agent", "resource"), "cpu")),
        "AGENT_CPUS": str(cfg_get(config, ("hpc", "agent", "cpus"), 16)),
        "AGENT_TIME": str(cfg_get(config, ("hpc", "agent", "time"), "4:00:00")),
    }
    if LOCAL_AGENT_PATH:
        env["LEANMARATHON_AGENT_PATH"] = LOCAL_AGENT_PATH
    if LOCAL_ORCH_PATH:
        env["LEANMARATHON_ORCH_PATH"] = LOCAL_ORCH_PATH
    return env


def slurm_account(resource: str) -> str:
    if resource == "cpu":
        return LOCAL_SLURM_CPU_ACCOUNT
    if resource == "gpu":
        return LOCAL_SLURM_GPU_ACCOUNT
    raise SystemExit(f"unknown Slurm resource mode: {resource}")


def slurm_resource_directives(resource: str) -> list[str]:
    if resource == "cpu":
        return []
    if resource == "gpu":
        partition = LOCAL_SLURM_GPU_PARTITION
        gres = LOCAL_SLURM_GPU_GRES
        return [f"#SBATCH --partition={partition}", f"#SBATCH --gres={gres}"]
    raise SystemExit(f"unknown Slurm resource mode: {resource}")


def shell_quote_env(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def github_auth_bootstrap_script() -> str:
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


def auto_forward_args(args: argparse.Namespace, *, submit: bool) -> list[str]:
    forwarded = ["auto", "--owner", args.owner, "--repo", args.repo]
    forwarded.append("--submit" if submit else "--no-submit")
    if args.max_review_rounds is not None:
        forwarded.extend(["--max-review-rounds", str(args.max_review_rounds)])
    if args.max_rounds is not None:
        forwarded.extend(["--max-rounds", str(args.max_rounds)])
    if args.start_review_round != 1:
        forwarded.extend(["--start-review-round", str(args.start_review_round)])
    if args.start_round is not None:
        forwarded.extend(["--start-round", str(args.start_round)])
    if args.n is not None:
        forwarded.extend(["--n", str(args.n)])
    if args.agent_resource is not None:
        forwarded.extend(["--agent-resource", args.agent_resource])
    if args.skip_blueprinter:
        forwarded.append("--skip-blueprinter")
    return forwarded


def submit_auto_job(args: argparse.Namespace, config: dict[str, Any]) -> int:
    env = runtime_env(config)
    resource = str(cfg_get(config, ("hpc", "auto", "resource"), "cpu"))
    account = slurm_account(resource)
    account_line = f"#SBATCH --account={account}" if account else ""
    resource_lines = "\n".join(slurm_resource_directives(resource))
    cpus = str(cfg_get(config, ("hpc", "auto", "cpus"), 1))
    time_limit = str(cfg_get(config, ("hpc", "auto", "time"), "48:00:00"))
    mem_per_cpu = LOCAL_SLURM_MEM_PER_CPU

    root = target_root(args.owner, args.repo)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    audit_dir = root / ".orchestrator-runs" / f"auto-{timestamp}"
    audit_dir.mkdir(parents=True, exist_ok=True)
    script = audit_dir / "auto.sbatch"
    command = [str(Path(LOCAL_VENV_BIN) / "leanmarathon"), *auto_forward_args(args, submit=False)]
    command_text = " ".join(shell_quote_env(item) for item in command)

    exports = []
    for key, value in env.items():
        exports.append(f"export {key}={shell_quote_env(str(value))}")
    for key, value in sorted(os.environ.items()):
        if key.startswith("LEANMARATHON_"):
            exports.append(f"export {key}={shell_quote_env(value)}")

    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                account_line,
                "#SBATCH --nodes=1",
                "#SBATCH --ntasks=1",
                f"#SBATCH --cpus-per-task={cpus}",
                f"#SBATCH --mem-per-cpu={mem_per_cpu}",
                resource_lines,
                f"#SBATCH --time={time_limit}",
                "#SBATCH --job-name=leanmarathon-auto",
                f"#SBATCH --output={audit_dir / 'auto.out'}",
                f"#SBATCH --error={audit_dir / 'auto.err'}",
                "",
                "set -euo pipefail",
                *exports,
                f"export PATH={shell_quote_env(DEFAULT_PATH)}:$PATH",
                github_auth_bootstrap_script(),
                f"cd {shell_quote_env(str(SYSTEM_ROOT))}",
                f"exec {command_text}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    proc = run(["sbatch", "--parsable", str(script)], check=False)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr, end="")
        return proc.returncode
    job_id = proc.stdout.strip().split(";", 1)[0]
    print(json.dumps({"slurm_job_id": job_id, "audit_dir": str(audit_dir), "script": str(script)}))
    return 0


def command_auto(args: argparse.Namespace) -> int:
    config = load_target_config(args.owner, args.repo)
    if args.submit:
        return submit_auto_job(args, config)

    stage1_extra = [
        "--max-review-rounds",
        str(args.max_review_rounds or cfg_get(config, ("stage1", "max_review_rounds"), 20)),
        "--start-review-round",
        str(args.start_review_round),
        "--agent-resource",
        str(args.agent_resource or cfg_get(config, ("hpc", "agent", "resource"), "cpu")),
    ]
    if args.skip_blueprinter:
        stage1_extra.append("--skip-blueprinter")
    rc = submit_stage_and_wait(
        owner=args.owner,
        repo=args.repo,
        script_name="stage1_blueprint_loop.py",
        extra_args=stage1_extra,
    )
    if rc != 0:
        return rc

    stage2_extra = [
        "--n",
        str(args.n or cfg_get(config, ("hpc", "agent", "batch_size"), 16)),
        "--max-rounds",
        str(args.max_rounds or cfg_get(config, ("stage2", "max_rounds"), 100)),
        "--agent-resource",
        str(args.agent_resource or cfg_get(config, ("hpc", "agent", "resource"), "cpu")),
    ]
    if args.start_round is not None:
        stage2_extra.extend(["--start-round", str(args.start_round)])
    return submit_stage_and_wait(
        owner=args.owner,
        repo=args.repo,
        script_name="per_node_worker_loop.py",
        extra_args=stage2_extra,
    )


def run_script_from_config(
    *,
    owner: str,
    repo: str,
    script_name: str,
    extra_args: list[str],
    submit: bool,
) -> int:
    command, env = script_command_from_config(
        owner=owner,
        repo=repo,
        script_name=script_name,
        extra_args=extra_args,
        submit=submit,
    )
    proc = run(command, cwd=SYSTEM_ROOT, env=env, check=False)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode


def script_command_from_config(
    *,
    owner: str,
    repo: str,
    script_name: str,
    extra_args: list[str],
    submit: bool,
) -> tuple[list[str], dict[str, str]]:
    config = load_target_config(owner, repo)
    project = config["project"]
    stage = "stage1" if script_name == "stage1_blueprint_loop.py" else "stage2"
    command = [
        sys.executable,
        str(SYSTEM_ROOT / ".scripts" / script_name),
        "--owner",
        owner,
        "--repo",
        repo,
        "--lean-file",
        str(project["lean_file"]),
        "--problem-file",
        str(project["problem_file"]),
        "--proof-file",
        str(project["proof_file"]),
        *extra_args,
    ]
    if submit:
        command.append("--submit-self")
    return command, orchestrator_env(config, stage=stage)


def parse_slurm_job_id(text: str) -> str:
    for line in reversed(text.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        job_id = payload.get("slurm_job_id")
        if isinstance(job_id, str) and job_id:
            return job_id
    return ""


def slurm_job_state(job_id: str) -> tuple[str | None, str | None]:
    squeue = run(["squeue", "-j", job_id, "-h", "-o", "%T"], check=False)
    if squeue.returncode == 0 and squeue.stdout.strip():
        return squeue.stdout.strip().splitlines()[0], None
    sacct = run(["sacct", "-j", job_id, "--format=JobID,State,ExitCode", "-n", "-P"], check=False)
    if sacct.returncode == 0:
        for line in sacct.stdout.splitlines():
            parts = line.split("|")
            if len(parts) >= 3 and parts[0] == job_id:
                return parts[1].split()[0], parts[2]
    return None, None


def wait_for_slurm_job(job_id: str) -> int:
    terminal = {
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
    while True:
        state, exit_code = slurm_job_state(job_id)
        if state in terminal:
            print(f"Slurm job {job_id} ended with state={state} exit={exit_code}")
            return 0 if state == "COMPLETED" and (exit_code in (None, "0:0")) else 1
        log(f"waiting for Slurm job {job_id}")
        import time

        time.sleep(120)


def submit_stage_and_wait(
    *,
    owner: str,
    repo: str,
    script_name: str,
    extra_args: list[str],
) -> int:
    command, env = script_command_from_config(
        owner=owner,
        repo=repo,
        script_name=script_name,
        extra_args=extra_args,
        submit=True,
    )
    proc = run(command, cwd=SYSTEM_ROOT, env=env, check=False)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if proc.returncode != 0:
        return proc.returncode
    job_id = parse_slurm_job_id(proc.stdout)
    if not job_id:
        print("could not find slurm_job_id in stage submission output", file=sys.stderr)
        return 1
    return wait_for_slurm_job(job_id)


def command_stage1_run(args: argparse.Namespace) -> int:
    config = load_target_config(args.owner, args.repo)
    extra = [
        "--max-review-rounds",
        str(args.max_review_rounds or cfg_get(config, ("stage1", "max_review_rounds"), 20)),
        "--start-review-round",
        str(args.start_review_round),
        "--agent-resource",
        str(args.agent_resource or cfg_get(config, ("hpc", "agent", "resource"), "cpu")),
    ]
    if args.skip_blueprinter:
        extra.append("--skip-blueprinter")
    return run_script_from_config(
        owner=args.owner,
        repo=args.repo,
        script_name="stage1_blueprint_loop.py",
        extra_args=extra,
        submit=args.submit,
    )


def command_stage2_run(args: argparse.Namespace) -> int:
    config = load_target_config(args.owner, args.repo)
    extra = [
        "--n",
        str(args.n or cfg_get(config, ("hpc", "agent", "batch_size"), 16)),
        "--max-rounds",
        str(args.max_rounds or cfg_get(config, ("stage2", "max_rounds"), 100)),
        "--agent-resource",
        str(args.agent_resource or cfg_get(config, ("hpc", "agent", "resource"), "cpu")),
    ]
    if args.start_round is not None:
        extra.extend(["--start-round", str(args.start_round)])
    return run_script_from_config(
        owner=args.owner,
        repo=args.repo,
        script_name="per_node_worker_loop.py",
        extra_args=extra,
        submit=args.submit,
    )


def command_status(args: argparse.Namespace) -> int:
    root = target_root(args.owner, args.repo)
    print(f"target_root: {root}")
    for state in ("open",):
        issues = run(["gh", "issue", "list", "--repo", f"{args.owner}/{args.repo}", "--state", state, "--limit", "50"], check=False)
        print(f"\nopen issues:\n{issues.stdout}", end="")
    prs = run(["gh", "pr", "list", "--repo", f"{args.owner}/{args.repo}", "--state", "open", "--limit", "50"], check=False)
    print(f"\nopen PRs:\n{prs.stdout}", end="")
    runs = sorted((root / ".orchestrator-runs").glob("*")) if (root / ".orchestrator-runs").exists() else []
    if runs:
        print(f"\nlatest run: {runs[-1]}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    checks = [
        ("gh", ["gh", "auth", "status"]),
        ("git", ["git", "--version"]),
        ("sbatch", ["sbatch", "--version"]),
        ("codex", ["codex", "--version"]),
        ("lake", ["lake", "--version"]),
        ("lean-explore", ["lean-explore", "--help"]),
        ("lean-lsp-mcp", ["lean-lsp-mcp", "--version"]),
        ("github-mcp-server", ["github-mcp-server", "--version"]),
    ]
    ok = True
    for name, command in checks:
        proc = run(command, check=False)
        expected = REQUIRED_TOOL_VERSIONS.get(name)
        status = "ok" if proc.returncode == 0 else "failed"
        suffix = f" (expected {expected})" if expected else ""
        print(f"{name}: {status}{suffix}")
        if proc.returncode != 0:
            ok = False
            if proc.stderr:
                print(proc.stderr.strip())
    git_mcp = shutil.which("git-mcp-server", path=DEFAULT_PATH + os.pathsep + os.environ.get("PATH", ""))
    print(f"git-mcp-server: {'ok' if git_mcp else 'failed'} (expected {REQUIRED_TOOL_VERSIONS['git-mcp-server']})")
    if not git_mcp:
        ok = False

    if args.owner and args.repo:
        config = load_target_config(args.owner, args.repo)
        configured_numeric = [str(item) for item in cfg_get(config, ("capabilities", "numeric_tools"), [])]
    else:
        configured_numeric = []

    numeric_tools = configured_numeric or detect_importable_numeric_tools()
    for module in numeric_tools:
        proc = run(
            [
                sys.executable,
                "-c",
                f"import importlib; importlib.import_module({module!r})",
            ],
            check=False,
        )
        status = "ok" if proc.returncode == 0 else "missing"
        print(f"optional numeric tool {module}: {status}")
        if proc.returncode != 0:
            print(f"warning: {module} is listed for this target but is not importable")

    for module in PDF_TOOL_IMPORTS:
        proc = run(
            [
                sys.executable,
                "-c",
                f"import importlib; importlib.import_module({module!r})",
            ],
            check=False,
        )
        status = "ok" if proc.returncode == 0 else "missing"
        print(f"required pdf tool {module}: {status}")
        if proc.returncode != 0:
            ok = False
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="leanmarathon")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create and initialize a LeanMarathon target repo")
    init.add_argument("--owner", required=True)
    init.add_argument("--repo", required=True)
    init.add_argument("--problem-file", required=True)
    init.add_argument("--proof-file", required=True)
    init.add_argument("--target-problem-file")
    init.add_argument("--target-proof-file")
    init.add_argument("--lean-file", default="LeanMarathon/Main.lean")
    init.add_argument(
        "--lean-project-root",
        default=str(DEFAULT_LEAN_PROJECT_ROOT) if DEFAULT_LEAN_PROJECT_ROOT is not None else None,
        required=DEFAULT_LEAN_PROJECT_ROOT is None,
        help="absolute path to the user's Lean project root containing lakefile.toml",
    )
    init.add_argument("--public", action="store_true")
    init.add_argument("--auto-resource", choices=("cpu", "gpu"), default="cpu")
    init.add_argument("--auto-cpus", type=int, default=1)
    init.add_argument("--auto-time", default="48:00:00")
    init.add_argument("--stage1-orchestrator-resource", choices=("cpu", "gpu"), default="cpu")
    init.add_argument("--stage1-orchestrator-cpus", type=int, default=1)
    init.add_argument("--stage1-orchestrator-time", default="48:00:00")
    init.add_argument("--orchestrator-resource", choices=("cpu", "gpu"), default="gpu")
    init.add_argument("--orchestrator-cpus", type=int, default=42)
    init.add_argument("--orchestrator-time", default="48:00:00")
    init.add_argument("--agent-resource", choices=("cpu", "gpu"), default="gpu")
    init.add_argument("--agent-cpus", type=int, default=42)
    init.add_argument("--agent-time", default="4:00:00")
    init.add_argument("--batch-size", type=int, default=16)
    init.add_argument("--max-rounds", type=int, default=100)
    init.add_argument("--max-review-rounds", type=int, default=20)
    init.set_defaults(func=command_init)

    stage1 = sub.add_parser("stage1", help="Stage 1 commands")
    stage1_sub = stage1.add_subparsers(dest="stage1_command", required=True)
    stage1_run = stage1_sub.add_parser("run", help="run Blueprinter / Target-Reviewer / Refiner loop")
    stage1_run.add_argument("--owner", required=True)
    stage1_run.add_argument("--repo", required=True)
    stage1_run.add_argument("--max-review-rounds", type=int)
    stage1_run.add_argument("--start-review-round", type=int, default=1)
    stage1_run.add_argument("--skip-blueprinter", action="store_true")
    stage1_run.add_argument("--agent-resource", choices=("cpu", "gpu"))
    stage1_run.add_argument("--submit", action="store_true", default=True)
    stage1_run.add_argument("--no-submit", dest="submit", action="store_false")
    stage1_run.set_defaults(func=command_stage1_run)

    stage2 = sub.add_parser("stage2", help="Stage 2 commands")
    stage2_sub = stage2.add_subparsers(dest="stage2_command", required=True)
    stage2_run = stage2_sub.add_parser("run", help="run Worker / Refiner loop")
    stage2_run.add_argument("--owner", required=True)
    stage2_run.add_argument("--repo", required=True)
    stage2_run.add_argument("--n", type=int)
    stage2_run.add_argument("--max-rounds", type=int)
    stage2_run.add_argument("--start-round", type=int)
    stage2_run.add_argument("--agent-resource", choices=("cpu", "gpu"))
    stage2_run.add_argument("--submit", action="store_true", default=True)
    stage2_run.add_argument("--no-submit", dest="submit", action="store_false")
    stage2_run.set_defaults(func=command_stage2_run)

    auto = sub.add_parser("auto", help="run Stage 1 then Stage 2 end to end")
    auto.add_argument("--owner", required=True)
    auto.add_argument("--repo", required=True)
    auto.add_argument("--max-review-rounds", type=int)
    auto.add_argument("--max-rounds", type=int)
    auto.add_argument("--start-review-round", type=int, default=1)
    auto.add_argument("--start-round", type=int)
    auto.add_argument("--n", type=int)
    auto.add_argument("--skip-blueprinter", action="store_true")
    auto.add_argument("--agent-resource", choices=("cpu", "gpu"))
    auto.add_argument("--submit", dest="submit", action="store_true", default=True)
    auto.add_argument("--no-submit", dest="submit", action="store_false")
    auto.set_defaults(func=command_auto)

    status = sub.add_parser("status", help="show repo status")
    status.add_argument("--owner", required=True)
    status.add_argument("--repo", required=True)
    status.set_defaults(func=command_status)

    doctor = sub.add_parser("doctor", help="check local dependencies")
    doctor.add_argument("--owner")
    doctor.add_argument("--repo")
    doctor.set_defaults(func=command_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
