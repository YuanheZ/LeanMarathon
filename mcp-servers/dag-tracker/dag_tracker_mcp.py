#!/usr/bin/env python3
"""MCP server for querying LeanArchitect blueprint dependency DAG context."""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any


SERVER_NAME = "dag-tracker"
SERVER_VERSION = "0.1.0"

DEFINITIONAL_KEYWORDS = frozenset({"def", "abbrev", "structure", "inductive", "class", "instance"})
PROOF_KEYWORDS = frozenset({"lemma", "theorem"})


class DagTrackerError(Exception):
    pass


@dataclass(frozen=True)
class ServerConfig:
    project_root: Path
    target_file: Path
    target_file_label: str
    verifier_path: Path


@dataclass(frozen=True)
class NodeRecord:
    lean_name: str
    label: str
    keyword: str
    latex_env: str
    line_decl: int
    line_attr: int
    order: int

    @property
    def line(self) -> int:
        return self.line_decl or self.line_attr


@dataclass
class GraphSnapshot:
    target_file: str
    nodes: list[NodeRecord]
    proof_nodes: list[NodeRecord]
    definitions: list[NodeRecord]
    by_name: dict[str, NodeRecord]
    deps_by_name: dict[str, set[str]]
    children_by_name: dict[str, set[str]]
    file_stat_key: tuple[int, int]
    dep_failures: list[str]


