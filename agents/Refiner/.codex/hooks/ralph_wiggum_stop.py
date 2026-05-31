#!/usr/bin/env python3
"""Stop hook that keeps Codex working until delivery.yml points to a merged PR."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml


EXPECTED_KEYS = {"kind", "owner", "repo", "number", "url"}
MAX_BOT_COMMENT_CHARS = 6_000
HTTP_TIMEOUT = 20
POLL_INTERVAL_SECONDS = 120
MAX_POLL_SECONDS = 7_200
VERIFY_WORKFLOW_FILE = "verify-blueprint.yml"
VERIFY_COMMENT_MARKER = "<!-- verify-blueprint:report -->"
LOG_FILE_NAME = "verify-blueprint.log"
LOG_DOWNLOAD_RETRIES = 6
LOG_DOWNLOAD_RETRY_SECONDS = 10


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def construct_mapping_without_duplicates(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.YAMLError(f"duplicate key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping_without_duplicates)


@dataclass(frozen=True)
class Delivery:
    kind: str
    owner: str
    repo: str
    number: int
    url: str


@dataclass(frozen=True)
class RuntimeContext:
    branch: str
    worktree_path: str
    lean_file: str


class HookBlock(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HookTerminate(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def emit_block(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def emit_terminate(reason: str) -> int:
    print(
        json.dumps(
            {
                "continue": False,
                "stopReason": reason,
                "systemMessage": reason,
            },
            ensure_ascii=False,
        )
    )
    return 0


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    keep_head = max_chars // 2
    keep_tail = max_chars - keep_head
    return (
        text[:keep_head].rstrip()
        + "\n\n[... omitted "
        + str(len(text) - max_chars)
        + " characters ...]\n\n"
        + text[-keep_tail:].lstrip()
    )


def format_yaml_key(key: Any) -> str:
    return f"`{key}`" if isinstance(key, str) else f"`{key!r}`"


def gate1_prompt(diagnostic: str) -> str:
    return f"""You did not pass the delivery.yml gate.

The stop hook cannot check PR merge status until `docs/delivery.yml` is deterministically parseable.

Current failure:
{diagnostic}

Task:
1. If you have not reached the delivery step yet, do not edit `docs/delivery.yml` prematurely. Resume from the interrupted point, strictly follow `AGENTS.md` and the active phase file, and proceed to `docs/deliver/pr.md` only when the workflow says to deliver.
2. If you are already in delivery or have opened the PR, repair `docs/delivery.yml` so it is a single valid YAML mapping with exactly these five top-level keys and no duplicate keys: `kind`, `owner`, `repo`, `number`, and `url`.
3. The values must describe the PR opened for this run: `kind: pr`, non-empty `owner`, non-empty `repo`, positive integer `number`, and the PR `url`.
4. If no PR exists yet and the workflow has reached delivery, follow `docs/deliver/pr.md` to open it, then replace `docs/delivery.yml` with the exact PR delivery record.
5. Stop again only after `docs/delivery.yml` has this shape:

