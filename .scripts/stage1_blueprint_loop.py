#!/usr/bin/env python3
"""Slurm-backed orchestrator for Stage 1 blueprint generation and target review.

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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


THIS_FILE = Path(__file__).resolve()


def load_stage2_module() -> Any:
    path = THIS_FILE.with_name("per_node_worker_loop.py")
    spec = importlib.util.spec_from_file_location("per_node_worker_loop", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["per_node_worker_loop"] = module
    spec.loader.exec_module(module)
    return module


PWL = load_stage2_module()

REPO_ROOT: Path = PWL.REPO_ROOT
SOURCE_ROOT: Path = PWL.SOURCE_ROOT
SCRIPTS_DIR: Path = PWL.SCRIPTS_DIR
CREATE_WORKTREE: Path = PWL.CREATE_WORKTREE
CODEX_SESSIONS_ROOT: Path = PWL.CODEX_SESSIONS_ROOT
PYTHON_BIN: str = PWL.PYTHON_BIN

BLUEPRINTER_CONFIG = REPO_ROOT / "agents" / "Blueprinter"
REVIEWER_CONFIG = REPO_ROOT / "agents" / "Target-Reviewer"
REFINER_CONFIG = REPO_ROOT / "agents" / "Refiner"
REVIEW_ISSUE_TITLE = "Blueprint target review"
TARGET_REVIEWER_DEFAULT_START_PROMPT = "Begin the work."


def log(message: str) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[stage1-blueprint-loop {now}] {message}", flush=True)


@dataclass
class Stage1State:
    audit_dir: Path
    audit: list[dict[str, Any]] = field(default_factory=list)
    final_commit: str | None = None
    stage_status: str = "running"
    reason: str | None = None

    @property
    def result_path(self) -> Path:
        return self.audit_dir / "stage1_result.json"

    @property
    def audit_path(self) -> Path:
        return self.audit_dir / "stage1_audit.jsonl"

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
            "stage_status": {"stage_1": self.stage_status},
            "audit_log": self.audit,
            "reason": self.reason,
        }
        tmp = self.result_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.result_path)


def validate_stage1_paths(branch_main: str, worktrees_root: Path) -> None:
    if branch_main != "main":
        raise ValueError(
            "--branch-main must be 'main': .scripts/create-worktree.sh hardcodes origin/main "
            "and the agent PR delivery templates target base 'main'."
        )
    if not worktrees_root.is_absolute():
        raise ValueError(f"--worktrees-root must be absolute, got {worktrees_root}")
    actual = worktrees_root.resolve()
    allowed_lake_root = PWL.LEAN_PROJECT_ROOT.resolve()
    for parent in (actual, *actual.parents):
        if (parent / "lakefile.toml").exists():
            if parent.resolve() == allowed_lake_root:
                break
            raise ValueError(
                f"--worktrees-root must not be inside a Lake project; found {parent / 'lakefile.toml'} "
                f"above {actual}. Put agent worktrees outside Lake projects except the configured "
                f"ORCHESTRATOR_LEAN_PROJECT_ROOT={allowed_lake_root}."
            )
    for path in (CREATE_WORKTREE, BLUEPRINTER_CONFIG, REVIEWER_CONFIG, REFINER_CONFIG):
        if not path.exists():
            raise FileNotFoundError(path)


def replace_toml_string_if_present(text: str, key: str, value: str) -> str:
    quoted = json.dumps(value)
    pattern = re.compile(rf"(^\s*{re.escape(key)}\s*=\s*)\".*?\"", re.MULTILINE)
    return pattern.sub(rf"\g<1>{quoted}", text)


def patch_codex_config_for_agent(worktree: Path, lean_file: str, *, allow_hook: bool) -> None:
    config = worktree / ".codex" / "config.toml"
    text = config.read_text(encoding="utf-8")
    text = PWL.replace_template_paths(text)

    if allow_hook and "[[hooks.Stop.hooks]]" in text:
        text = PWL.replace_stop_hook_command(text, worktree)
    if "--lean-project-path" in text:
        text = PWL.replace_lean_project_path(text)

    for key, value in {
        "GIT_BASE_DIR": str(worktree),
        "APPLY_PATCH_WORKSPACE": str(worktree),
        "APPLY_PATCH_TARGET_FILE": lean_file,
    }.items():
        text = replace_toml_string_if_present(text, key, value)

    try:
        rel_dag_target = str((worktree / lean_file).resolve().relative_to(PWL.LEAN_PROJECT_ROOT))
    except ValueError:
        rel_dag_target = str(worktree / lean_file)
    for key, value in {
        "DAG_PROJECT_ROOT": PWL.LEAN_PROJECT_ROOT_LABEL,
        "DAG_TARGET_FILE": rel_dag_target,
    }.items():
        text = replace_toml_string_if_present(text, key, value)

    config.write_text(text, encoding="utf-8")
    PWL.materialize_runtime_reference_docs(worktree)


def write_blueprinter_inputs(
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
            f"problem_file: {PWL.yaml_quote(problem_file)}",
            f"proof_file: {PWL.yaml_quote(proof_file)}",
            f"lean_file: {PWL.yaml_quote(lean_file)}",
            f"owner: {PWL.yaml_quote(owner)}",
            f"repo: {PWL.yaml_quote(repo)}",
            f"branch: {PWL.yaml_quote(branch)}",
            f"worktrees_root: {PWL.yaml_quote(str(worktrees_root))}",
            "",
        ]
    )
    (worktree / "docs" / "inputs.yml").write_text(content, encoding="utf-8")


def write_reviewer_inputs(
    worktree: Path,
    *,
    lean_file: str,
    problem_file: str,
    owner: str,
    repo: str,
    branch: str,
    worktrees_root: Path,
) -> None:
    content = "\n".join(
        [
            f"problem_file: {PWL.yaml_quote(problem_file)}",
            f"lean_file: {PWL.yaml_quote(lean_file)}",
            f"owner: {PWL.yaml_quote(owner)}",
            f"repo: {PWL.yaml_quote(repo)}",
            f"branch: {PWL.yaml_quote(branch)}",
            f"worktrees_root: {PWL.yaml_quote(str(worktrees_root))}",
            "",
        ]
    )
    (worktree / "docs" / "inputs.yml").write_text(content, encoding="utf-8")


def preallocate_blueprinter(
    *,
    owner: str,
    repo: str,
    worktrees_root: Path,
    lean_file: str,
    problem_file: str,
    proof_file: str,
    base_commit: str,
    start_prompt: str | None = None,
) -> dict[str, Any]:
    branch = "blueprint/init"
    worktree = PWL.create_worktree(branch, BLUEPRINTER_CONFIG, owner, repo, base_commit, worktrees_root=worktrees_root)
    local_problem_file = PWL.materialize_problem_file(worktree, problem_file, base_commit)
    local_proof_file = PWL.materialize_proof_file(worktree, proof_file, base_commit)
    start_prompt_file = PWL.materialize_start_prompt(worktree, start_prompt)
    patch_codex_config_for_agent(worktree, lean_file, allow_hook=True)
    write_blueprinter_inputs(
        worktree,
        lean_file=lean_file,
        problem_file=local_problem_file,
        proof_file=local_proof_file,
        owner=owner,
        repo=repo,
        branch=branch,
        worktrees_root=worktrees_root,
    )
    return {
        "kind": "Blueprinter",
        "tag": "init",
        "branch": branch,
        "worktree": str(worktree),
        "base_commit": base_commit,
        "start_prompt_file": str(start_prompt_file) if start_prompt_file else None,
        "start_prompt_default": PWL.DEFAULT_START_PROMPT,
    }


def preallocate_reviewer(
    *,
    round_id: int,
    owner: str,
    repo: str,
    worktrees_root: Path,
    lean_file: str,
    problem_file: str,
    base_commit: str,
    start_prompt: str | None = None,
) -> dict[str, Any]:
    branch = f"target-review/round-{round_id}"
    worktree = PWL.create_worktree(branch, REVIEWER_CONFIG, owner, repo, base_commit, worktrees_root=worktrees_root)
    local_problem_file = PWL.materialize_problem_file(worktree, problem_file, base_commit)
    start_prompt_file = PWL.materialize_start_prompt(
        worktree,
        start_prompt,
        default_prompt=TARGET_REVIEWER_DEFAULT_START_PROMPT,
    )
    patch_codex_config_for_agent(worktree, lean_file, allow_hook=False)
    write_reviewer_inputs(
        worktree,
        lean_file=lean_file,
        problem_file=local_problem_file,
        owner=owner,
        repo=repo,
        branch=branch,
        worktrees_root=worktrees_root,
    )
    return {
        "kind": "Target-Reviewer",
        "tag": f"round-{round_id}",
        "branch": branch,
        "worktree": str(worktree),
        "base_commit": base_commit,
        "start_prompt_file": str(start_prompt_file) if start_prompt_file else None,
        "start_prompt_default": TARGET_REVIEWER_DEFAULT_START_PROMPT,
    }


def preallocate_stage1_refiner(
    *,
    round_id: int,
    owner: str,
    repo: str,
    worktrees_root: Path,
    lean_file: str,
    problem_file: str,
    proof_file: str,
    base_commit: str,
    issues: list[dict[str, Any]],
    start_prompt: str | None = None,
) -> dict[str, Any]:
    branch = f"blueprint-refiner/round-{round_id}"
    worktree = PWL.create_worktree(branch, REFINER_CONFIG, owner, repo, base_commit, worktrees_root=worktrees_root)
    local_problem_file = PWL.materialize_problem_file(worktree, problem_file, base_commit)
    local_proof_file = PWL.materialize_proof_file(worktree, proof_file, base_commit)
    start_prompt_file = PWL.materialize_start_prompt(worktree, start_prompt)
    PWL.render_issue_context(worktree, owner, repo, issues)
    PWL.patch_codex_config(worktree, lean_file)
    PWL.write_refiner_inputs(
        worktree,
        lean_file=lean_file,
        problem_file=local_problem_file,
        proof_file=local_proof_file,
        owner=owner,
        repo=repo,
        branch=branch,
        worktrees_root=worktrees_root,
    )
    return {
        "kind": "Refiner",
        "tag": f"round-{round_id}",
        "branch": branch,
        "worktree": str(worktree),
        "base_commit": base_commit,
        "issue_numbers": [int(issue["number"]) for issue in issues],
        "start_prompt_file": str(start_prompt_file) if start_prompt_file else None,
        "start_prompt_default": PWL.DEFAULT_START_PROMPT,
    }


def reviewer_issue_numbers(owner: str, repo: str) -> set[int]:
    return {
        int(issue["number"])
        for issue in PWL.list_open_issues(owner, repo)
        if str(issue.get("title") or "") == REVIEW_ISSUE_TITLE
    }


def open_issues_by_number(owner: str, repo: str) -> dict[int, dict[str, Any]]:
    return {int(issue["number"]): issue for issue in PWL.list_open_issues(owner, repo)}


def make_reviewer_job_script(
    *,
    job_file: Path,
    job_name: str,
    branch: str,
    worktree: Path,
    result_file: Path,
    codex_home: Path,
    agent_resource: str,
    start_prompt_file: Path | None = None,
    start_prompt_default: str = TARGET_REVIEWER_DEFAULT_START_PROMPT,
) -> None:
    account = PWL.agent_slurm_account(agent_resource)
    resource_directives = PWL.agent_resource_directives(agent_resource)
    start_prompt_file_value = shlex.quote(str(start_prompt_file)) if start_prompt_file else '""'
    default_start_prompt_value = shlex.quote(start_prompt_default)
    default_start_prompt_json = json.dumps(start_prompt_default)
    script = f"""#!/usr/bin/env bash
