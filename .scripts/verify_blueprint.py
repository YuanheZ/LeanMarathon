#!/usr/bin/env python3
"""Verifier for LeanMarathon LeanArchitect blueprint files.

Implements the seven algorithmic checks in verification.md. Definitional nodes
(`def`, `abbrev`, `structure`, `inductive`, `class`, `instance`) are treated as
global context and excluded from the proof DAG. `axiom`, `example`, `opaque`
are banned at the source level.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFINITIONAL_KEYWORDS = frozenset({"def", "abbrev", "structure", "inductive", "class", "instance"})
PROOF_KEYWORDS = frozenset({"lemma", "theorem"})
ALLOWED_DECL_KEYWORDS = DEFINITIONAL_KEYWORDS | PROOF_KEYWORDS
BANNED_DECL_KEYWORDS = frozenset({"axiom", "example", "opaque"})

PREFIX_TO_LATEX_ENV = {"def": "definition", "lem": "lemma", "thm": "theorem"}
KEYWORD_TO_LATEX_ENV: dict[str, str] = {
    **{kw: "definition" for kw in DEFINITIONAL_KEYWORDS},
    "lemma": "lemma",
    "theorem": "theorem",
}
ALLOWED_LATEX_ENV = {"definition", "lemma", "theorem"}


def lean_project_cwd() -> Path:
    for env_name in ("VERIFY_BLUEPRINT_LEAN_PROJECT_ROOT", "ORCHESTRATOR_LEAN_PROJECT_ROOT"):
        raw = os.environ.get(env_name)
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_dir():
            return path.resolve()
    return Path.cwd()


@dataclass
class Node:
    file: str
    label: str
    statement: str
    title: str
    proof: Optional[str]
    latex_env: str
    keyword: str
    lean_name: str
    sorry_uses: list[str]
    cref_labels: list[str]
    line_attr: int
    line_decl: int
    attr_start_offset: int = 0
    decl_end_offset: int = 0
    body_content_end_offset: int = 0
    decl_signature_text: str = ""
    proof_body_text: str = ""
    sorry_using_raw_args: Optional[str] = None
    body_kind: str = ""  # "by_sorry" | "by_sorry_using" | "complete" | "invalid" | ""
    body_invalid_reason: Optional[str] = None
    duplicate_fields: list[str] = field(default_factory=list)
    statement_cref_labels: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    name: str
    passed: bool
    failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _skip_block_comment(text: str, start: int) -> int:
    """Skip a Lean 4 block comment at offset `start` (which must be `/-`).
    Lean 4 block comments (`/- ... -/` and `/-- ... -/`) NEST — we must
    track depth and consume up to the matching `-/`. Returns the position
    just after the closing `-/`, or `len(text)` if unclosed."""
    depth = 1
    i = start + 2
    n = len(text)
    while i < n and depth > 0:
        if text.startswith("/-", i):
            depth += 1
            i += 2
        elif text.startswith("-/", i):
            depth -= 1
            i += 2
        else:
            i += 1
    return i


def skip_comments_and_ws(text: str, i: int) -> int:
    while i < len(text):
        if text[i] in " \t\n\r":
            i += 1
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = j + 1 if j != -1 else len(text)
            continue
        if text.startswith("/-", i) and not text.startswith("/--", i):
            i = _skip_block_comment(text, i)
            continue
        break
    return i


def find_balanced(text: str, start: int, opener: str, closer: str) -> int:
    """Return the index of the matching `closer` for the `opener` at `start`.

    Skips Lean docstrings (/-- ... -/), block comments (/- ... -/), line
    comments (-- ...), and string literals.
    """
    assert text[start] == opener
    depth = 1
    i = start + 1
    while i < len(text):
        ch = text[i]
        if text.startswith("/-", i):
            i = _skip_block_comment(text, i)
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = j + 1 if j != -1 else len(text)
            continue
        if ch == '"':
            j = i + 1
            while j < len(text) and text[j] != '"':
                if text[j] == "\\" and j + 1 < len(text):
                    j += 2
                else:
                    j += 1
            i = j + 1
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"Unbalanced '{opener}' at offset {start}")


def parse_attr_body(body: str) -> tuple[dict[str, str], list[str]]:
    """Extract `(name := value)` pairs from a blueprint attribute body.

    Returns (fields, duplicate_names) where duplicate_names lists every field
    name that appeared more than once (last-wins semantics for the value, but
    the duplication itself is reported as a Check 2 failure)."""
    fields: dict[str, str] = {}
    duplicates: list[str] = []
    i = 0
    while i < len(body):
        if body[i] != "(":
            i += 1
            continue
        end = find_balanced(body, i, "(", ")")
        inner = body[i + 1 : end].strip()
        m = re.match(r"(\w+)\s*:=\s*(.*)", inner, re.DOTALL)
        if m:
            name, value = m.group(1), m.group(2).strip()
            if value.startswith("/--") and value.endswith("-/"):
                value = value[3:-2].strip()
            elif len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                value = value[1:-1]
            if name in fields and name not in duplicates:
                duplicates.append(name)
            fields[name] = value
        i = end + 1
    return fields, duplicates


_DECL_KEYWORDS: tuple[str, ...] = (
    "theorem", "lemma",
    "def", "abbrev", "structure", "inductive", "class", "instance",
)
_MODIFIERS = (
    "noncomputable", "private", "protected",
    "unsafe", "partial", "nonrec", "scoped", "local",
)


def parse_decl(text: str, start: int) -> Optional[tuple[str, str, int]]:
    """Find the first allowed declaration keyword after `start` and return
    (keyword, lean_name, line_decl). Skip Lean modifiers like `noncomputable`
    and skip over additional non-blueprint `@[...]` attributes.
    If the declaration has no identifier (anonymous `instance`), returns an
    empty `lean_name`; Check 2 will flag that as anonymous."""
    i = skip_comments_and_ws(text, start)
    while True:
        skipped = False
        for mod in _MODIFIERS:
            if text.startswith(mod, i) and (
                i + len(mod) >= len(text) or text[i + len(mod)] in " \t\n\r"
            ):
                i += len(mod)
                i = skip_comments_and_ws(text, i)
                skipped = True
                break
        if not skipped and text.startswith("@[", i):
            try:
                close = find_balanced(text, i + 1, "[", "]")
                i = close + 1
                i = skip_comments_and_ws(text, i)
                skipped = True
            except ValueError:
                pass
        if not skipped:
            break
    for kw in _DECL_KEYWORDS:
        if text.startswith(kw, i) and (
            i + len(kw) >= len(text) or text[i + len(kw)] in " \t\n\r"
        ):
            line_decl = line_of_offset(text, i)
            j = i + len(kw)
            while j < len(text) and text[j] in " \t":
                j += 1
            name_start = j
            # Read first identifier segment.
            while j < len(text) and (text[j].isalnum() or text[j] in "_'"):
                j += 1
            # Allow dotted continuations like `Bar.foo`. Only consume `.` if
            # the character after it begins another identifier segment — this
            # excludes universe-binder syntax `def foo.{u}`.
            while (
                j + 1 < len(text)
                and text[j] == "."
                and (text[j + 1].isalpha() or text[j + 1] == "_")
            ):
                j += 1  # consume the dot
                while j < len(text) and (text[j].isalnum() or text[j] in "_'"):
                    j += 1
            return kw, text[name_start:j], line_decl
    return None


def find_decl_body_range(text: str, decl_offset: int) -> tuple[int, int]:
    """Return (body_start, body_end) for the proof/value of the declaration
    that starts at `decl_offset` (offset of the keyword)."""
    # Cap the `:=` search at the next top-level construct so we don't pick
    # up a `:=` belonging to a downstream declaration. Matters for
    # `structure` / `class` / `inductive` nodes which have no `:=` of their
    # own (they use `where` / `|` syntax instead).
    decl_end = _find_top_level_break(text, decl_offset + 1)
    i = decl_offset
    paren = 0
    while i < decl_end:
        if text.startswith("/-", i):
            i = _skip_block_comment(text, i)
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = j + 1 if j != -1 else len(text)
            continue
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < len(text) and text[j] != '"':
                if text[j] == "\\" and j + 1 < len(text):
                    j += 2
                else:
                    j += 1
            i = j + 1
            continue
        if ch in "({[":
            paren += 1
        elif ch in ")}]":
            paren = max(0, paren - 1)
        elif paren == 0 and text.startswith(":=", i):
            body_start = i + 2
            body_end = _find_top_level_break(text, body_start)
            return body_start, body_end
        i += 1
    return decl_offset, decl_offset


_TOP_LEVEL_BREAK_KEYWORDS = _DECL_KEYWORDS + _MODIFIERS + (
    "end", "namespace", "section", "import", "open", "set_option",
    "variable", "universe", "attribute",
)


def _find_top_level_break(text: str, start: int) -> int:
    """Walk forward from `start` until we hit the next top-level structural
    construct (column 0): an `@[...]` attribute, a declaration keyword, or a
    structural command like `end`/`namespace`/`section`/`import`/etc.
    Returns the offset of the break."""
    i = start
    while i < len(text):
        if text[i] == "\n":
            j = i + 1
            if j >= len(text):
                return j
            if text[j] in (" ", "\t"):
                i += 1
                continue
            if text.startswith("@[", j):
                return j
            for kw in _TOP_LEVEL_BREAK_KEYWORDS:
                if text.startswith(kw, j) and (
                    j + len(kw) >= len(text) or text[j + len(kw)] in " \t\n\r"
                ):
                    return j
        i += 1
    return len(text)


_BLUEPRINT_HEAD = re.compile(r"@\[blueprint\s+\"([^\"]+)\"")
_ATTR_OPEN_RE = re.compile(r"@\[")
_BLUEPRINT_TOKEN_RE = re.compile(r"\bblueprint\s+\"([^\"]+)\"")


def mask_comments_only(text: str) -> str:
    """Mask Lean block comments (including nested) and line comments with
    spaces; preserve string-literal contents (needed to read the blueprint
    label string from inside `@[blueprint "..."]`)."""
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("/-", i):
            end = _skip_block_comment(text, i)
            for k in range(i, end):
                if out[k] != "\n":
                    out[k] = " "
            i = end
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            end = j if j != -1 else n
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 1
            i = j + 1
            continue
        i += 1
    return "".join(out)

_CREF_RE = re.compile(r"\\[Cc]ref\{([^}]+)\}")

_SORRY_LIKE_RE = re.compile(
    r"(?<![A-Za-z0-9_'])sorry(?:_using)?(?![A-Za-z0-9_'])"
)
_BY_SORRY_RE = re.compile(r"\Aby\s+sorry\Z", re.DOTALL)
_BY_SORRY_USING_RE = re.compile(r"\Aby\s+sorry_using\s*\[[^\]]*\]\Z", re.DOTALL)
_PLACEHOLDER_LAYOUT_REASON = (
    "placeholder proofs must put `sorry` or `sorry_using [...]` on a separate "
    "indented line after a standalone `by`; same-line forms like "
    "`:= by sorry` and `:= by sorry_using [...]` are not allowed"
)


def strip_lean_comments(text: str) -> str:
    """Remove Lean block comments (including nested `/- /- inner -/ -/`),
    docstrings, line comments, and string literal contents. Used as a
    pre-pass for `sorry`-token detection and body-scan dep extraction so
    that tokens inside comments/strings do not trigger false positives."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("/-", i):
            i = _skip_block_comment(text, i)
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = j if j != -1 else n
            continue
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 1
            i = j + 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def placeholder_has_standalone_by_line(body: str) -> bool:
    """Check the formatting discipline for canonical placeholder proofs.

    `find_decl_body_range` returns text beginning immediately after `:=`.  For
    worker-boundary safety, a placeholder proof must look like:

        := by
          sorry

    not:

        := by sorry
    """
    for line in strip_lean_comments(body).splitlines():
        stripped = line.strip()
        if stripped:
            return stripped == "by"
    return False