```yaml
kind: pr
owner: "<GitHub owner>"
repo: "<GitHub repo>"
number: <PR number>
url: "https://github.com/<owner>/<repo>/pull/<PR number>"
```
"""


def read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def validate_delivery(workspace_dir: Path) -> Delivery:
    delivery_path = workspace_dir / "docs" / "delivery.yml"
    try:
        raw = delivery_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HookBlock(gate1_prompt(f"`docs/delivery.yml` could not be read: {exc}")) from exc

    try:
        parsed = yaml.load(raw, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise HookBlock(gate1_prompt(f"`docs/delivery.yml` is not valid YAML: {exc}")) from exc

    if not isinstance(parsed, dict):
        raise HookBlock(gate1_prompt("`docs/delivery.yml` must be a single YAML mapping."))

    keys = set(parsed.keys())
    if keys != EXPECTED_KEYS:
        missing = sorted(EXPECTED_KEYS - keys, key=repr)
        extra = sorted(keys - EXPECTED_KEYS, key=repr)
        details = []
        if missing:
            details.append("missing keys: " + ", ".join(format_yaml_key(key) for key in missing))
        if extra:
            details.append("extra keys: " + ", ".join(format_yaml_key(key) for key in extra))
        detail_text = "; ".join(details) if details else "key set mismatch"
        raise HookBlock(gate1_prompt(f"`docs/delivery.yml` has the wrong top-level keys: {detail_text}."))

    kind = parsed["kind"]
    owner = parsed["owner"]
    repo = parsed["repo"]
    number = parsed["number"]
    url = parsed["url"]

    errors: list[str] = []
    if kind != "pr":
        errors.append("`kind` must be exactly `pr`")
    if not isinstance(owner, str) or not owner.strip():
        errors.append("`owner` must be a non-empty string")
    if not isinstance(repo, str) or not repo.strip():
        errors.append("`repo` must be a non-empty string")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        errors.append("`number` must be a positive integer PR number")
    if not isinstance(url, str) or not url.strip():
        errors.append("`url` must be a non-empty string")

    if errors:
        raise HookBlock(
            gate1_prompt(
                "`docs/delivery.yml` has the right keys but invalid values:\n"
                + "\n".join(f"- {error}" for error in errors)
            )
        )

    return Delivery(kind=kind, owner=owner.strip(), repo=repo.strip(), number=number, url=url.strip())


class GitHubClient:
    def __init__(self, token: str | None) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "codex-ralph-wiggum-stop-hook",
            }
        )
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", HTTP_TIMEOUT)
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            raise HookTerminate(f"Stop hook terminated: GitHub API request failed before a response was received: {exc}") from exc
        if response.status_code == 401:
            raise HookTerminate("Stop hook terminated: GitHub API authentication failed. Ensure `GITHUB_TOKEN` or `GITHUB_PERSONAL_ACCESS_TOKEN` is available to the hook environment.")
        if response.status_code == 403:
            raise HookTerminate("Stop hook terminated: GitHub API access was forbidden or rate-limited. Ensure the hook token can read PRs, issue comments, and Actions logs for this repository.")
        return response

    def get_json(self, url: str, **params: Any) -> Any:
        response = self.request("GET", url, params={key: value for key, value in params.items() if value is not None})
        if response.status_code >= 400:
            raise HookTerminate(f"Stop hook terminated: GitHub API request failed with HTTP {response.status_code}: {url}\n{truncate(response.text, 1000)}")
        return response.json()


def github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")


def is_pr_merged(client: GitHubClient, delivery: Delivery) -> bool:
    url = f"https://api.github.com/repos/{delivery.owner}/{delivery.repo}/pulls/{delivery.number}/merge"
    response = client.request("GET", url)
    if response.status_code == 204:
        return True
    if response.status_code == 404:
        return False
    raise HookTerminate(f"Stop hook terminated: could not determine whether PR #{delivery.number} is merged. GitHub returned HTTP {response.status_code}.\n{truncate(response.text, 1000)}")


def get_pr(client: GitHubClient, delivery: Delivery) -> dict[str, Any]:
    return client.get_json(f"https://api.github.com/repos/{delivery.owner}/{delivery.repo}/pulls/{delivery.number}")


def useful_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or (stripped.startswith("<") and stripped.endswith(">")):
        return None
    return stripped


def load_runtime_context(workspace_dir: Path, pr: dict[str, Any]) -> RuntimeContext:
    inputs_path = workspace_dir / "docs" / "inputs.yml"
    inputs: dict[str, Any] = {}
    try:
        parsed = yaml.load(inputs_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        if isinstance(parsed, dict):
            inputs = parsed
    except (OSError, yaml.YAMLError):
        inputs = {}

    head = pr.get("head") if isinstance(pr, dict) else {}
    branch = useful_string(inputs.get("branch"))
    if branch is None and isinstance(head, dict):
        branch = useful_string(head.get("ref"))
    if branch is None:
        branch = "<feature branch>"

    lean_file = useful_string(inputs.get("lean_file")) or "LeanMarathon/Main.lean"
    worktrees_root = useful_string(inputs.get("worktrees_root"))
    if worktrees_root:
        worktree_path = str(Path(worktrees_root) / branch)
    else:
        worktree_path = str(workspace_dir)

    return RuntimeContext(branch=branch, worktree_path=worktree_path, lean_file=lean_file)


def get_bot_comment(client: GitHubClient, delivery: Delivery) -> str:
    comments = client.get_json(
        f"https://api.github.com/repos/{delivery.owner}/{delivery.repo}/issues/{delivery.number}/comments",
        per_page=100,
    )
    if not isinstance(comments, list) or not comments:
        return "(none)"

    marker_comments = [
        comment for comment in comments
        if isinstance(comment, dict)
        and isinstance(comment.get("body"), str)
        and comment["body"].startswith(VERIFY_COMMENT_MARKER)
    ]
    bot_comments = [
        comment for comment in comments
        if isinstance(comment, dict) and isinstance(comment.get("user"), dict) and comment["user"].get("type") == "Bot"
    ]
    chosen = marker_comments[-1] if marker_comments else bot_comments[-1] if bot_comments else comments[-1]
    author = chosen.get("user", {}).get("login", "unknown")
    updated_at = chosen.get("updated_at", "unknown time")
    body = chosen.get("body") or "(comment body is empty)"
    return truncate(f"Author: {author}\nUpdated: {updated_at}\n\n{body}", MAX_BOT_COMMENT_CHARS)


def run_belongs_to_pr(run: dict[str, Any], pr_number: int) -> bool:
    pull_requests = run.get("pull_requests")
    if not isinstance(pull_requests, list):
        return False
    for pr in pull_requests:
        if not isinstance(pr, dict):
            continue
        try:
            if int(pr.get("number")) == pr_number:
                return True
        except (TypeError, ValueError):
            continue
    return False


def latest_verify_run_for_pr(client: GitHubClient, delivery: Delivery) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    url = f"https://api.github.com/repos/{delivery.owner}/{delivery.repo}/actions/workflows/{VERIFY_WORKFLOW_FILE}/runs"
    for page in range(1, 6):
        data = client.get_json(url, event="pull_request_target", per_page=100, page=page)
        runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
        if not isinstance(runs, list):
            break
        matches.extend(run for run in runs if isinstance(run, dict) and run_belongs_to_pr(run, delivery.number))
        if len(runs) < 100:
            break

    if not matches:
        return None

    def sort_key(run: dict[str, Any]) -> tuple[str, int, int]:
        created_at = str(run.get("created_at") or "")
        run_attempt = run.get("run_attempt") if isinstance(run.get("run_attempt"), int) else 0
        run_id = run.get("id") if isinstance(run.get("id"), int) else 0
        return (created_at, run_attempt, run_id)

    return max(matches, key=sort_key)


def list_jobs(client: GitHubClient, delivery: Delivery, run: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = run.get("id")
    attempt = run.get("run_attempt")
    if not run_id:
        return []
    if attempt:
        url = f"https://api.github.com/repos/{delivery.owner}/{delivery.repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"
    else:
        url = f"https://api.github.com/repos/{delivery.owner}/{delivery.repo}/actions/runs/{run_id}/jobs"
    data = client.get_json(url, per_page=100)
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    return jobs if isinstance(jobs, list) else []


def download_job_log(client: GitHubClient, delivery: Delivery, job_id: int) -> str:
    url = f"https://api.github.com/repos/{delivery.owner}/{delivery.repo}/actions/jobs/{job_id}/logs"
    response = client.request("GET", url)
    for attempt in range(1, LOG_DOWNLOAD_RETRIES + 1):
        if response.status_code < 400:
            break
        if attempt < LOG_DOWNLOAD_RETRIES and response.status_code in (404, 409, 410, 429, 500, 502, 503, 504):
            time.sleep(LOG_DOWNLOAD_RETRY_SECONDS)
            response = client.request("GET", url)
            continue
        return (
            f"Log download unavailable for job {job_id}: GitHub returned HTTP "
            f"{response.status_code}.\n{truncate(response.text, 2000)}"
        )
    content = response.content
    if content.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                chunks: list[str] = []
                for name in sorted(archive.namelist()):
                    if name.endswith("/"):
                        continue
                    with archive.open(name) as file:
                        chunks.append(f"===== {name} =====\n" + file.read().decode("utf-8", errors="replace"))
                return "\n\n".join(chunks)
        except zipfile.BadZipFile:
            pass
    return response.text


def failed_step_lines(job: dict[str, Any]) -> str:
    steps = job.get("steps")
    if not isinstance(steps, list) or not steps:
        return "Failed steps: (GitHub did not return step metadata.)"

    interesting = [
        step for step in steps
        if isinstance(step, dict)
        and (step.get("status") != "completed" or step.get("conclusion") not in ("success", "skipped"))
    ]
    if not interesting:
        return "Failed steps: (none marked failed in step metadata.)"

    lines = ["Failed steps:"]
    for step in interesting:
        name = step.get("name") or f"step {step.get('number', '?')}"
        status = step.get("status")
        conclusion = step.get("conclusion")
        lines.append(f"- {name} (status: {status}; conclusion: {conclusion})")
    return "\n".join(lines)


def log_file_relative_path() -> str:
    return f"docs/{LOG_FILE_NAME}"


def write_failed_run_log_file(workspace_dir: Path, client: GitHubClient, delivery: Delivery, run: dict[str, Any]) -> str:
    lines: list[str] = []
    run_name = run.get("name") or run.get("display_title") or f"run {run.get('id')}"
    run_status = run.get("status")
    run_conclusion = run.get("conclusion")
    run_url = run.get("html_url")
    lines.append("# verify-blueprint raw job logs")
    lines.append("")
    lines.append("This file is overwritten completely by each failed CI run. It is not an aggregation.")
    lines.append("")
    lines.append(f"PR: #{delivery.number} {delivery.url}")
    lines.append(f"Workflow run: {run_name}")
    lines.append(f"Status: {run_status}; conclusion: {run_conclusion}; attempt: {run.get('run_attempt')}; url: {run_url}")
    lines.append("")

    jobs = list_jobs(client, delivery, run)
    if not jobs:
        lines.append("No jobs returned for this run.")
    else:
        failed_jobs = [
            job for job in jobs
            if job.get("conclusion") not in (None, "success", "skipped") or job.get("status") != "completed"
        ]
        selected_jobs = failed_jobs if failed_jobs else jobs

        for job in selected_jobs:
            job_name = job.get("name") or f"job {job.get('id')}"
            job_status = job.get("status")
            job_conclusion = job.get("conclusion")
            job_url = job.get("html_url")
            lines.append("=" * 80)
            lines.append(f"Job: {job_name}")
            lines.append(f"Status: {job_status}; conclusion: {job_conclusion}; url: {job_url}")
            lines.append(failed_step_lines(job))
            lines.append("-" * 80)
            lines.append("Raw job log:")
            if job_status == "completed" and job.get("id"):
                lines.append(download_job_log(client, delivery, int(job["id"])))
            else:
                lines.append("Log not available yet because the job is not completed.")
            lines.append("")

    log_path = workspace_dir / "docs" / LOG_FILE_NAME
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = log_path.with_name(f".{log_path.name}.tmp")
        tmp_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        tmp_path.replace(log_path)
    except OSError as exc:
        raise HookTerminate(f"Stop hook terminated: could not write `{log_file_relative_path()}`: {exc}") from exc

    return log_file_relative_path()


def poll_budget_seconds() -> int:
    raw = os.environ.get("RALPH_STOP_MAX_POLL_SECONDS")
    if raw is None:
        return MAX_POLL_SECONDS
    try:
        parsed = int(raw)
    except ValueError:
        return MAX_POLL_SECONDS
    return max(POLL_INTERVAL_SECONDS, parsed)


def run_status_line(run: dict[str, Any] | None) -> str:
    if run is None:
        return "none found"
    name = run.get("name") or run.get("display_title") or f"run {run.get('id')}"
    return (
        f"{name}; status={run.get('status')}; conclusion={run.get('conclusion')}; "
        f"attempt={run.get('run_attempt')}; url={run.get('html_url')}"
    )


def pr_head_sha(pr: dict[str, Any]) -> str | None:
    head = pr.get("head") if isinstance(pr, dict) else {}
    if isinstance(head, dict) and isinstance(head.get("sha"), str):
        return head["sha"]
    return None


def run_head_sha(run: dict[str, Any]) -> str | None:
    value = run.get("head_sha") if isinstance(run, dict) else None
    return value if isinstance(value, str) and value else None


def run_matches_current_pr_head(run: dict[str, Any], pr: dict[str, Any]) -> bool:
    current_head = pr_head_sha(pr)
    observed_head = run_head_sha(run)
    if current_head is None or observed_head is None:
        return True
    return observed_head == current_head


def wait_for_merge_or_failed_run(client: GitHubClient, delivery: Delivery) -> tuple[dict[str, Any], dict[str, Any]] | None:
    deadline = time.monotonic() + poll_budget_seconds()
    latest_run: dict[str, Any] | None = None

    while True:
        if is_pr_merged(client, delivery):
            return None

        pr = get_pr(client, delivery)
        latest_run = latest_verify_run_for_pr(client, delivery)
        if latest_run is not None and latest_run.get("status") == "completed":
            conclusion = latest_run.get("conclusion")
            if conclusion not in ("success", "skipped"):
                if run_matches_current_pr_head(latest_run, pr):
                    if is_pr_merged(client, delivery):
                        return None
                    return pr, latest_run

        if time.monotonic() >= deadline:
            raise HookTerminate(
                f"Stop hook terminated: PR #{delivery.number} was not merged after polling every "
                f"{POLL_INTERVAL_SECONDS} seconds for {poll_budget_seconds()} seconds. "
                f"Last exact verify-blueprint run for this PR: {run_status_line(latest_run)}."
            )

        time.sleep(POLL_INTERVAL_SECONDS)


def merged_block_reason(client: GitHubClient, delivery: Delivery, workspace_dir: Path, pr: dict[str, Any], run: dict[str, Any]) -> str:
    runtime = load_runtime_context(workspace_dir, pr)
    bot_comment = get_bot_comment(client, delivery)
    log_path = write_failed_run_log_file(workspace_dir, client, delivery, run)
    return f"""You are now in CI-fix mode. The PR you opened failed verify-blueprint.