#SBATCH --account={account}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={PWL.AGENT_CPUS}
#SBATCH --mem-per-cpu={PWL.SLURM_MEM_PER_CPU}
{resource_directives}
#SBATCH --time={PWL.AGENT_TIME}
#SBATCH --job-name={job_name}
#SBATCH --output={shlex.quote(str(job_file.with_suffix(".out")))}
#SBATCH --error={shlex.quote(str(job_file.with_suffix(".err")))}

set +e
export PATH={shlex.quote(PWL.AGENT_PATH)}
{PWL.github_auth_bootstrap()}
export VERIFY_BLUEPRINT_LEAN_THREADS={PWL.AGENT_CPUS}
export LEAN_LSP_THREADS={PWL.AGENT_CPUS}
export DAG_TRACKER_LEAN_THREADS={PWL.AGENT_CPUS}
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
START_PROMPT_FILE={start_prompt_file_value}
if [[ -n "$START_PROMPT_FILE" ]]; then
  START_PROMPT="$(cat "$START_PROMPT_FILE")"
else
  START_PROMPT={default_start_prompt_value}
fi
codex exec "$START_PROMPT"
RC=$?
python3 - "$CODEX_HOME" {shlex.quote(str(result_file))} "$RC" "$START_TS" "$START_PROMPT_FILE" <<'PY'
import json
import sys
from pathlib import Path