def classify_proof_body(body: str) -> tuple[str, Optional[str]]:
    """Return (kind, reason) for a `lemma`/`theorem` proof body.

    kind ∈ {"by_sorry", "by_sorry_using", "complete", "invalid"}.
    The body is "complete" only if it contains no `sorry` and no `sorry_using`
    token. Otherwise it must match one of the two canonical placeholder forms.
    """
    cleaned = strip_lean_comments(body).strip()
    if not _SORRY_LIKE_RE.search(cleaned):
        return "complete", None
    if _BY_SORRY_RE.match(cleaned):
        if not placeholder_has_standalone_by_line(body):
            return "invalid", _PLACEHOLDER_LAYOUT_REASON
        return "by_sorry", None
    if _BY_SORRY_USING_RE.match(cleaned):
        if not placeholder_has_standalone_by_line(body):
            return "invalid", _PLACEHOLDER_LAYOUT_REASON
        return "by_sorry_using", None
    return "invalid", (
        "body contains `sorry` or `sorry_using` but is not exactly "
        "`by sorry` or `by sorry_using [...]` (mixed/multiple sorry forms "
        "and term-mode `sorry` are not allowed)"
    )


def has_sorry_token(text: str) -> bool:
    """Check whether `text` contains a `sorry` or `sorry_using` token outside
    comments. Used to enforce that definitional nodes are complete."""
    return bool(_SORRY_LIKE_RE.search(strip_lean_comments(text)))