PR:       #{delivery.number}  {delivery.url}
Branch:   {runtime.branch}

--- verify-blueprint bot comment ---
{bot_comment}
-------------------------------------

--- verify-blueprint raw job logs ---
Full raw job logs for the failed CI run were saved to `{log_path}`.
This file is overwritten completely after each failed CI run; it is not an aggregation.
--------------------------------------

Task:
1. FIRST, call `mcp__git__git_set_working_dir` with `path={runtime.worktree_path}`
2. Read the bot comment above and `{log_path}` efficiently to diagnose the root cause.
3. Edit `{runtime.lean_file}` to address the failure. ONLY this file may change; every other path is blocked by the path-allowlist check in CI.
4. Commit with `mcp__git__git_add` + `mcp__git__git_commit`.
5. Push with `mcp__git__git_push`.
6. Exit with message "COMPLETE". The orchestrator will detect the new HEAD and re-poll CI.
"""


def run(workspace_dir: Path) -> int:
    _ = read_hook_input()
    delivery = validate_delivery(workspace_dir)
    client = GitHubClient(github_token())
    failed = wait_for_merge_or_failed_run(client, delivery)
    if failed is None:
        return 0
    pr, latest_run = failed
    raise HookBlock(merged_block_reason(client, delivery, workspace_dir, pr, latest_run))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--workspace-dir")
    args = parser.parse_args()
    _config_dir = Path(args.config_dir).resolve()
    workspace_dir = Path(args.workspace_dir).resolve() if args.workspace_dir else Path.cwd().resolve()

    try:
        return run(workspace_dir)
    except HookBlock as exc:
        return emit_block(exc.reason)
    except HookTerminate as exc:
        return emit_terminate(exc.reason)
    except Exception as exc:
        return emit_terminate(
            "Stop hook terminated: unexpected hook failure while checking delivery state. "
            f"{type(exc).__name__}: {exc}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