codex_home = Path(sys.argv[1])
result = Path(sys.argv[2])
rc = int(sys.argv[3])
start_ts = int(sys.argv[4])
prompt_file_raw = sys.argv[5]
start_prompt = Path(prompt_file_raw).read_text(encoding="utf-8") if prompt_file_raw else {default_start_prompt_json}
sessions = []
history = codex_home / "history.jsonl"
if history.exists():
    with history.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("text") != start_prompt:
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
    "start_prompt_file": prompt_file_raw or None,
}}
result.parent.mkdir(parents=True, exist_ok=True)
tmp = result.with_suffix(result.suffix + ".tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
tmp.replace(result)
PY

cd {shlex.quote(str(REPO_ROOT))}
if [[ "$RC" -eq 0 ]]; then
  echo "Cleaning reviewer worktree branch {shlex.quote(branch)} at {shlex.quote(str(worktree))}" >&2
  if git worktree remove --force {shlex.quote(str(worktree))}; then
    git branch -D {shlex.quote(branch)} || true
    git push origin --delete {shlex.quote(branch)} || true
  else
    echo "warning: failed to remove reviewer worktree {shlex.quote(str(worktree))}" >&2
  fi
else
  echo "Skipping reviewer cleanup for {shlex.quote(branch)} because Codex exited with $RC" >&2
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


def launch_reviewer(
    handle: dict[str, Any],
    *,
    audit_dir: Path,
    poll_seconds: int,
    agent_resource: str,
) -> PWL.AgentRun:
    jobs_dir = audit_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    label = handle.get("tag") or handle["branch"]
    job_dir = jobs_dir / PWL.job_slug(handle["kind"]) / PWL.job_slug(label, limit=180)
    job_dir.mkdir(parents=True, exist_ok=True)
    job_file = job_dir / "job.sbatch"
    result_file = job_dir / "result.json"
    codex_home = CODEX_SESSIONS_ROOT / PWL.codex_home_slug(handle["branch"])
    make_reviewer_job_script(
        job_file=job_file,
        job_name=PWL.job_slug(f"leanmarathon-{handle['kind']}-{label}", limit=60),
        branch=handle["branch"],
        worktree=Path(handle["worktree"]),
        result_file=result_file,
        codex_home=codex_home,
        agent_resource=agent_resource,
        start_prompt_file=Path(handle["start_prompt_file"]) if handle.get("start_prompt_file") else None,
        start_prompt_default=str(handle.get("start_prompt_default", TARGET_REVIEWER_DEFAULT_START_PROMPT)),
    )
    job_id = PWL.submit_job(job_file)
    log(f"submitted {handle['kind']} {label} as Slurm job {job_id}")
    states = PWL.wait_for_jobs([job_id], poll_seconds)
    result = PWL.read_agent_result(result_file)
    state, _exit_code = states.get(job_id, (None, None))
    run = PWL.AgentRun(
        kind=handle["kind"],
        branch=handle["branch"],
        worktree=handle["worktree"],
        base_commit=handle.get("base_commit"),
        slurm_job_id=job_id,
        codex_session_id=result.get("codex_session_id"),
        returncode=result.get("returncode"),
        state=state,
        result_file=str(result_file),
        tag=handle.get("tag"),
        start_prompt_file=result.get("start_prompt_file") or handle.get("start_prompt_file"),
    )
    if run.returncode == 0:
        return run
    raise RuntimeError(
        f"{run.kind} job {job_id} for {handle.get('tag')} ended with "
        f"state={run.state}, returncode={run.returncode}; see {result_file}"
    )


def launch_single_agent(
    handle: dict[str, Any],
    *,
    audit_dir: Path,
    poll_seconds: int,
    agent_resource: str,
) -> PWL.AgentRun:
    return PWL.launch_agents(
        [handle],
        audit_dir=audit_dir,
        poll_seconds=poll_seconds,
        agent_resource=agent_resource,
    )[0]


def run_refiner_for_issues(
    *,
    round_id: int,
    args: argparse.Namespace,
    worktrees_root: Path,
    audit_dir: Path,
    base_commit: str,
    issues: list[dict[str, Any]],
    state: Stage1State,
) -> PWL.AgentRun:
    issue_numbers = [int(issue["number"]) for issue in issues]
    log(
        f"review round {round_id}: launching Refiner for issues {issue_numbers} "
        f"from {base_commit[:12]}"
    )
    handle = preallocate_stage1_refiner(
        round_id=round_id,
        owner=args.owner,
        repo=args.repo,
        worktrees_root=worktrees_root,
        lean_file=args.lean_file,
        problem_file=args.problem_file,
        proof_file=args.proof_file,
        base_commit=base_commit,
        issues=issues,
        start_prompt=args.refiner_prompt,
    )
    run = launch_single_agent(
        handle,
        audit_dir=audit_dir / f"review-round-{round_id}" / "refiner",
        poll_seconds=args.poll_seconds,
        agent_resource=args.agent_resource,
    )
    state.append(
        {
            "stage": 1,
            "round": round_id,
            "kind": "refiner",
            "item": run.audit_record(),
            "issue_numbers": issue_numbers,
        }
    )
    return run


def stage1_loop(args: argparse.Namespace) -> Stage1State:
    worktrees_root = Path(args.worktrees_root)
    PWL.validate_positive("--max-review-rounds", args.max_review_rounds)
    PWL.validate_positive("--start-review-round", args.start_review_round)
    if args.start_review_round > args.max_review_rounds:
        raise ValueError(
            f"--start-review-round ({args.start_review_round}) must be <= "
            f"--max-review-rounds ({args.max_review_rounds})"
        )
    validate_stage1_paths(args.branch_main, worktrees_root)

    audit_dir = Path(args.audit_dir) if args.audit_dir else default_audit_dir()
    state = Stage1State(audit_dir=audit_dir)
    state.write_result()

    commit = PWL.current_main_head(args.branch_main, args.owner, args.repo)
    log(f"starting Stage 1 from origin/{args.branch_main} at {commit}")

    if not args.skip_blueprinter:
        handle = preallocate_blueprinter(
            owner=args.owner,
            repo=args.repo,
            worktrees_root=worktrees_root,
            lean_file=args.lean_file,
            problem_file=args.problem_file,
            proof_file=args.proof_file,
            base_commit=commit,
            start_prompt=args.blueprinter_prompt,
        )
        run = launch_single_agent(
            handle,
            audit_dir=audit_dir / "blueprinter",
            poll_seconds=args.poll_seconds,
            agent_resource=args.agent_resource,
        )
        state.append({"stage": 1, "kind": "blueprinter", "item": run.audit_record()})
        new_commit = PWL.current_main_head(args.branch_main, args.owner, args.repo)
        if new_commit == commit:
            state.final_commit = commit
            state.stage_status = "stuck"
            state.reason = "stage 1: blueprinter completed but main did not advance"
            state.append({"stage": 1, "kind": "stuck", "reason": state.reason})
            return state
        log(
            f"blueprinter advanced origin/{args.branch_main} "
            f"from {commit[:12]} to {new_commit[:12]}"
        )
        commit = new_commit
    else:
        log("skipping blueprinter by request")

    for round_id in range(args.start_review_round, args.max_review_rounds + 1):
        round_base = PWL.current_main_head(args.branch_main, args.owner, args.repo)
        if round_base != commit:
            log(
                f"review round {round_id}: refreshing base from {commit[:12]} "
                f"to current origin/{args.branch_main} {round_base[:12]}"
            )
        commit = round_base

        existing_open = open_issues_by_number(args.owner, args.repo)
        if existing_open:
            run_refiner_for_issues(
                round_id=round_id,
                args=args,
                worktrees_root=worktrees_root,
                audit_dir=audit_dir,
                base_commit=commit,
                issues=list(existing_open.values()),
                state=state,
            )
            new_commit = PWL.current_main_head(args.branch_main, args.owner, args.repo)
            if new_commit == commit:
                state.final_commit = commit
                state.stage_status = "stuck"
                state.reason = "stage 1: pre-review open-issue refiner made no progress"
                state.append({"stage": 1, "round": round_id, "kind": "stuck", "reason": state.reason})
                return state
            log(
                f"review round {round_id}: pre-review refiner advanced origin/{args.branch_main} "
                f"from {commit[:12]} to {new_commit[:12]}"
            )
            commit = new_commit
            continue

        before_review_issues = reviewer_issue_numbers(args.owner, args.repo)
        handle = preallocate_reviewer(
            round_id=round_id,
            owner=args.owner,
            repo=args.repo,
            worktrees_root=worktrees_root,
            lean_file=args.lean_file,
            problem_file=args.problem_file,
            base_commit=commit,
            start_prompt=args.target_reviewer_prompt,
        )
        run = launch_reviewer(
            handle,
            audit_dir=audit_dir / f"review-round-{round_id}" / "reviewer",
            poll_seconds=args.poll_seconds,
            agent_resource=args.agent_resource,
        )
        after_review_issues = reviewer_issue_numbers(args.owner, args.repo)
        new_issue_numbers = sorted(after_review_issues - before_review_issues)
        state.append(
            {
                "stage": 1,
                "round": round_id,
                "kind": "Target-Reviewer",
                "item": run.audit_record(),
                "new_issue_numbers": new_issue_numbers,
            }
        )

        if not new_issue_numbers:
            commit = PWL.current_main_head(args.branch_main, args.owner, args.repo)
            state.final_commit = commit
            state.stage_status = "done"
            state.reason = None
            state.append({"stage": 1, "round": round_id, "kind": "done", "commit": commit})
            return state

        all_open = open_issues_by_number(args.owner, args.repo)
        issues = [all_open[number] for number in new_issue_numbers if number in all_open]
        if not issues:
            state.final_commit = commit
            state.stage_status = "stuck"
            state.reason = "stage 1: reviewer issue disappeared before refiner dispatch"
            state.append({"stage": 1, "round": round_id, "kind": "stuck", "reason": state.reason})
            return state

        refiner_base = PWL.current_main_head(args.branch_main, args.owner, args.repo)
        run_refiner_for_issues(
            round_id=round_id,
            args=args,
            worktrees_root=worktrees_root,
            audit_dir=audit_dir,
            base_commit=refiner_base,
            issues=issues,
            state=state,
        )
        new_commit = PWL.current_main_head(args.branch_main, args.owner, args.repo)
        if new_commit == refiner_base:
            state.final_commit = refiner_base
            state.stage_status = "stuck"
            state.reason = "stage 1: refiner completed but main did not advance"
            state.append({"stage": 1, "round": round_id, "kind": "stuck", "reason": state.reason})
            return state
        log(
            f"review round {round_id}: refiner advanced origin/{args.branch_main} "
            f"from {refiner_base[:12]} to {new_commit[:12]}"
        )
        commit = new_commit

    state.final_commit = commit
    state.stage_status = "stuck"
    state.reason = f"max_review_rounds ({args.max_review_rounds}) exhausted"
    state.append({"stage": 1, "kind": "stuck", "reason": state.reason})
    return state


def default_audit_dir() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / ".orchestrator-runs" / f"stage1-{stamp}"


def copy_runtime_input_to_target(value: str, target_root: Path) -> str:
    return PWL.copy_runtime_input_to_target(value, target_root)


def prepare_target_orchestration_root(args: argparse.Namespace) -> Path:
    target_root = PWL.target_orchestration_root(args.owner, args.repo)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    expected_origin = PWL.target_repo_url(args.owner, args.repo)
    auth_env = PWL.git_auth_env()

    if not target_root.exists():
        log(f"creating per-target orchestration root at {target_root}")
        PWL.run_cmd(["git", "clone", expected_origin, str(target_root)], cwd=SOURCE_ROOT, env=auth_env)
    elif not (target_root / ".git").exists():
        raise RuntimeError(f"target orchestration root exists but is not a git repo: {target_root}")

    PWL.run_cmd(["git", "-C", str(target_root), "remote", "set-url", "origin", expected_origin])
    PWL.run_cmd(["git", "-C", str(target_root), "fetch", "origin", args.branch_main], env=auth_env)
    branch_check = PWL.run_cmd(
        ["git", "-C", str(target_root), "rev-parse", "--verify", args.branch_main],
        check=False,
    )
    if branch_check.returncode == 0:
        PWL.run_cmd(["git", "-C", str(target_root), "checkout", args.branch_main])
    else:
        PWL.run_cmd(["git", "-C", str(target_root), "checkout", "-b", args.branch_main, f"origin/{args.branch_main}"])
    PWL.run_cmd(["git", "-C", str(target_root), "pull", "--ff-only", "origin", args.branch_main], env=auth_env)

    scripts_dir = target_root / ".scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_ROOT / ".scripts" / "stage1_blueprint_loop.py", scripts_dir / "stage1_blueprint_loop.py")
    shutil.copy2(SOURCE_ROOT / ".scripts" / "per_node_worker_loop.py", scripts_dir / "per_node_worker_loop.py")
    shutil.copy2(SOURCE_ROOT / ".scripts" / "create-worktree.sh", scripts_dir / "create-worktree.sh")
    shutil.copy2(SOURCE_ROOT / ".scripts" / "verify_blueprint.py", scripts_dir / "verify_blueprint.py")

    PWL.copy_path_fresh(SOURCE_ROOT / "agents" / "Blueprinter", target_root / "agents" / "Blueprinter")
    PWL.copy_path_fresh(SOURCE_ROOT / "agents" / "Target-Reviewer", target_root / "agents" / "Target-Reviewer")
    PWL.copy_path_fresh(SOURCE_ROOT / "agents" / "Refiner", target_root / "agents" / "Refiner")
    PWL.copy_path_fresh(SOURCE_ROOT / "agents" / "Worker", target_root / "agents" / "Worker")
    copy_runtime_input_to_target(args.problem_file, target_root)
    copy_runtime_input_to_target(args.proof_file, target_root)
    return target_root


def delegated_submit_self(args: argparse.Namespace) -> str | None:
    if PWL.target_origin_matches(args.owner, args.repo):
        return None

    target_root = prepare_target_orchestration_root(args)
    forwarded = list(sys.argv[1:])
    forwarded = PWL.set_forwarded_option(
        forwarded,
        "--problem-file",
        copy_runtime_input_to_target(args.problem_file, target_root),
    )
    forwarded = PWL.set_forwarded_option(
        forwarded,
        "--proof-file",
        copy_runtime_input_to_target(args.proof_file, target_root),
    )
    forwarded = PWL.set_forwarded_option(forwarded, "--worktrees-root", str(PWL.target_worktrees_root(args.owner, args.repo)))
    forwarded = PWL.remove_forwarded_option(forwarded, "--audit-dir")

    env = os.environ.copy()
    env["ORCHESTRATOR_SOURCE_ROOT"] = str(SOURCE_ROOT)
    env["ORCHESTRATOR_LEAN_PROJECT_ROOT"] = PWL.LEAN_PROJECT_ROOT_LABEL
    proc = subprocess.run(
        [PYTHON_BIN, str(target_root / ".scripts" / "stage1_blueprint_loop.py"), *forwarded],
        cwd=str(PWL.LEAN_PROJECT_ROOT),
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

    validate_stage1_paths(args.branch_main, Path(args.worktrees_root))
    PWL.require_target_origin(args.owner, args.repo)

    audit_dir = Path(args.audit_dir) if args.audit_dir else default_audit_dir()
    audit_dir.mkdir(parents=True, exist_ok=True)

    forwarded: list[str] = []
    for raw in sys.argv[1:]:
        if raw != "--submit-self":
            forwarded.append(raw)
    if "--audit-dir" not in forwarded:
        forwarded.extend(["--audit-dir", str(audit_dir)])

    script_path = audit_dir / "stage1.sbatch"
    command = " ".join([shlex.quote(sys.executable), shlex.quote(str(THIS_FILE)), *map(shlex.quote, forwarded)])
    account = PWL.agent_slurm_account(PWL.ORCH_RESOURCE_MODE)
    account_line = PWL.account_directive(account)
    resource_directives = PWL.agent_resource_directives(PWL.ORCH_RESOURCE_MODE)
    env_exports = PWL.leanmarathon_env_exports()
    script = f"""#!/usr/bin/env bash
{account_line}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={PWL.ORCH_CPUS}
#SBATCH --mem-per-cpu={PWL.SLURM_MEM_PER_CPU}
{resource_directives}
#SBATCH --time={PWL.ORCH_TIME}
#SBATCH --job-name=leanmarathon-stage1-loop
#SBATCH --output={shlex.quote(str(audit_dir / "stage1.out"))}
#SBATCH --error={shlex.quote(str(audit_dir / "stage1.err"))}

set -euo pipefail
export PATH={shlex.quote(PWL.ORCH_PATH)}
{env_exports}
{PWL.github_auth_bootstrap()}
export ORCHESTRATOR_SOURCE_ROOT={shlex.quote(str(SOURCE_ROOT))}
export ORCHESTRATOR_LEAN_PROJECT_ROOT={shlex.quote(PWL.LEAN_PROJECT_ROOT_LABEL)}
export ORCH_CPUS={PWL.ORCH_CPUS}
export ORCH_TIME={shlex.quote(PWL.ORCH_TIME)}
export ORCH_RESOURCE_MODE={shlex.quote(PWL.ORCH_RESOURCE_MODE)}
export AGENT_CPUS={PWL.AGENT_CPUS}
export AGENT_TIME={shlex.quote(PWL.AGENT_TIME)}
export AGENT_RESOURCE_MODE={shlex.quote(args.agent_resource)}
export LEANMARATHON_NUMERIC_TOOLS={shlex.quote(os.environ.get("LEANMARATHON_NUMERIC_TOOLS", ""))}
cd {shlex.quote(str(PWL.LEAN_PROJECT_ROOT))}
exec {command}
"""
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)
    job_id = PWL.submit_job(script_path)
    print(json.dumps({"slurm_job_id": job_id, "audit_dir": str(audit_dir), "script": str(script_path)}))
    return job_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch-main", default="main")
    parser.add_argument("--worktrees-root", default=str(REPO_ROOT / ".worktrees"))
    parser.add_argument("--lean-file", default="LeanMarathon/Main.lean")
    parser.add_argument("--problem-file", required=True)
    parser.add_argument("--proof-file", required=True)
    parser.add_argument("--max-review-rounds", type=int, default=20)
    parser.add_argument(
        "--start-review-round",
        type=int,
        default=1,
        help="first Target-Reviewer round id to use for resumed Stage 1 runs",
    )
    parser.add_argument(
        "--skip-blueprinter",
        action="store_true",
        help="resume directly at the Target-Reviewer/Refiner loop from current main",
    )
    parser.add_argument("--audit-dir")
    parser.add_argument("--poll-seconds", type=int, default=PWL.POLL_SECONDS)
    parser.add_argument(
        "--agent-resource",
        choices=("cpu", "gpu"),
        default=PWL.AGENT_RESOURCE_MODE,
        help="Slurm resource mode for lb/tr/br Codex jobs",
    )
    parser.add_argument("--blueprinter-prompt")
    parser.add_argument("--target-reviewer-prompt")
    parser.add_argument("--refiner-prompt")
    parser.add_argument("--submit-self", action="store_true", help="submit the Stage 1 orchestrator itself as a Slurm job")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.submit_self:
        submit_self(args)
        return 0
    state = stage1_loop(args)
    state.write_result()
    print(json.dumps(json.loads(state.result_path.read_text(encoding="utf-8")), indent=2, sort_keys=True))
    return 0 if state.stage_status == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