def sorry_using_args_have_comment(args_raw: str) -> bool:
    """Detect comments inside the captured `sorry_using [...]` argument list."""
    return "/-" in args_raw or "--" in args_raw


def extract_cref_labels(text: str) -> list[str]:
    """Extract every label cited via `\\cref{...}` or `\\Cref{...}`. Splits on
    commas inside the braces so `\\cref{lem:a, lem:b}` yields two labels."""
    labels: list[str] = []
    for m in _CREF_RE.finditer(text):
        for raw in m.group(1).split(","):
            label = raw.strip()
            if label:
                labels.append(label)
    return labels


def mask_comments_and_strings(text: str) -> str:
    """Replace the interiors of Lean block comments (including nested),
    docstrings, line comments, and string literals with spaces, preserving
    line breaks and offsets. Length-preserving so offsets match raw text."""
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("/-", i):
            end = _skip_block_comment(text, i)
            for k in range(i, end):
                if out[k] != "\n":
                    out[k] = " "
            i = end
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            end = j if j != -1 else n
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 1
            end = min(j + 1, n)
            for k in range(i, end):
                if out[k] != "\n":
                    out[k] = " "
            i = end
            continue
        i += 1
    return "".join(out)


_MUTUAL_RE = re.compile(r"^mutual\b", re.MULTILINE)
_NAMESPACE_RE = re.compile(r"^namespace\b", re.MULTILINE)
_TOP_LEVEL_BARE_DECL_RE = re.compile(
    r"^(?:@\[[^\]]*\][ \t]*)*"
    r"(?:(?:noncomputable|private|protected|unsafe|partial|nonrec|scoped|local)[ \t]+)*"
    r"(theorem|lemma|def|abbrev|structure|inductive|class|instance|axiom|example|opaque)\b",
    re.MULTILINE,
)


def scan_anomalies(masked: str, path: Path, nodes: list[Node]) -> list[str]:
    """Flag top-level declarations that (a) use a banned keyword, (b) lack a
    preceding `@[blueprint]` attribute, or (c) appear inside a `mutual` block.
    Operates on the masked text so tokens inside comments/docstrings/strings
    are ignored."""
    anomalies: list[str] = []
    decl_lines = {n.line_decl for n in nodes if n.line_decl}
    seen_lines: set[int] = set()
    for m in _TOP_LEVEL_BARE_DECL_RE.finditer(masked):
        keyword = m.group(1)
        line = masked.count("\n", 0, m.start()) + 1
        if line in seen_lines:
            continue
        seen_lines.add(line)
        loc = f"{path}:{line}"
        if keyword in BANNED_DECL_KEYWORDS:
            anomalies.append(
                f"{loc}: '{keyword}' declarations are not allowed in blueprint files"
            )
        elif line not in decl_lines:
            anomalies.append(
                f"{loc}: top-level '{keyword}' has no preceding @[blueprint] attribute"
            )
    for m in _MUTUAL_RE.finditer(masked):
        line = masked.count("\n", 0, m.start()) + 1
        anomalies.append(
            f"{path}:{line}: 'mutual' blocks are not allowed in blueprint files "
            f"(every node must be a single top-level declaration with @[blueprint])"
        )
    for m in _NAMESPACE_RE.finditer(masked):
        line = masked.count("\n", 0, m.start()) + 1
        anomalies.append(
            f"{path}:{line}: 'namespace' blocks are not allowed in blueprint files "
            f"(use top-level declarations with fully descriptive names; use "
            f"`local instance` for non-leaking typeclass instances)"
        )
    return anomalies