_SNAPSHOT: GraphSnapshot | None = None
_VERIFIER_MODULE: Any | None = None


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_under_root(project_root: Path, raw_path: str, description: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project_root / path
    try:
        resolved = path.resolve()
        root = project_root.resolve()
        resolved.relative_to(root)
    except ValueError as exc:
        raise DagTrackerError(f"{description} must stay inside DAG_PROJECT_ROOT: {raw_path}") from exc
    return resolved


def make_config() -> ServerConfig:
    project_root_raw = os.environ.get("DAG_PROJECT_ROOT")
    project_root = (
        Path(project_root_raw).expanduser().resolve()
        if project_root_raw
        else _default_project_root()
    )
    if not project_root.exists() or not project_root.is_dir():
        raise DagTrackerError(f"DAG_PROJECT_ROOT is not a directory: {project_root}")

    target_raw = (os.environ.get("DAG_TARGET_FILE") or "").strip()
    if not target_raw:
        raise DagTrackerError("DAG_TARGET_FILE is required")
    target_file = _resolve_under_root(project_root, target_raw, "DAG_TARGET_FILE")
    if not target_file.exists():
        raise DagTrackerError(f"DAG_TARGET_FILE does not exist: {target_file}")
    if not target_file.is_file():
        raise DagTrackerError(f"DAG_TARGET_FILE is not a file: {target_file}")

    verifier_path = project_root / ".scripts" / "verify_blueprint.py"
    if not verifier_path.exists():
        raise DagTrackerError(f"verify_blueprint.py was not found: {verifier_path}")

    return ServerConfig(
        project_root=project_root,
        target_file=target_file,
        target_file_label=target_raw,
        verifier_path=verifier_path,
    )


def load_verifier(config: ServerConfig) -> Any:
    global _VERIFIER_MODULE
    if _VERIFIER_MODULE is not None:
        return _VERIFIER_MODULE

    spec = importlib.util.spec_from_file_location("openclean_verify_blueprint", config.verifier_path)
    if spec is None or spec.loader is None:
        raise DagTrackerError(f"could not load verifier module from {config.verifier_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _VERIFIER_MODULE = module
    return module


class _Chdir:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.previous: str | None = None

    def __enter__(self) -> None:
        self.previous = os.getcwd()
        os.chdir(self.path)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.previous is not None:
            os.chdir(self.previous)


def _stat_key(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def dag_tracker_lean_threads() -> str | None:
    raw = (os.environ.get("DAG_TRACKER_LEAN_THREADS") or "").strip()
    if not raw:
        return None
    try:
        count = int(raw)
    except ValueError as exc:
        raise DagTrackerError("DAG_TRACKER_LEAN_THREADS must be a positive integer") from exc
    if count <= 0:
        raise DagTrackerError("DAG_TRACKER_LEAN_THREADS must be a positive integer")
    return raw


def build_snapshot(config: ServerConfig) -> GraphSnapshot:
    verifier = load_verifier(config)
    nodes_raw, anomalies = verifier.parse_file(config.target_file)
    # Parser anomalies are formatting/checker findings from verify_blueprint.py.
    # They do not necessarily prevent graph extraction, so this server keeps
    # dependency queries available unless the Lean elaborator probe itself fails.
    del anomalies

    records: list[NodeRecord] = []
    seen_names: set[str] = set()
    for order, node in enumerate(nodes_raw):
        lean_name = getattr(node, "lean_name", "")
        if not lean_name or lean_name in seen_names:
            continue
        seen_names.add(lean_name)
        records.append(
            NodeRecord(
                lean_name=lean_name,
                label=getattr(node, "label", ""),
                keyword=getattr(node, "keyword", ""),
                latex_env=getattr(node, "latex_env", ""),
                line_decl=getattr(node, "line_decl", 0),
                line_attr=getattr(node, "line_attr", 0),
                order=order,
            )
        )

    proof_nodes = [node for node in records if node.keyword in PROOF_KEYWORDS]
    definitions = [
        node
        for node in records
        if node.keyword in DEFINITIONAL_KEYWORDS and node.latex_env == "definition"
    ]
    proof_name_set = {node.lean_name for node in proof_nodes}

    threads = dag_tracker_lean_threads()
    old_threads = os.environ.get("VERIFY_BLUEPRINT_LEAN_THREADS")
    try:
        if threads is not None:
            os.environ["VERIFY_BLUEPRINT_LEAN_THREADS"] = threads
        with _Chdir(config.project_root):
            deps_by_name, dep_failures = verifier.extract_elaborated_proof_deps(
                [config.target_file],
                nodes_raw,
            )
    finally:
        if old_threads is None:
            os.environ.pop("VERIFY_BLUEPRINT_LEAN_THREADS", None)
        else:
            os.environ["VERIFY_BLUEPRINT_LEAN_THREADS"] = old_threads

    normalized_deps: dict[str, set[str]] = {node.lean_name: set() for node in proof_nodes}
    for name, deps in deps_by_name.items():
        if name in normalized_deps:
            normalized_deps[name] = {dep for dep in deps if dep in proof_name_set and dep != name}

    children_by_name: dict[str, set[str]] = {node.lean_name: set() for node in proof_nodes}
    for child, parents in normalized_deps.items():
        for parent in parents:
            children_by_name.setdefault(parent, set()).add(child)

    return GraphSnapshot(
        target_file=str(config.target_file),
        nodes=records,
        proof_nodes=proof_nodes,
        definitions=definitions,
        by_name={node.lean_name: node for node in records},
        deps_by_name=normalized_deps,
        children_by_name=children_by_name,
        file_stat_key=_stat_key(config.target_file),
        dep_failures=dep_failures,
    )


def snapshot(config: ServerConfig) -> GraphSnapshot:
    global _SNAPSHOT
    key = _stat_key(config.target_file)
    if _SNAPSHOT is None or _SNAPSHOT.file_stat_key != key:
        _SNAPSHOT = build_snapshot(config)
    if _SNAPSHOT.dep_failures:
        details = "\n".join(_SNAPSHOT.dep_failures)
        raise DagTrackerError(f"could not build blueprint dependency DAG:\n{details}")
    return _SNAPSHOT


def require_proof_node(graph: GraphSnapshot, lean_name: str) -> NodeRecord:
    target = graph.by_name.get(lean_name)
    if target is None:
        raise DagTrackerError(
            f"'{lean_name}' is not a blueprint node in: {graph.target_file}"
        )
    if target.keyword not in PROOF_KEYWORDS:
        raise DagTrackerError(
            f"'{lean_name}' is a {target.keyword or 'non-proof'} node in: "
            f"{graph.target_file}; expected lemma or theorem"
        )
    return target


def ordered_names(names: set[str], graph: GraphSnapshot) -> list[str]:
    return [
        node.lean_name
        for node in sorted(
            (graph.by_name[name] for name in names if name in graph.by_name),
            key=lambda node: node.order,
        )
    ]


def visibility(anchor: NodeRecord, node: NodeRecord) -> str:
    return "visible" if node.order < anchor.order else "invisible"


def descendants_of(target_name: str, graph: GraphSnapshot) -> set[str]:
    descendants: set[str] = set()
    stack = list(graph.children_by_name.get(target_name, set()))
    while stack:
        name = stack.pop()
        if name in descendants:
            continue
        descendants.add(name)
        stack.extend(graph.children_by_name.get(name, set()))
    return descendants


def node_payload(node: NodeRecord, *, include_keyword: bool = False, visibility_class: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "lean_name": node.lean_name,
        "label": node.label,
        "line": node.line,
    }
    if include_keyword:
        payload["keyword"] = node.keyword
    if visibility_class is not None:
        payload["visibility"] = visibility_class
    return payload


def get_admissible_external_nodes(graph: GraphSnapshot, lean_name: str) -> dict[str, Any]:
    target = require_proof_node(graph, lean_name)
    inadmissible = descendants_of(target.lean_name, graph)
    entries = [
        node_payload(node, visibility_class=visibility(target, node))
        for node in graph.proof_nodes
        if node.lean_name != target.lean_name and node.lean_name not in inadmissible
    ]
    return {
        "target": target.lean_name,
        "admissible_external_nodes": entries,
        "count": len(entries),
    }


def get_parent_nodes(graph: GraphSnapshot, lean_name: str) -> dict[str, Any]:
    target = require_proof_node(graph, lean_name)
    names = ordered_names(graph.deps_by_name.get(target.lean_name, set()), graph)
    return {"target": target.lean_name, "parent_nodes": names, "count": len(names)}


def get_child_nodes(graph: GraphSnapshot, lean_name: str) -> dict[str, Any]:
    target = require_proof_node(graph, lean_name)
    names = ordered_names(graph.children_by_name.get(target.lean_name, set()), graph)
    return {"target": target.lean_name, "child_nodes": names, "count": len(names)}


def get_global_definitional_context(graph: GraphSnapshot, lean_name: str) -> dict[str, Any]:
    target = require_proof_node(graph, lean_name)
    entries = [
        node_payload(
            node,
            include_keyword=True,
            visibility_class=visibility(target, node),
        )
        for node in graph.definitions
    ]
    return {
        "target": target.lean_name,
        "global_definitional_context": entries,
        "count": len(entries),
    }


def format_result(result: dict[str, Any]) -> str:
    if "admissible_external_nodes" in result:
        entries = result["admissible_external_nodes"]
        if not entries:
            return f"{result['target']}: no admissible external nodes."
        lines = [f"{result['target']}: admissible external nodes ({len(entries)}):"]
        lines.extend(f"- {entry['lean_name']} ({entry['visibility']})" for entry in entries)
        return "\n".join(lines)
    if "parent_nodes" in result:
        entries = result["parent_nodes"]
        if not entries:
            return f"{result['target']}: no parent nodes."
        return f"{result['target']}: parent nodes:\n" + "\n".join(f"- {name}" for name in entries)
    if "child_nodes" in result:
        entries = result["child_nodes"]
        if not entries:
            return f"{result['target']}: no child nodes."
        return f"{result['target']}: child nodes:\n" + "\n".join(f"- {name}" for name in entries)
    if "global_definitional_context" in result:
        entries = result["global_definitional_context"]
        if not entries:
            return f"{result['target']}: no global definitional context nodes."
        lines = [f"{result['target']}: global definitional context ({len(entries)}):"]
        lines.extend(
            f"- {entry['lean_name']} ({entry['keyword']}, {entry['visibility']})"
            for entry in entries
        )
        return "\n".join(lines)
    return json.dumps(result, indent=2)


def tool_schemas() -> list[dict[str, Any]]:
    lean_name_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "lean_name": {
                "type": "string",
                "description": "Lean name of one blueprint lemma/theorem node in DAG_TARGET_FILE.",
            }
        },
        "required": ["lean_name"],
    }
    return [
        {
            "name": "admissible_external_nodes",
            "description": (
                "Return proof nodes admissible for locally refining the target. "
                "Visibility is classified by whether the external node is declared before the target node."
            ),
            "inputSchema": lean_name_schema,
        },
        {
            "name": "parent_nodes",
            "description": "Return the target proof node's direct upstream proof dependencies.",
            "inputSchema": lean_name_schema,
        },
        {
            "name": "child_nodes",
            "description": "Return proof nodes that directly depend on the target proof node.",
            "inputSchema": lean_name_schema,
        },
        {
            "name": "global_definitional_context",
            "description": (
                "Return all blueprint definitional nodes with latexEnv := \"definition\", "
                "classified as visible or invisible relative to the target declaration."
            ),
            "inputSchema": lean_name_schema,
        },
    ]


def handle_tool_call(name: str, arguments: dict[str, Any], config: ServerConfig) -> dict[str, Any]:
    lean_name = arguments.get("lean_name")
    if not isinstance(lean_name, str) or not lean_name.strip():
        raise DagTrackerError("tool argument 'lean_name' must be a non-empty string")
    lean_name = lean_name.strip()
    graph = snapshot(config)

    if name == "admissible_external_nodes":
        result = get_admissible_external_nodes(graph, lean_name)
    elif name == "parent_nodes":
        result = get_parent_nodes(graph, lean_name)
    elif name == "child_nodes":
        result = get_child_nodes(graph, lean_name)
    elif name == "global_definitional_context":
        result = get_global_definitional_context(graph, lean_name)
    else:
        raise DagTrackerError(f"unknown tool: {name}")

    return {
        "content": [{"type": "text", "text": format_result(result)}],
        "structuredContent": result,
    }


def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def result_response(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def error_response(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def serve() -> int:
    try:
        config = make_config()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        config = None
        startup_error = str(exc)
    else:
        startup_error = None

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            emit(error_response(None, -32700, f"invalid JSON: {exc}"))
            continue

        message_id = message.get("id")
        method = message.get("method")
        try:
            if method == "initialize":
                params = message.get("params") or {}
                protocol_version = params.get("protocolVersion") or "2024-11-05"
                emit(
                    result_response(
                        message_id,
                        {
                            "protocolVersion": protocol_version,
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                        },
                    )
                )
            elif method == "notifications/initialized":
                continue
            elif method == "ping":
                emit(result_response(message_id, {}))
            elif method == "tools/list":
                emit(result_response(message_id, {"tools": tool_schemas()}))
            elif method == "tools/call":
                if startup_error is not None or config is None:
                    raise DagTrackerError(startup_error or "server configuration failed")
                params = message.get("params") or {}
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if not isinstance(name, str):
                    raise DagTrackerError("tools/call param 'name' must be a string")
                if not isinstance(arguments, dict):
                    raise DagTrackerError("tools/call param 'arguments' must be an object")
                try:
                    emit(result_response(message_id, handle_tool_call(name, arguments, config)))
                except DagTrackerError as exc:
                    emit(
                        result_response(
                            message_id,
                            {
                                "content": [{"type": "text", "text": f"Error: {exc}"}],
                                "isError": True,
                            },
                        )
                    )
            elif method == "resources/list":
                emit(result_response(message_id, {"resources": []}))
            elif method == "prompts/list":
                emit(result_response(message_id, {"prompts": []}))
            elif method is None:
                emit(error_response(message_id, -32600, "missing method"))
            elif message_id is None:
                continue
            else:
                emit(error_response(message_id, -32601, f"method not found: {method}"))
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            emit(error_response(message_id, -32603, str(exc)))
    return 0


def _run_self_test() -> int:
    nodes = [
        NodeRecord("a", "lem:a", "lemma", "lemma", 1, 1, 0),
        NodeRecord("b", "lem:b", "lemma", "lemma", 2, 2, 1),
        NodeRecord("c", "thm:c", "theorem", "theorem", 3, 3, 2),
        NodeRecord("d", "lem:d", "lemma", "lemma", 4, 4, 3),
        NodeRecord("foo", "def:foo", "def", "definition", 0, 5, 4),
    ]
    proof_nodes = nodes[:4]
    deps_by_name = {"a": set(), "b": {"a"}, "c": {"b"}, "d": set()}
    children_by_name = {"a": {"b"}, "b": {"c"}, "c": set(), "d": set()}
    graph = GraphSnapshot(
        target_file="self-test.lean",
        nodes=nodes,
        proof_nodes=proof_nodes,
        definitions=[nodes[4]],
        by_name={node.lean_name: node for node in nodes},
        deps_by_name=deps_by_name,
        children_by_name=children_by_name,
        file_stat_key=(0, 0),
        dep_failures=[],
    )
    assert get_parent_nodes(graph, "c")["parent_nodes"] == ["b"]
    assert get_child_nodes(graph, "b")["child_nodes"] == ["c"]
    admissible = get_admissible_external_nodes(graph, "b")["admissible_external_nodes"]
    assert [entry["lean_name"] for entry in admissible] == ["a", "d"]
    assert [entry["visibility"] for entry in admissible] == ["visible", "invisible"]
    defs = get_global_definitional_context(graph, "b")["global_definitional_context"]
    assert defs == [
        {
            "lean_name": "foo",
            "label": "def:foo",
            "line": 5,
            "keyword": "def",
            "visibility": "invisible",
        }
    ]
    print("self-test passed", file=sys.stderr)
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        return _run_self_test()
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