def scan_node_spacing(text: str, path: Path, nodes: list[Node]) -> list[str]:
    """Require a blank separator line between consecutive blueprint nodes."""
    failures: list[str] = []
    for prev, cur in zip(nodes, nodes[1:]):
        if not prev.keyword or not cur.keyword:
            continue
        gap = text[prev.body_content_end_offset : cur.attr_start_offset]
        if not re.search(r"\n[ \t]*\n", gap):
            failures.append(
                f"{path}:{cur.line_attr}: blueprint node '{cur.label}' must be "
                f"separated from previous node '{prev.label}' by at least one blank line"
            )
    return failures


def parse_file(path: Path) -> tuple[list[Node], list[str]]:
    text = path.read_text()
    masked_for_attrs = mask_comments_only(text)
    nodes: list[Node] = []
    seen_attr_starts: set[int] = set()
    for m in _ATTR_OPEN_RE.finditer(masked_for_attrs):
        attr_start = m.start()
        if attr_start in seen_attr_starts:
            continue
        seen_attr_starts.add(attr_start)
        bracket_open = attr_start + 1  # position of '['
        try:
            bracket_close = find_balanced(text, bracket_open, "[", "]")
        except ValueError:
            continue
        body = text[bracket_open + 1 : bracket_close]
        bm = _BLUEPRINT_TOKEN_RE.search(body)
        if not bm:
            continue
        label = bm.group(1)
        fields, duplicate_fields = parse_attr_body(body)

        decl = parse_decl(text, bracket_close + 1)
        if decl is None:
            nodes.append(
                Node(
                    file=str(path),
                    label=label,
                    statement=fields.get("statement", ""),
                    title=fields.get("title", ""),
                    proof=fields.get("proof"),
                    latex_env=fields.get("latexEnv", ""),
                    keyword="",
                    lean_name="",
                    sorry_uses=[],
                    cref_labels=[],
                    line_attr=line_of_offset(text, attr_start),
                    line_decl=0,
                    duplicate_fields=duplicate_fields,
                    statement_cref_labels=extract_cref_labels(fields.get("statement", "")),
                )
            )
            continue
        keyword, lean_name, line_decl = decl
        decl_offset = text.find(keyword, bracket_close + 1)
        body_start, body_end = find_decl_body_range(text, decl_offset)
        decl_end = _find_top_level_break(text, decl_offset + 1)
        body_content_end = decl_end
        while body_content_end > decl_offset and text[body_content_end - 1] in " \t\n\r":
            body_content_end -= 1
        proof_body = text[body_start:body_end]
        signature_text = text[decl_offset:body_start] if body_start > decl_offset else ""

        proof_text = fields.get("proof")
        statement_text = fields.get("statement", "")
        cref_labels = extract_cref_labels(proof_text) if proof_text else []
        statement_cref_labels = extract_cref_labels(statement_text)

        if keyword in PROOF_KEYWORDS:
            body_kind, body_invalid_reason = classify_proof_body(proof_body)
        else:
            body_kind, body_invalid_reason = "", None

        # `sorry_using` extraction is restricted to bodies that classify as
        # `by_sorry_using`. This prevents two leakage bugs:
        # (1) complete-proof bodies with `-- sorry_using [foo]` in a comment,
        #     and (2) definitional bodies with the literal text
        #     `"sorry_using [foo]"` inside a string literal. Both would
        #     otherwise pollute the DAG with phantom edges.
        # For Rule-3 raw-args extraction we use a length-preserving mask of
        # comments so the regex finds the *canonical* `sorry_using [...]` and
        # not a commented-out one that happens to appear earlier in the body.
        sorry_uses: list[str] = []
        sorry_using_args_raw: Optional[str] = None
        if body_kind == "by_sorry_using":
            cleaned_body = strip_lean_comments(proof_body)
            sm_clean = re.search(
                r"sorry_using\s*\[(?P<args>[^\]]*)\]", cleaned_body, re.DOTALL
            )
            if sm_clean:
                sorry_uses = [
                    s.strip() for s in sm_clean.group("args").split(",") if s.strip()
                ]
            masked_body = mask_comments_only(proof_body)
            sm_masked = re.search(r"sorry_using\s*\[", masked_body)
            if sm_masked:
                open_pos = sm_masked.end() - 1
                try:
                    close_pos = find_balanced(proof_body, open_pos, "[", "]")
                    sorry_using_args_raw = proof_body[open_pos + 1 : close_pos]
                except ValueError:
                    sorry_using_args_raw = None

        nodes.append(
            Node(
                file=str(path),
                label=label,
                statement=fields.get("statement", ""),
                title=fields.get("title", ""),
                proof=proof_text,
                latex_env=fields.get("latexEnv", ""),
                keyword=keyword,
                lean_name=lean_name,
                sorry_uses=sorry_uses,
                cref_labels=cref_labels,
                line_attr=line_of_offset(text, attr_start),
                line_decl=line_decl,
                attr_start_offset=attr_start,
                decl_end_offset=decl_end,
                body_content_end_offset=body_content_end,
                decl_signature_text=signature_text,
                proof_body_text=proof_body,
                sorry_using_raw_args=sorry_using_args_raw,
                body_kind=body_kind,
                body_invalid_reason=body_invalid_reason,
                duplicate_fields=duplicate_fields,
                statement_cref_labels=statement_cref_labels,
            )
        )
    masked = mask_comments_and_strings(text)
    anomalies = scan_anomalies(masked, path, nodes)
    anomalies.extend(scan_node_spacing(text, path, nodes))
    return nodes, anomalies


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

_LEAN_MSG_RE = re.compile(
    # Lean 4 emits either `error:` or `error(lean.someErrorCode):`. Allow an
    # optional `(code)` between severity word and colon. Same for `warning`.
    r":\s*\d+:\d+:\s*(error|warning)(?:\([^)]*\))?:",
    re.IGNORECASE,
)
_FREESTANDING_FAILURE_RE = re.compile(
    # Lean/lake/kernel failures without file:line:col prefix:
    r"(?:^\s*(?:PANIC|panic|fatal\s*error|lake:\s*error|error:))"
    # Shell/tool failures (missing executable, etc.):
    r"|(?::\s*command\s+not\s+found\s*$)",
    re.IGNORECASE,
)


def check_compilation(build_log: Optional[Path]) -> CheckResult:
    if build_log is None:
        return CheckResult(
            "Check 1: Lean Compilation",
            True,
            ["(skipped: no --build-log provided)"],
        )
    if not build_log.exists():
        return CheckResult(
            "Check 1: Lean Compilation",
            False,
            [f"build log {build_log} does not exist"],
        )
    if build_log.is_dir():
        return CheckResult(
            "Check 1: Lean Compilation",
            False,
            [f"build log path is a directory, not a file: {build_log}"],
        )
    log_text = build_log.read_text(errors="replace")
    bad: list[str] = []
    lines = log_text.splitlines()
    in_msg = False
    accum: list[str] = []
    for line in lines:
        # Freestanding failures (PANIC, lake errors, etc.) without file:line
        # prefix are caught in addition to Lean's structured warnings/errors.
        if _FREESTANDING_FAILURE_RE.search(line) and not _LEAN_MSG_RE.search(line):
            if in_msg and accum:
                _maybe_record(accum, bad)
                accum = []
                in_msg = False
            bad.append(line)
            continue
        is_header = bool(_LEAN_MSG_RE.search(line))
        if is_header:
            if in_msg and accum:
                _maybe_record(accum, bad)
            accum = [line]
            in_msg = True
        elif in_msg:
            if line.startswith(" ") or line.startswith("\t") or line == "":
                accum.append(line)
            else:
                _maybe_record(accum, bad)
                accum = []
                in_msg = False
    if in_msg and accum:
        _maybe_record(accum, bad)
    if bad:
        return CheckResult(
            "Check 1: Lean Compilation",
            False,
            ["Lean compilation produced non-sorry diagnostics:"] + bad,
        )
    return CheckResult("Check 1: Lean Compilation", True)


_SORRY_LINE_RE = re.compile(
    # Tolerate optional `(code)` suffix on the warning marker for forward
    # compatibility with future Lean versions that may add error codes.
    r"^[^:]+:\d+:\d+:\s*warning(?:\([^)]*\))?:\s*declaration uses [`']sorry[`']\s*$"
)


def _maybe_record(msg_lines: list[str], bad: list[str]) -> None:
    """A sorry warning must be exactly a single line of the form
    `<file>:<line>:<col>: warning: declaration uses ['`]sorry[`']` with no
    continuation. Multi-line messages whose body happens to contain the sorry
    phrase are NOT whitelisted."""
    if len(msg_lines) == 1 and _SORRY_LINE_RE.match(msg_lines[0]):
        return
    bad.append("\n".join(msg_lines))


def _braces_balanced(text: str) -> bool:
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def check_node_well_formedness(
    nodes: list[Node], anomalies: list[str]
) -> CheckResult:
    failures: list[str] = list(anomalies)
    for n in nodes:
        loc = f"{n.file}:{n.line_attr}"
        if not n.keyword:
            failures.append(
                f"{loc}: blueprint label '{n.label}' has no following declaration"
            )
            continue
        if not n.lean_name:
            failures.append(
                f"{loc}: '{n.label}' is an anonymous {n.keyword} "
                f"(blueprint nodes must be named; anonymous `instance` is forbidden)"
            )
        if not n.statement.strip():
            failures.append(f"{loc}: '{n.label}' has empty (statement := /-- ... -/)")
        if not n.title.strip():
            failures.append(f"{loc}: '{n.label}' has empty (title := /-- ... -/)")
        if n.keyword in PROOF_KEYWORDS:
            if not n.proof or not n.proof.strip():
                failures.append(
                    f"{loc}: '{n.label}' is a {n.keyword} but has empty (proof := /-- ... -/)"
                )
        for fld_name, fld in (
            ("statement", n.statement),
            ("title", n.title),
            ("proof", n.proof or ""),
        ):
            if fld.strip() and not _braces_balanced(fld):
                failures.append(
                    f"{loc}: '{n.label}' has unbalanced LaTeX braces in {fld_name}"
                )
        decl_loc = f"{n.file}:{n.line_decl or n.line_attr}"
        if n.keyword in PROOF_KEYWORDS and n.body_kind == "invalid":
            failures.append(
                f"{decl_loc}: '{n.label}' has invalid proof body — {n.body_invalid_reason}. "
                f"A {n.keyword} body must be a multiline placeholder proof "
                f"(`by` followed by `sorry` or `sorry_using [...]`), "
                f"or a complete proof with no `sorry` token."
            )
        if n.keyword in DEFINITIONAL_KEYWORDS:
            if has_sorry_token(n.decl_signature_text + n.proof_body_text):
                failures.append(
                    f"{decl_loc}: definitional node '{n.label}' contains a `sorry` "
                    f"token; definitions are global context and must be complete."
                )
        if n.duplicate_fields:
            failures.append(
                f"{loc}: '{n.label}' has duplicate field(s) "
                f"{sorted(set(n.duplicate_fields))} in @[blueprint ...] — "
                f"each field may appear at most once"
            )
    return CheckResult("Check 2: Node Well-Formedness", not failures, failures)


def check_latex_env(nodes: list[Node]) -> CheckResult:
    failures: list[str] = []
    for n in nodes:
        loc = f"{n.file}:{n.line_attr}"
        if n.latex_env not in ALLOWED_LATEX_ENV:
            failures.append(
                f"{loc}: latexEnv '{n.latex_env}' not in {sorted(ALLOWED_LATEX_ENV)}"
            )
            continue
        if n.keyword and KEYWORD_TO_LATEX_ENV.get(n.keyword) != n.latex_env:
            failures.append(
                f"{loc}: keyword '{n.keyword}' does not match latexEnv '{n.latex_env}' "
                f"(expected '{KEYWORD_TO_LATEX_ENV.get(n.keyword)}')"
            )
    return CheckResult("Check 3: latexEnv Consistency", not failures, failures)


def check_label_name_normalization(nodes: list[Node]) -> CheckResult:
    failures: list[str] = []
    for n in nodes:
        loc = f"{n.file}:{n.line_attr}"
        if ":" not in n.label:
            failures.append(
                f"{loc}: label '{n.label}' has no environment prefix (expected def:/lem:/thm:)"
            )
            continue
        prefix, suffix = n.label.split(":", 1)
        if prefix not in PREFIX_TO_LATEX_ENV:
            failures.append(
                f"{loc}: label prefix '{prefix}:' is not one of def/lem/thm"
            )
            continue
        expected_env = PREFIX_TO_LATEX_ENV[prefix]
        actual_env = KEYWORD_TO_LATEX_ENV.get(n.keyword)
        if actual_env and expected_env != actual_env:
            failures.append(
                f"{loc}: label prefix '{prefix}:' expects a '{expected_env}' node, "
                f"but the declaration is a {n.keyword} (latexEnv '{actual_env}')"
            )
        expected = suffix.replace("-", "_")
        if n.lean_name and n.lean_name != expected:
            failures.append(
                f"{loc}: label '{n.label}' normalizes to '{expected}', "
                f"but Lean name is '{n.lean_name}'"
            )
    return CheckResult("Check 4: Label-Name Normalization", not failures, failures)


def check_unique_labels(nodes: list[Node]) -> CheckResult:
    seen: dict[str, int] = {}
    failures: list[str] = []
    for n in nodes:
        if n.label in seen:
            failures.append(
                f"{n.file}:{n.line_attr}: duplicate label '{n.label}' "
                f"(first seen at line {seen[n.label]})"
            )
        else:
            seen[n.label] = n.line_attr
    return CheckResult("Check 5: Unique Labels", not failures, failures)


_ELAB_DEPS_MARKER = "__VERIFY_BLUEPRINT_DEP__"
_ELAB_NODE_MARKER = "__VERIFY_BLUEPRINT_NODE__"


def _lean_string_literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _lean_array_literal(values: list[str]) -> str:
    return "#[" + ", ".join(_lean_string_literal(v) for v in values) + "]"


def _tail(text: str, max_lines: int = 80) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(["... (truncated)"] + lines[-max_lines:])


def _source_without_imports(source: str) -> tuple[list[str], str]:
    """Return top-level import lines and the source with import lines removed.

    The elaborator probe may concatenate several blueprint files. Lean requires
    all imports to appear before declarations, so imports from later files must
    be hoisted instead of left in the middle of the generated probe.
    """
    imports: list[str] = []
    body_lines: list[str] = []
    for line in source.splitlines(keepends=True):
        if re.match(r"^\s*import\s+", line):
            imports.append(line.rstrip("\n"))
        else:
            body_lines.append(line)
    return imports, "".join(body_lines)


def extract_elaborated_proof_deps(
    files: list[Path], nodes: list[Node]
) -> tuple[dict[str, set[str]], list[str]]:
    """Ask Lean for each proof node's elaborated blueprint proof dependencies.

    The temporary Lean file contains the target blueprint files with imports
    hoisted to the top, then calls `Architect.collectUsed` on each
    `lemma`/`theorem`. LeanArchitect
    stops dependency traversal when it reaches another blueprint node, so this
    returns the proof-level blueprint boundary deps rather than Mathlib internals.
    The Python side filters those deps to lemma/theorem nodes only; definitions
    are global context and are intentionally not graph vertices.
    """
    proof_nodes = [n for n in nodes if n.keyword in PROOF_KEYWORDS and n.lean_name]
    proof_name_set = {n.lean_name for n in proof_nodes}
    if not proof_nodes:
        return {}, []

    deps_by_name: dict[str, set[str]] = {n.lean_name: set() for n in proof_nodes}
    failures: list[str] = []
    proof_names_literal = _lean_array_literal(sorted(proof_name_set))

    decls_literal = _lean_array_literal([n.lean_name for n in proof_nodes])
    import_lines: list[str] = ["import Lean", "import Architect"]
    source_chunks: list[str] = []
    for path in files:
        imports, body = _source_without_imports(path.read_text())
        import_lines.extend(imports)
        source_chunks.append(f"\n/-! Source: {path} -/\n" + body)
    seen_imports: set[str] = set()
    unique_import_lines: list[str] = []
    for line in import_lines:
        if line not in seen_imports:
            unique_import_lines.append(line)
            seen_imports.add(line)

    probe = f"""

open Lean Architect

#eval show CoreM Unit from do
  let proofNames : Array String := {proof_names_literal}
  let decls : Array String := {decls_literal}
  let proofSet : NameSet := NameSet.ofArray (proofNames.map String.toName)
  for decl in decls do
    let name := decl.toName
    IO.println s!"{_ELAB_NODE_MARKER}\\t{{decl}}"
    let (_, valueUsed) ← Architect.collectUsed name
    for dep in valueUsed do
      if proofSet.contains dep then
        IO.println s!"{_ELAB_DEPS_MARKER}\\t{{decl}}\\t{{dep}}"
"""
    with tempfile.TemporaryDirectory(prefix="verify-blueprint-") as td:
        tmp_path = Path(td) / "Probe.lean"
        tmp_path.write_text(
            "\n".join(unique_import_lines) + "\n" + "\n".join(source_chunks) + probe
        )
        lean_cmd = ["lake", "env", "lean"]
        lean_threads = os.environ.get("VERIFY_BLUEPRINT_LEAN_THREADS")
        if lean_threads:
            lean_cmd.extend(["-j", lean_threads])
        lean_cmd.extend(["--", str(tmp_path)])
        proc = subprocess.run(
            lean_cmd,
            cwd=lean_project_cwd(),
            text=True,
            capture_output=True,
            timeout=3600,
        )
    if proc.returncode != 0:
        details = "\n".join(
            part
            for part in (
                _tail(proc.stdout).strip(),
                _tail(proc.stderr).strip(),
            )
            if part
        )
        failures.append(
            "Lean elaborator dependency extraction failed "
            f"(exit {proc.returncode})"
            + (f":\n{details}" if details else "")
        )
        return deps_by_name, failures
    seen_nodes: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] == _ELAB_NODE_MARKER:
            seen_nodes.add(parts[1])
        elif len(parts) >= 3 and parts[0] == _ELAB_DEPS_MARKER:
            decl, dep = parts[1], parts[2]
            if decl in deps_by_name and dep in proof_name_set and dep != decl:
                deps_by_name[decl].add(dep)
    missing = [n.lean_name for n in proof_nodes if n.lean_name not in seen_nodes]
    if missing:
        failures.append(
            "Lean elaborator dependency extraction produced no "
            f"result for {missing}"
        )

    return deps_by_name, failures


def _extract_with_cached_regex(
    body: str, dep_regex, self_name: str
) -> set[str]:
    """Run a pre-compiled dep regex against the cleaned body."""
    if not body or dep_regex is None:
        return set()
    cleaned = strip_lean_comments(body)
    found: set[str] = set()
    for m in dep_regex.finditer(cleaned):
        name = m.group("name")
        if name != self_name:
            found.add(name)
    return found


def check_sorry_using_consistency(
    nodes: list[Node], elaborated_deps: dict[str, set[str]]
) -> CheckResult:
    """Definitions are global context: proof deps and \\cref pairs are checked
    only against lemma/theorem nodes. \\cref{def:...} citations in proofs are
    accepted without requiring a proof dependency, but every \\cref{...} label
    must resolve to an existing blueprint node."""
    failures: list[str] = []
    by_lean_name = {n.lean_name: n for n in nodes if n.lean_name}
    by_label = {n.label: n for n in nodes}
    seen_so_far: set[str] = set()
    for n in nodes:
        loc = f"{n.file}:{n.line_decl or n.line_attr}"
        if n.sorry_using_raw_args is not None and sorry_using_args_have_comment(
            n.sorry_using_raw_args
        ):
            failures.append(
                f"{loc}: sorry_using list of '{n.label}' contains a comment "
                f"(`/-…-/` or `--…`); comments inside the list are forbidden"
            )
        for label in n.cref_labels:
            if label not in by_label:
                failures.append(
                    f"{loc}: \\cref{{{label}}} in proof of '{n.label}' points to "
                    f"no blueprint node in this file"
                )
        for label in n.statement_cref_labels:
            if label not in by_label:
                failures.append(
                    f"{loc}: \\cref{{{label}}} in statement of '{n.label}' points to "
                    f"no blueprint node in this file"
                )
        for dep in n.sorry_uses:
            target = by_lean_name.get(dep)
            if target is None:
                failures.append(
                    f"{loc}: sorry_using references '{dep}' which is not the Lean name of any blueprint node"
                )
                continue
            if target.keyword in DEFINITIONAL_KEYWORDS:
                failures.append(
                    f"{loc}: sorry_using references definitional node '{dep}' "
                    f"({target.keyword}); definitions are global context and must "
                    f"not appear in sorry_using"
                )
                continue
            if dep not in seen_so_far:
                failures.append(
                    f"{loc}: sorry_using references '{dep}' which appears later in the file"
                )
        # 6.4 — two-way `\cref` ↔ proof dependency parity. The dependency
        # source is Lean elaborator metadata (`Architect.collectUsed`) filtered
        # to in-blueprint lemma/theorem nodes. Invalid bodies are skipped
        # because Check 2 reports them first.
        if n.proof and n.keyword in PROOF_KEYWORDS and n.body_kind != "invalid":
            cref_lemma_thm: set[str] = set()
            for label in n.cref_labels:
                target = by_label.get(label)
                if target and target.keyword in PROOF_KEYWORDS and target.lean_name:
                    cref_lemma_thm.add(target.lean_name)
            deps_set = elaborated_deps.get(n.lean_name, set())
            for dep in sorted(deps_set):
                if dep not in seen_so_far:
                    failures.append(
                        f"{loc}: proof depends on '{dep}' which appears later in the file"
                    )
            for d in sorted(cref_lemma_thm - deps_set):
                failures.append(
                    f"{loc}: '{d}' is cited via \\cref in proof text of '{n.label}' "
                    f"but Lean elaborator metadata does not report it as a proof dependency"
                )
            for d in sorted(deps_set - cref_lemma_thm):
                failures.append(
                    f"{loc}: proof of '{n.label}' depends on '{d}' according to "
                    f"Lean elaborator metadata but the proof text does not cite it via \\cref"
                )
        if n.lean_name:
            seen_so_far.add(n.lean_name)
    return CheckResult("Check 6: Proof Dependency Consistency", not failures, failures)


def build_dep_regex(candidate_names: list[str]):
    """Build a single compiled alternation regex that matches any candidate
    identifier as a Lean-identifier-bounded token. Names are escaped and
    sorted longest-first so prefix names can't shadow longer ones (`a` won't
    match inside `abc` regardless of order, but with regex alternation we want
    the longer literal to be tried first to bind correctly).

    Boundary semantics (using Python re's Unicode-aware `\\w`):
    - **Lookbehind** `(?<![\\w'.])` — match must NOT be preceded by a Lean
      identifier character, by an apostrophe, or by `.`. The `.` exclusion
      prevents `bar` from matching inside `Foo.bar` (qualified-name use).
    - **Lookahead** `(?![\\w'])` — match must NOT be followed by an identifier
      character. `.` is *not* excluded so `bar.symm` correctly matches `bar`
      (the lemma is used with `.symm` accessor).
    """
    sorted_names = sorted({n for n in candidate_names if n}, key=lambda s: -len(s))
    if not sorted_names:
        return None
    alts = "|".join(re.escape(n) for n in sorted_names)
    return re.compile(rf"(?<![\w'.])(?P<name>{alts})(?![\w'])")


def extract_lean_name_deps(
    body: str, candidate_names: list[str], self_name: str
) -> set[str]:
    """Scan the cleaned Lean body for any candidate identifier (single
    pre-compiled alternation regex). Returns the set of matched names,
    excluding `self_name`."""
    if not body:
        return set()
    pattern = build_dep_regex(candidate_names)
    if pattern is None:
        return set()
    cleaned = strip_lean_comments(body)
    found: set[str] = set()
    for m in pattern.finditer(cleaned):
        name = m.group("name")
        if name != self_name:
            found.add(name)
    return found


def check_lemma_closeness(
    nodes: list[Node], elaborated_deps: dict[str, set[str]]
) -> CheckResult:
    """Every lemma node must be referenced as a downstream "use" by some later
    `lemma`/`theorem`. A node N "uses" a lemma X if:

    X appears in N's Lean-elaborated proof dependencies, filtered to in-file
    blueprint lemma/theorem names.

    Theorems are exempt from being a "redundant" target. Definitions are global
    context. Cycle detection and topological-file-order checks are subsumed by
    Check 6's earlier-existence rule."""
    failures: list[str] = []
    used_by_someone: set[str] = set()
    for n in nodes:
        if n.keyword not in PROOF_KEYWORDS or n.body_kind == "invalid":
            continue
        used_by_someone.update(elaborated_deps.get(n.lean_name, set()))
    for n in nodes:
        if n.keyword == "lemma" and n.lean_name not in used_by_someone:
            failures.append(
                f"{n.file}:{n.line_decl or n.line_attr}: lemma '{n.lean_name}' "
                f"is not referenced by any later `sorry_using` or by any "
                f"complete-proof body (redundant node or missing dependency)"
            )
    return CheckResult(
        "Check 7: Lemma Closeness",
        not failures,
        failures,
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_checks(files: list[Path], build_log: Optional[Path]) -> tuple[bool, list[CheckResult]]:
    nodes: list[Node] = []
    anomalies: list[str] = []
    for f in files:
        fnodes, fanoms = parse_file(f)
        nodes.extend(fnodes)
        anomalies.extend(fanoms)

    results: list[CheckResult] = []
    for runner in [
        lambda: check_compilation(build_log),
        lambda: check_node_well_formedness(nodes, anomalies),
        lambda: check_latex_env(nodes),
        lambda: check_label_name_normalization(nodes),
        lambda: check_unique_labels(nodes),
    ]:
        r = runner()
        results.append(r)
        if not r.passed:
            return False, results

    elaborated_deps, dep_failures = extract_elaborated_proof_deps(files, nodes)
    if dep_failures:
        results.append(
            CheckResult(
                "Check 6: Lean-Elaborated Proof Dependencies",
                False,
                dep_failures,
            )
        )
        return False, results

    for runner in [
        lambda: check_sorry_using_consistency(nodes, elaborated_deps),
        lambda: check_lemma_closeness(nodes, elaborated_deps),
    ]:
        r = runner()
        results.append(r)
        if not r.passed:
            return False, results
    return True, results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--build-log", type=Path, default=None)
    ap.add_argument("--report", type=Path, default=Path("verify-report.json"))
    args = ap.parse_args()

    for f in args.files:
        if not f.exists():
            print(f"ERROR: file does not exist: {f}", file=sys.stderr)
            return 2
        if f.is_dir():
            print(f"ERROR: path is a directory, not a file: {f}", file=sys.stderr)
            return 2
        try:
            f.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            print(f"ERROR: file is not valid UTF-8: {f} ({e})", file=sys.stderr)
            return 2

    overall_pass, results = run_checks(args.files, args.build_log)

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"{status}  {r.name}")
        for f in r.failures:
            for line in f.splitlines():
                print(f"      {line}")

    args.report.write_text(
        json.dumps(
            {
                "files": [str(f) for f in args.files],
                "overall_pass": overall_pass,
                "results": [
                    {"name": r.name, "passed": r.passed, "failures": r.failures}
                    for r in results
                ],
            },
            indent=2,
        )
    )
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
