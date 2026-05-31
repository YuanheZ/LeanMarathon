#!/usr/bin/env python3
"""
Stdio MCP server that exposes Codex-style apply_patch as a structured tool.

This is a small Python port of the OpenAI Codex Rust apply-patch crate
(`codex-rs/apply-patch`, rust-v0.124.0). It intentionally does not shell out
to bash, git apply, patch, Python subprocesses, or any other command.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import traceback
from typing import Any


BEGIN_PATCH_MARKER = "*** Begin Patch"
END_PATCH_MARKER = "*** End Patch"
EOF_MARKER = "*** End of File"
CHANGE_CONTEXT_MARKER = "@@ "
EMPTY_CHANGE_CONTEXT_MARKER = "@@"

SERVER_NAME = "codex-apply-patch-mcp"
SERVER_VERSION = "0.1.0"
_MISSING_ID = object()


class PatchError(Exception):
    pass


class ParseError(PatchError):
    pass


class ApplyError(PatchError):
    pass


@dataclass
class UpdateFileChunk:
    change_context: str | None
    old_lines: list[str]
    new_lines: list[str]
    is_end_of_file: bool


@dataclass
class ParsedPatch:
    patch: str
    chunks: list[UpdateFileChunk]


@dataclass(frozen=True)
class NodeEditAnchor:
    node_name: str
    helper_area_start: int
    prefix_hash: str
    frozen_hash: str


@dataclass(frozen=True)
class ServerConfig:
    workspace: Workspace
    configured_target_file: Path | None
    configured_target_label: str | None
    other_target_files: dict[str, Path]
    apply_patch_node: str | None
    node_edit_anchor: NodeEditAnchor | None


@dataclass
class ApplySummary:
    added: list[str]
    modified: list[str]
    deleted: list[str]
    dry_run: bool

    def text(self) -> str:
        prefix = "Dry run. Would update the following files:" if self.dry_run else "Success. Updated the following files:"
        lines = [prefix]
        lines.extend(f"A {path}" for path in self.added)
        lines.extend(f"M {path}" for path in self.modified)
        lines.extend(f"D {path}" for path in self.deleted)
        return "\n".join(lines) + "\n"

    def structured(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "added": self.added,
            "modified": self.modified,
            "deleted": self.deleted,
        }


@dataclass(frozen=True)
class TextRange:
    name: str
    start: int
    end: int
    allow_end_boundary_insert: bool = False


@dataclass(frozen=True)
class BlueprintNode:
    label: str
    keyword: str
    lean_name: str
    attr_start: int
    attr_end: int
    decl_start: int
    body_start: int
    body_end: int
    body_content_end: int
    field_ranges: dict[str, tuple[int, int]]


def parse_patch(patch: str) -> ParsedPatch:
    lines = patch.strip().splitlines()
    patch_lines, hunk_lines = _check_patch_boundaries_lenient(lines)
    chunks: list[UpdateFileChunk] = []
    index = 0
    line_number = 2
    while index < len(hunk_lines):
        if not hunk_lines[index].strip():
            index += 1
            line_number += 1
            continue
        if hunk_lines[index].startswith("*** "):
            raise ParseError(
                "file operation markers are not supported by this MCP server; "
                "pass the target file as the structured 'path' argument"
            )
        chunk, consumed = _parse_update_file_chunk(
            hunk_lines[index:],
            line_number,
            allow_missing_context=not chunks,
        )
        chunks.append(chunk)
        index += consumed
        line_number += consumed
    return ParsedPatch(patch="\n".join(patch_lines), chunks=chunks)


def _check_patch_boundaries_strict(lines: list[str]) -> tuple[list[str], list[str]]:
    first = lines[0].strip() if lines else None
    last = lines[-1].strip() if lines else None
    if first != BEGIN_PATCH_MARKER:
        raise ParseError("The first line of the patch must be '*** Begin Patch'")
    if last != END_PATCH_MARKER:
        raise ParseError("The last line of the patch must be '*** End Patch'")
    return lines, lines[1:-1]


def _check_patch_boundaries_lenient(lines: list[str]) -> tuple[list[str], list[str]]:
    try:
        return _check_patch_boundaries_strict(lines)
    except ParseError as original:
        if (
            len(lines) >= 4
            and lines[0] in {"<<EOF", "<<'EOF'", '<<"EOF"'}
            and lines[-1].endswith("EOF")
        ):
            return _check_patch_boundaries_strict(lines[1:-1])
        raise original


def _parse_update_file_chunk(
    lines: list[str],
    line_number: int,
    allow_missing_context: bool,
) -> tuple[UpdateFileChunk, int]:
    if not lines:
        raise ParseError(f"Update hunk at line {line_number} does not contain any lines")

    if lines[0] == EMPTY_CHANGE_CONTEXT_MARKER:
        change_context = None
        start_index = 1
    elif lines[0].startswith(CHANGE_CONTEXT_MARKER):
        change_context = lines[0][len(CHANGE_CONTEXT_MARKER) :]
        start_index = 1
    else:
        if not allow_missing_context:
            raise ParseError(f"Expected update hunk to start with a @@ context marker, got: '{lines[0]}'")
        change_context = None
        start_index = 0

    if start_index >= len(lines):
        raise ParseError(f"Update hunk at line {line_number + 1} does not contain any lines")

    chunk = UpdateFileChunk(
        change_context=change_context,
        old_lines=[],
        new_lines=[],
        is_end_of_file=False,
    )
    parsed_lines = 0
    for line in lines[start_index:]:
        if line == EOF_MARKER:
            if parsed_lines == 0:
                raise ParseError(f"Update hunk at line {line_number + 1} does not contain any lines")
            chunk.is_end_of_file = True
            parsed_lines += 1
            break

        marker = line[:1]
        if marker == "":
            chunk.old_lines.append("")
            chunk.new_lines.append("")
        elif marker == " ":
            chunk.old_lines.append(line[1:])
            chunk.new_lines.append(line[1:])
        elif marker == "+":
            chunk.new_lines.append(line[1:])
        elif marker == "-":
            chunk.old_lines.append(line[1:])
        else:
            if parsed_lines == 0:
                raise ParseError(
                    f"Unexpected line found in update hunk: '{line}'. Every line should start with "
                    "' ' (context line), '+' (added line), or '-' (removed line)"
                )
            break
        parsed_lines += 1

    return chunk, parsed_lines + start_index


def _normalise_for_match(value: str) -> str:
    translation = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u00a0": " ",
        "\u2002": " ",
        "\u2003": " ",
        "\u2004": " ",
        "\u2005": " ",
        "\u2006": " ",
        "\u2007": " ",
        "\u2008": " ",
        "\u2009": " ",
        "\u200a": " ",
        "\u202f": " ",
        "\u205f": " ",
        "\u3000": " ",
    }
    return "".join(translation.get(char, char) for char in value.strip())


def seek_sequence(lines: list[str], pattern: list[str], start: int, eof: bool) -> int | None:
    if not pattern:
        return start
    if len(pattern) > len(lines):
        return None

    search_start = len(lines) - len(pattern) if eof and len(lines) >= len(pattern) else start
    search_end = len(lines) - len(pattern)
    if search_start > search_end:
        return None

    for index in range(search_start, search_end + 1):
        if lines[index : index + len(pattern)] == pattern:
            return index

    for index in range(search_start, search_end + 1):
        if all(lines[index + offset].rstrip() == value.rstrip() for offset, value in enumerate(pattern)):
            return index

    for index in range(search_start, search_end + 1):
        if all(lines[index + offset].strip() == value.strip() for offset, value in enumerate(pattern)):
            return index

    for index in range(search_start, search_end + 1):
        if all(
            _normalise_for_match(lines[index + offset]) == _normalise_for_match(value)
            for offset, value in enumerate(pattern)
        ):
            return index

    return None


DECL_KEYWORDS: tuple[str, ...] = (
    "theorem", "lemma",
    "def", "abbrev", "structure", "inductive", "class", "instance",
)
MODIFIERS = (
    "noncomputable", "private", "protected",
    "unsafe", "partial", "nonrec", "scoped", "local",
)
TOP_LEVEL_BREAK_KEYWORDS = DECL_KEYWORDS + MODIFIERS + (
    "end", "namespace", "section", "import", "open", "set_option",
    "variable", "universe", "attribute",
)
ATTR_OPEN_RE = re.compile(r"@\[")
BLUEPRINT_TOKEN_RE = re.compile(r"\bblueprint\s+\"([^\"]+)\"")


def _skip_block_comment(text: str, start: int) -> int:
    depth = 1
    index = start + 2
    while index < len(text) and depth > 0:
        if text.startswith("/-", index):
            depth += 1
            index += 2
        elif text.startswith("-/", index):
            depth -= 1
            index += 2
        else:
            index += 1
    return index


def skip_comments_and_ws(text: str, index: int) -> int:
    while index < len(text):
        if text[index] in " \t\n\r":
            index += 1
            continue
        if text.startswith("--", index):
            newline = text.find("\n", index)
            index = newline + 1 if newline != -1 else len(text)
            continue
        if text.startswith("/-", index) and not text.startswith("/--", index):
            index = _skip_block_comment(text, index)
            continue
        break
    return index


def find_balanced(text: str, start: int, opener: str, closer: str) -> int:
    if start >= len(text) or text[start] != opener:
        raise ParseError(f"expected '{opener}' at offset {start}")
    depth = 1
    index = start + 1
    while index < len(text):
        ch = text[index]
        if text.startswith("/-", index):
            index = _skip_block_comment(text, index)
            continue
        if text.startswith("--", index):
            newline = text.find("\n", index)
            index = newline + 1 if newline != -1 else len(text)
            continue
        if ch == '"':
            end = index + 1
            while end < len(text) and text[end] != '"':
                if text[end] == "\\" and end + 1 < len(text):
                    end += 2
                else:
                    end += 1
            index = end + 1
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ParseError(f"unbalanced '{opener}' at offset {start}")


def mask_comments_only(text: str) -> str:
    out = list(text)
    index = 0
    while index < len(text):
        if text.startswith("/-", index):
            end = _skip_block_comment(text, index)
            for offset in range(index, end):
                if out[offset] != "\n":
                    out[offset] = " "
            index = end
            continue
        if text.startswith("--", index):
            newline = text.find("\n", index)
            end = newline if newline != -1 else len(text)
            for offset in range(index, end):
                out[offset] = " "
            index = end
            continue
        if text[index] == '"':
            end = index + 1
            while end < len(text) and text[end] != '"':
                if text[end] == "\\" and end + 1 < len(text):
                    end += 2
                else:
                    end += 1
            index = end + 1
            continue
        index += 1
    return "".join(out)


def parse_decl(text: str, start: int) -> tuple[str, str, int] | None:
    index = skip_comments_and_ws(text, start)
    while True:
        skipped = False
        for modifier in MODIFIERS:
            if text.startswith(modifier, index) and (
                index + len(modifier) >= len(text)
                or text[index + len(modifier)] in " \t\n\r"
            ):
                index += len(modifier)
                index = skip_comments_and_ws(text, index)
                skipped = True
                break
        if not skipped and text.startswith("@[", index):
            try:
                close = find_balanced(text, index + 1, "[", "]")
                index = skip_comments_and_ws(text, close + 1)
                skipped = True
            except ParseError:
                pass
        if not skipped:
            break

    for keyword in DECL_KEYWORDS:
        if text.startswith(keyword, index) and (
            index + len(keyword) >= len(text)
            or text[index + len(keyword)] in " \t\n\r"
        ):
            name_index = index + len(keyword)
            while name_index < len(text) and text[name_index] in " \t":
                name_index += 1
            name_start = name_index
            while name_index < len(text) and (text[name_index].isalnum() or text[name_index] in "_'"):
                name_index += 1
            while (
                name_index + 1 < len(text)
                and text[name_index] == "."
                and (text[name_index + 1].isalpha() or text[name_index + 1] == "_")
            ):
                name_index += 1
                while name_index < len(text) and (text[name_index].isalnum() or text[name_index] in "_'"):
                    name_index += 1
            return keyword, text[name_start:name_index], index
    return None


def _find_top_level_break(text: str, start: int) -> int:
    index = start
    while index < len(text):
        if text[index] == "\n":
            line_start = index + 1
            if line_start >= len(text):
                return line_start
            if text[line_start] in (" ", "\t"):
                index += 1
                continue
            if text.startswith("@[", line_start):
                return line_start
            for keyword in TOP_LEVEL_BREAK_KEYWORDS:
                if text.startswith(keyword, line_start) and (
                    line_start + len(keyword) >= len(text)
                    or text[line_start + len(keyword)] in " \t\n\r"
                ):
                    return line_start
        index += 1
    return len(text)


def find_decl_body_range(text: str, decl_offset: int) -> tuple[int, int]:
    decl_end = _find_top_level_break(text, decl_offset + 1)
    index = decl_offset
    nesting = 0
    while index < decl_end:
        if text.startswith("/-", index):
            index = _skip_block_comment(text, index)
            continue
        if text.startswith("--", index):
            newline = text.find("\n", index)
            index = newline + 1 if newline != -1 else len(text)
            continue
        ch = text[index]
        if ch == '"':
            end = index + 1
            while end < len(text) and text[end] != '"':
                if text[end] == "\\" and end + 1 < len(text):
                    end += 2
                else:
                    end += 1
            index = end + 1
            continue
        if ch in "({[":
            nesting += 1
        elif ch in ")}]":
            nesting = max(0, nesting - 1)
        elif nesting == 0 and text.startswith(":=", index):
            body_start = index + 2
            return body_start, _find_top_level_break(text, body_start)
        index += 1
    return decl_offset, decl_offset


def _trim_outer_ws(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in " \t\n\r":
        start += 1
    while end > start and text[end - 1] in " \t\n\r":
        end -= 1
    return start, end


def parse_attr_field_ranges(text: str, body_start: int, body_end: int) -> dict[str, tuple[int, int]]:
    ranges: dict[str, tuple[int, int]] = {}
    index = body_start
    while index < body_end:
        if text[index] != "(":
            index += 1
            continue
        try:
            field_end = find_balanced(text, index, "(", ")")
        except ParseError:
            break
        inner_start = index + 1
        inner_end = field_end
        inner = text[inner_start:inner_end]
        match = re.match(r"(\w+)\s*:=\s*", inner, re.DOTALL)
        if match:
            name = match.group(1)
            value_start = inner_start + match.end()
            value_end = inner_end
            value_start, value_end = _trim_outer_ws(text, value_start, value_end)
            if text.startswith("/--", value_start) and text[value_end - 2:value_end] == "-/":
                ranges[name] = (value_start + 3, value_end - 2)
            elif value_end > value_start + 1 and text[value_start] == '"' and text[value_end - 1] == '"':
                ranges[name] = (value_start + 1, value_end - 1)
        index = field_end + 1
    return ranges


def parse_blueprint_nodes(text: str) -> list[BlueprintNode]:
    masked = mask_comments_only(text)
    nodes: list[BlueprintNode] = []
    for match in ATTR_OPEN_RE.finditer(masked):
        attr_start = match.start()
        bracket_open = attr_start + 1
        try:
            bracket_close = find_balanced(text, bracket_open, "[", "]")
        except ParseError:
            continue
        attr_body_start = bracket_open + 1
        attr_body_end = bracket_close
        body = text[attr_body_start:attr_body_end]
        blueprint = BLUEPRINT_TOKEN_RE.search(body)
        if blueprint is None:
            continue
        decl = parse_decl(text, bracket_close + 1)
        if decl is None:
            continue
        keyword, lean_name, decl_start = decl
        body_start, body_end = find_decl_body_range(text, decl_start)
        body_content_end = body_end
        while body_content_end > body_start and text[body_content_end - 1] in " \t\n\r":
            body_content_end -= 1
        nodes.append(
            BlueprintNode(
                label=blueprint.group(1),
                keyword=keyword,
                lean_name=lean_name,
                attr_start=attr_start,
                attr_end=bracket_close + 1,
                decl_start=decl_start,
                body_start=body_start,
                body_end=body_end,
                body_content_end=body_content_end,
                field_ranges=parse_attr_field_ranges(text, attr_body_start, attr_body_end),
            )
        )
    return nodes


def preceding_blank_line_range(text: str, attr_start: int) -> tuple[int, int] | None:
    attr_line_start = text.rfind("\n", 0, attr_start) + 1
    if attr_line_start == 0:
        return None
    previous_line_end = attr_line_start - 1
    previous_line_start = text.rfind("\n", 0, previous_line_end) + 1
    if text[previous_line_start:previous_line_end].strip():
        return None
    return previous_line_start, attr_line_start


def line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset) + 1
    return line, offset - line_start + 1


def line_start_offsets(text: str) -> list[int]:
    offsets = [0]
    index = 0
    while True:
        newline = text.find("\n", index)
        if newline == -1:
            return offsets
        offsets.append(newline + 1)
        index = newline + 1


def offset_for_line_start(offsets: list[int], text_length: int, line_index: int) -> int:
    if line_index < len(offsets):
        return offsets[line_index]
    return text_length


def text_for_replacement_lines(lines: list[str], include_trailing_newline: bool) -> str:
    if not lines:
        return ""
    text = "\n".join(lines)
    if include_trailing_newline:
        text += "\n"
    return text


def _lines_are_subsequence(needle: list[str], haystack: list[str]) -> bool:
    index = 0
    for line in haystack:
        if index < len(needle) and needle[index] == line:
            index += 1
    return index == len(needle)


def changed_spans_from_replacements(
    original_contents: str,
    original_lines: list[str],
    replacements: list[tuple[int, int, list[str]]],
) -> list[tuple[int, bool, str, int, int, str]]:
    offsets = line_start_offsets(original_contents)
    spans: list[tuple[int, bool, str, int, int, str]] = []
    for replacement_index, (start_line, old_len, new_segment) in enumerate(replacements):
        old_segment = original_lines[start_line : start_line + old_len]
        replacement_rewrites_old_lines = bool(old_segment) and not _lines_are_subsequence(
            old_segment,
            new_segment,
        )
        prefix_len = 0
        while (
            prefix_len < len(old_segment)
            and prefix_len < len(new_segment)
            and old_segment[prefix_len] == new_segment[prefix_len]
        ):
            prefix_len += 1

        suffix_len = 0
        while (
            suffix_len < len(old_segment) - prefix_len
            and suffix_len < len(new_segment) - prefix_len
            and old_segment[len(old_segment) - 1 - suffix_len]
            == new_segment[len(new_segment) - 1 - suffix_len]
        ):
            suffix_len += 1

        old_start = prefix_len
        old_end = len(old_segment) - suffix_len
        new_start = prefix_len
        new_end = len(new_segment) - suffix_len
        if old_start == old_end and new_start == new_end:
            continue

        absolute_line_start = start_line + old_start
        absolute_line_end = start_line + old_end
        old_char_start = offset_for_line_start(offsets, len(original_contents), absolute_line_start)
        old_char_end = offset_for_line_start(offsets, len(original_contents), absolute_line_end)
        if old_start == old_end:
            inserted_text = text_for_replacement_lines(
                new_segment[new_start:new_end],
                include_trailing_newline=True,
            )
            spans.append(
                (
                    replacement_index,
                    replacement_rewrites_old_lines,
                    "insert",
                    old_char_start,
                    old_char_start,
                    inserted_text,
                )
            )
            continue
        if new_start == new_end:
            spans.append(
                (
                    replacement_index,
                    replacement_rewrites_old_lines,
                    "delete",
                    old_char_start,
                    old_char_end,
                    "",
                )
            )
            continue

        old_text = original_contents[old_char_start:old_char_end]
        include_trailing_newline = old_text.endswith("\n")
        new_text = text_for_replacement_lines(
            new_segment[new_start:new_end],
            include_trailing_newline,
        )
        char_matcher = difflib.SequenceMatcher(None, old_text, new_text, autojunk=False)
        for char_tag, char_old_start, char_old_end, char_new_start, char_new_end in char_matcher.get_opcodes():
            if char_tag == "equal":
                continue
            spans.append(
                (
                    replacement_index,
                    replacement_rewrites_old_lines,
                    char_tag,
                    old_char_start + char_old_start,
                    old_char_start + char_old_end,
                    new_text[char_new_start:char_new_end],
                )
            )
    return spans


def find_target_node(nodes: list[BlueprintNode], node_name: str, path_label: str) -> BlueprintNode:
    matches = [node for node in nodes if node.lean_name == node_name]
    if not matches:
        raise ApplyError(f"APPLY_PATCH_NODE '{node_name}' was not found in {path_label}")
    if len(matches) > 1:
        raise ApplyError(f"APPLY_PATCH_NODE '{node_name}' is ambiguous in {path_label}")
    return matches[0]


def anchor_prefix_hash(text: str, helper_area_start: int) -> str:
    return hashlib.sha256(text[:helper_area_start].encode("utf-8")).hexdigest()


def _normalise_ranges(text_length: int, ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    normalised: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        start = max(0, min(start, text_length))
        end = max(0, min(end, text_length))
        if start >= end:
            continue
        if normalised and start <= normalised[-1][1]:
            previous_start, previous_end = normalised[-1]
            normalised[-1] = (previous_start, max(previous_end, end))
        else:
            normalised.append((start, end))
    return normalised


def frozen_projection_hash(
    text: str,
    target: BlueprintNode,
    helper_area_start: int,
) -> str:
    ignored_ranges: list[tuple[int, int]] = []
    if helper_area_start <= target.attr_start:
        ignored_ranges.append((helper_area_start, target.attr_start))
    ignored_ranges.extend(
        target.field_ranges[field_name]
        for field_name in ("statement", "proof", "title")
        if field_name in target.field_ranges
    )
    proof_edit_end = _proof_body_edit_end(text, target)
    if target.body_start < proof_edit_end:
        ignored_ranges.append((target.body_start, proof_edit_end))

    digest = hashlib.sha256()
    cursor = 0
    for start, end in _normalise_ranges(len(text), ignored_ranges):
        digest.update(text[cursor:start].encode("utf-8"))
        digest.update(b"\0<editable-range>\0")
        cursor = end
    digest.update(text[cursor:].encode("utf-8"))
    return digest.hexdigest()


def compute_node_edit_anchor(text: str, node_name: str, path_label: str) -> NodeEditAnchor:
    nodes = parse_blueprint_nodes(text)
    target = find_target_node(nodes, node_name, path_label)
    gap = preceding_blank_line_range(text, target.attr_start)
    helper_area_start = gap[0] if gap is not None else target.attr_start
    return NodeEditAnchor(
        node_name=node_name,
        helper_area_start=helper_area_start,
        prefix_hash=anchor_prefix_hash(text, helper_area_start),
        frozen_hash=frozen_projection_hash(text, target, helper_area_start),
    )


_SORRY_LIKE_RE = re.compile(r"(?<![A-Za-z0-9_'])sorry(?:_using)?(?![A-Za-z0-9_'])")
_PLACEHOLDER_PROOF_RE = re.compile(r"\Aby\s+(?:sorry|sorry_using\s*\[[^\]]*\])\Z", re.DOTALL)
_PLACEHOLDER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_'])(?:sorry_using\s*\[[^\]]*\]|sorry)(?![A-Za-z0-9_'])", re.DOTALL)


def _proof_body_edit_end(text: str, target: BlueprintNode) -> int:
    body_edit_end = target.body_content_end
    if body_edit_end < target.body_end:
        newline = text.find("\n", body_edit_end, target.body_end)
        if newline != -1:
            body_edit_end = newline + 1
    return body_edit_end


def _line_slices(text: str, start: int, end: int) -> list[tuple[int, int, str]]:
    slices: list[tuple[int, int, str]] = []
    index = start
    while index < end:
        newline = text.find("\n", index, end)
        line_end = end if newline == -1 else newline + 1
        slices.append((index, line_end, text[index:line_end]))
        index = line_end
    return slices


def mask_comments_and_strings(text: str) -> str:
    out = list(text)
    index = 0
    while index < len(text):
        if text.startswith("/-", index):
            end = _skip_block_comment(text, index)
            for offset in range(index, end):
                if out[offset] != "\n":
                    out[offset] = " "
            index = end
            continue
        if text.startswith("--", index):
            newline = text.find("\n", index)
            end = newline if newline != -1 else len(text)
            for offset in range(index, end):
                out[offset] = " "
            index = end
            continue
        if text[index] == '"':
            end = index + 1
            while end < len(text) and text[end] != '"':
                if text[end] == "\\" and end + 1 < len(text):
                    end += 2
                else:
                    end += 1
            end = min(end + 1, len(text))
            for offset in range(index, end):
                if out[offset] != "\n":
                    out[offset] = " "
            index = end
            continue
        index += 1
    return "".join(out)


def _first_code_line_is_standalone_by(masked_body: str) -> bool:
    for _line_start, _line_end, line in _line_slices(masked_body, 0, len(masked_body)):
        stripped = line.strip()
        if stripped:
            return stripped == "by"
    return False


def _placeholder_token_edit_start(text: str, body_start: int, masked_body: str) -> int:
    match = _PLACEHOLDER_TOKEN_RE.search(masked_body)
    if match is None:
        return body_start
    token_start = body_start + match.start()
    token_line_start = text.rfind("\n", 0, token_start) + 1
    if token_line_start < body_start:
        return token_start
    return token_line_start


def proof_body_edit_range(text: str, target: BlueprintNode) -> tuple[int, int, bool] | None:
    body_edit_end = _proof_body_edit_end(text, target)
    if target.body_start >= body_edit_end:
        return None

    body_text = text[target.body_start:body_edit_end]
    masked_body = mask_comments_and_strings(body_text)
    if _PLACEHOLDER_PROOF_RE.match(masked_body.strip()):
        return _placeholder_token_edit_start(
            text,
            target.body_start,
            masked_body,
        ), body_edit_end, False

    allow_end_boundary_insert = (
        not _SORRY_LIKE_RE.search(masked_body)
        and _first_code_line_is_standalone_by(masked_body)
    )
    return target.body_start, body_edit_end, allow_end_boundary_insert


def editable_ranges_for_target(
    text: str,
    nodes: list[BlueprintNode],
    target_index: int,
    helper_area_start: int,
) -> list[TextRange]:
    target = nodes[target_index]
    ranges: list[TextRange] = []
    if helper_area_start <= target.attr_start:
        ranges.append(
            TextRange(
                "helper insertion/refinement area before target attribute",
                helper_area_start,
                target.attr_start,
            )
        )
    for field_name in ("statement", "proof", "title"):
        if field_name in target.field_ranges:
            start, end = target.field_ranges[field_name]
            ranges.append(TextRange(f"{field_name} text", start, end))
    proof_range = proof_body_edit_range(text, target)
    if proof_range is not None:
        ranges.append(
            TextRange(
                "proof body",
                proof_range[0],
                proof_range[1],
                proof_range[2],
            )
        )
    return ranges


def _proof_body_inserted_text_allowed(text: str, start: int, inserted_text: str) -> bool:
    if not inserted_text:
        return True
    _line, col = line_col(text, start)
    for index, line in enumerate(inserted_text.splitlines()):
        if not line.strip():
            continue
        if index == 0 and col > 1:
            continue
        if line[0] not in (" ", "\t"):
            return False
    return True


def _span_allowed(
    original_contents: str,
    start: int,
    end: int,
    inserted_text: str,
    ranges: list[TextRange],
) -> bool:
    if start == end:
        for editable in ranges:
            if not (editable.start <= start <= editable.end):
                continue
            if editable.name == "proof body" and start == editable.end:
                if editable.allow_end_boundary_insert and _proof_body_boundary_insert_allowed(inserted_text):
                    return True
                continue
            if editable.name == "proof body" and not _proof_body_inserted_text_allowed(
                original_contents,
                start,
                inserted_text,
            ):
                continue
            return True
        return False
    return any(
        editable.start <= start
        and end <= editable.end
        and (
            editable.name != "proof body"
            or _proof_body_inserted_text_allowed(
                original_contents,
                start,
                inserted_text,
            )
        )
        for editable in ranges
    )


def _proof_body_boundary_insert_allowed(inserted_text: str) -> bool:
    has_content = False
    for line in inserted_text.splitlines():
        if not line.strip():
            continue
        has_content = True
        if line[0] not in (" ", "\t"):
            return False
    return has_content


def _paired_proof_body_end_insert_allowed(
    replacement_rewrites_old_lines: bool,
    start: int,
    inserted_text: str,
    ranges: list[TextRange],
) -> bool:
    if not replacement_rewrites_old_lines:
        return False
    if not _proof_body_boundary_insert_allowed(inserted_text):
        return False
    for editable in ranges:
        if editable.name != "proof body" or start != editable.end:
            continue
        return True
    return False


def _format_ranges(text: str, ranges: list[TextRange]) -> str:
    parts: list[str] = []
    for editable in ranges:
        start_line, start_col = line_col(text, editable.start)
        end_line, end_col = line_col(text, editable.end)
        parts.append(f"{editable.name} [{start_line}:{start_col}-{end_line}:{end_col}]")
    return "; ".join(parts)


def enforce_node_edit_restrictions(
    original_contents: str,
    new_contents: str,
    original_lines: list[str],
    replacements: list[tuple[int, int, list[str]]],
    anchor: NodeEditAnchor,
    path_label: str,
) -> None:
    node_name = anchor.node_name
    if (
        anchor.helper_area_start > len(original_contents)
        or anchor_prefix_hash(original_contents, anchor.helper_area_start) != anchor.prefix_hash
    ):
        raise ApplyError(
            "content before the APPLY_PATCH_NODE helper anchor changed since server startup "
            f"for '{node_name}' in {path_label}; restart the apply-patch MCP server"
        )
    original_nodes = parse_blueprint_nodes(original_contents)
    target = find_target_node(original_nodes, node_name, path_label)
    if frozen_projection_hash(original_contents, target, anchor.helper_area_start) != anchor.frozen_hash:
        raise ApplyError(
            "frozen content outside the APPLY_PATCH_NODE editable areas changed since server startup "
            f"for '{node_name}' in {path_label}; restart the apply-patch MCP server"
        )
    target_index = next(
        index for index, node in enumerate(original_nodes) if node.lean_name == node_name
    )
    ranges = editable_ranges_for_target(
        original_contents,
        original_nodes,
        target_index,
        anchor.helper_area_start,
    )
    if not ranges:
        raise ApplyError(f"APPLY_PATCH_NODE '{node_name}' has no editable ranges in {path_label}")

    violations: list[str] = []
    spans = changed_spans_from_replacements(
        original_contents,
        original_lines,
        replacements,
    )
    for (
        replacement_index,
        replacement_rewrites_old_lines,
        tag,
        old_start,
        old_end,
        inserted_text,
    ) in spans:
        if not _span_allowed(original_contents, old_start, old_end, inserted_text, ranges):
            if tag == "insert" and _paired_proof_body_end_insert_allowed(
                replacement_rewrites_old_lines,
                old_start,
                inserted_text,
                ranges,
            ):
                continue
            start_line, start_col = line_col(original_contents, old_start)
            end_line, end_col = line_col(original_contents, old_end)
            violations.append(f"{tag} at original {start_line}:{start_col}-{end_line}:{end_col}")

    if violations:
        raise ApplyError(
            "patch edits outside the APPLY_PATCH_NODE editable areas for "
            f"'{node_name}' in {path_label}: "
            + "; ".join(violations)
            + ". Allowed areas: "
            + _format_ranges(original_contents, ranges)
        )


class Workspace:
    def __init__(self, root: Path):
        try:
            resolved = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ApplyError(f"workspace root does not exist or is inaccessible: {root}") from exc
        if not resolved.is_dir():
            raise ApplyError(f"workspace root is not a directory: {root}")
        self.root = resolved

    def resolve_path(self, raw_path: str, allow_missing: bool) -> Path:
        if raw_path == "":
            raise ApplyError("empty paths are not allowed")
        if "\x00" in raw_path:
            raise ApplyError("paths must not contain NUL bytes")
        requested = Path(raw_path)
        candidate = requested if requested.is_absolute() else self.root / requested
        if not allow_missing:
            try:
                unresolved_info = candidate.lstat()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise ApplyError(f"failed to inspect path {raw_path}: {exc}") from exc
            else:
                if stat.S_ISLNK(unresolved_info.st_mode):
                    raise ApplyError(f"refusing to follow symlink: {candidate}")
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ApplyError(f"failed to resolve path {raw_path}: {exc}") from exc
        if not _is_relative_to(resolved, self.root):
            raise ApplyError(f"path escapes workspace root: {raw_path}")
        if allow_missing:
            try:
                parent = resolved.parent.resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                raise ApplyError(f"failed to resolve path parent {raw_path}: {exc}") from exc
            if not _is_relative_to(parent, self.root):
                raise ApplyError(f"path parent escapes workspace root: {raw_path}")
        return resolved

    def read_text(self, path: Path) -> str:
        self._check_existing_regular_file(path)
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ApplyError(f"file is not valid UTF-8: {path}") from exc
        except OSError as exc:
            raise ApplyError(f"failed to read file {path}: {exc}") from exc

    def write_text_atomic(self, path: Path, content: str) -> None:
        self._check_existing_regular_file(path)
        mode = stat.S_IMODE(path.stat().st_mode)

        parent_stat = path.parent.stat()
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ApplyError(f"parent path is not a directory: {path.parent}")

        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                delete=False,
                prefix=f".{path.name}.",
                suffix=".tmp",
            ) as temp_file:
                temp_name = temp_file.name
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.chmod(temp_name, mode)
            self._check_existing_regular_file(path)
            os.replace(temp_name, path)
            temp_name = None
            self._fsync_directory(path.parent)
        except OSError as exc:
            raise ApplyError(f"failed to write file {path}: {exc}") from exc
        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass

    def _check_existing_regular_file(self, path: Path) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise ApplyError(f"file does not exist: {path}") from exc
        except OSError as exc:
            raise ApplyError(f"failed to inspect file {path}: {exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ApplyError(f"refusing to follow symlink: {path}")
        if not stat.S_ISREG(info.st_mode):
            raise ApplyError(f"path is not a regular file: {path}")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if not hasattr(os, "O_DIRECTORY"):
            return
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_lean_path(path: Path) -> bool:
    return path.suffix.lower() == ".lean"


def _parse_configured_file_list(raw_value: str | None, env_name: str) -> list[str]:
    if raw_value is None or not raw_value.strip():
        return []
    value = raw_value.strip()
    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ApplyError(f"{env_name} must be a JSON string array or a comma/newline-separated list") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ApplyError(f"{env_name} must be a JSON string array")
        result = [item.strip() for item in parsed]
    else:
        result = [item.strip() for item in re.split(r"[,\n]", value)]
    if any(not item for item in result):
        raise ApplyError(f"{env_name} must not contain empty file entries")
    return result


def _resolve_other_target_files(workspace: Workspace, raw_value: str | None) -> dict[str, Path]:
    labels = _parse_configured_file_list(raw_value, "APPLY_PATCH_OTHER_FILES")
    result: dict[str, Path] = {}
    seen_paths: dict[Path, str] = {}
    for label in labels:
        if label in result:
            raise ApplyError(f"duplicate APPLY_PATCH_OTHER_FILES entry: {label}")
        path = workspace.resolve_path(label, allow_missing=False)
        workspace._check_existing_regular_file(path)
        if _is_lean_path(path):
            raise ApplyError(
                "APPLY_PATCH_OTHER_FILES must not contain Lean files; "
                "configure the single Lean file with APPLY_PATCH_TARGET_FILE"
            )
        if path in seen_paths:
            raise ApplyError(
                "duplicate APPLY_PATCH_OTHER_FILES path: "
                f"{label} resolves to the same file as {seen_paths[path]}"
            )
        result[label] = path
        seen_paths[path] = label
    return result


def _configured_file_entries(config: ServerConfig) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    if config.configured_target_file is not None:
        assert config.configured_target_label is not None
        entries.append((config.configured_target_label, config.configured_target_file))
    entries.extend(config.other_target_files.items())
    return entries


def derive_new_contents(original_contents: str, path_label: str, chunks: list[UpdateFileChunk]) -> str:
    original_lines = original_contents.split("\n")
    if original_lines and original_lines[-1] == "":
        original_lines.pop()
    replacements = compute_replacements(original_lines, path_label, chunks)
    new_lines = apply_replacements(original_lines, replacements)
    if not new_lines or new_lines[-1] != "":
        new_lines.append("")
    return "\n".join(new_lines)


def derive_new_contents_and_replacements(
    original_contents: str,
    path_label: str,
    chunks: list[UpdateFileChunk],
) -> tuple[str, list[str], list[tuple[int, int, list[str]]]]:
    original_lines = original_contents.split("\n")
    if original_lines and original_lines[-1] == "":
        original_lines.pop()
    replacements = compute_replacements(original_lines, path_label, chunks)
    new_lines = apply_replacements(original_lines, replacements)
    if not new_lines or new_lines[-1] != "":
        new_lines.append("")
    return "\n".join(new_lines), original_lines, replacements


def compute_replacements(
    original_lines: list[str],
    path_label: str,
    chunks: list[UpdateFileChunk],
) -> list[tuple[int, int, list[str]]]:
    replacements: list[tuple[int, int, list[str]]] = []
    line_index = 0

    for chunk in chunks:
        if chunk.change_context is not None:
            context_index = seek_sequence(original_lines, [chunk.change_context], line_index, eof=False)
            if context_index is None:
                raise ApplyError(f"Failed to find context '{chunk.change_context}' in {path_label}")
            line_index = context_index + 1

        if not chunk.old_lines:
            insertion_index = len(original_lines) - 1 if original_lines and original_lines[-1] == "" else len(original_lines)
            replacements.append((insertion_index, 0, list(chunk.new_lines)))
            continue

        pattern = list(chunk.old_lines)
        new_slice = list(chunk.new_lines)
        found = seek_sequence(original_lines, pattern, line_index, eof=chunk.is_end_of_file)

        if found is None and pattern and pattern[-1] == "":
            pattern = pattern[:-1]
            if new_slice and new_slice[-1] == "":
                new_slice = new_slice[:-1]
            found = seek_sequence(original_lines, pattern, line_index, eof=chunk.is_end_of_file)

        if found is None:
            raise ApplyError(f"Failed to find expected lines in {path_label}:\n" + "\n".join(chunk.old_lines))

        replacements.append((found, len(pattern), new_slice))
        line_index = found + len(pattern)

    replacements.sort(key=lambda item: item[0])
    return replacements


def apply_replacements(
    lines: list[str],
    replacements: list[tuple[int, int, list[str]]],
) -> list[str]:
    result = list(lines)
    for start_index, old_len, new_segment in reversed(replacements):
        del result[start_index : start_index + old_len]
        for offset, new_line in enumerate(new_segment):
            result.insert(start_index + offset, new_line)
    return result


def apply_patch_to_workspace(
    patch: str,
    target_path: Path,
    target_label: str,
    workspace: Workspace,
    dry_run: bool,
    node_edit_anchor: NodeEditAnchor | None = None,
) -> ApplySummary:
    parsed = parse_patch(patch)
    if not parsed.chunks:
        raise ApplyError("No files were modified.")

    original_contents = workspace.read_text(target_path)
    new_contents, original_lines, replacements = derive_new_contents_and_replacements(
        original_contents,
        str(target_path),
        parsed.chunks,
    )
    if node_edit_anchor:
        enforce_node_edit_restrictions(
            original_contents,
            new_contents,
            original_lines,
            replacements,
            node_edit_anchor,
            target_label,
        )
    if not dry_run:
        workspace.write_text_atomic(target_path, new_contents)

    return ApplySummary(added=[], modified=[target_label], deleted=[], dry_run=dry_run)


def diff_preview(patch: str, target_path: Path, target_label: str, workspace: Workspace) -> str:
    parsed = parse_patch(patch)
    old_content = workspace.read_text(target_path)
    new_content = derive_new_contents(old_content, str(target_path), parsed.chunks)
    lines = difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=target_label,
        tofile=target_label,
        n=1,
    )
    return "".join(lines)


def tool_schemas(config: ServerConfig) -> list[dict[str, Any]]:
    common_properties: dict[str, Any] = {
        "patch": {
            "type": "string",
            "description": "Patch text containing only update chunks between *** Begin Patch and *** End Patch.",
        },
    }
    required = ["patch"]
    configured_entries = _configured_file_entries(config)
    path_required = config.configured_target_file is None or bool(config.other_target_files)
    if path_required:
        if configured_entries:
            allowed = ", ".join(label for label, _path in configured_entries)
            path_description = (
                "Configured file to edit. The path must resolve to one of: "
                f"{allowed}."
            )
        else:
            path_description = "Existing file to edit. Relative paths are resolved against the configured workspace root."
        common_properties["path"] = {
            "type": "string",
            "description": path_description,
        }
        required.insert(0, "path")
    target_scope = "configured " if configured_entries else ""

    return [
        {
            "name": "apply_patch",
            "description": f"Apply update chunks to one existing {target_scope}file without invoking a shell.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": common_properties,
                "required": required,
            },
        },
        {
            "name": "apply_patch_dry_run",
            "description": f"Validate update chunks for one existing {target_scope}file and return a unified diff preview, without writing files.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": common_properties,
                "required": required,
            },
        },
    ]


def make_config() -> ServerConfig:
    root = os.environ.get("APPLY_PATCH_WORKSPACE") or os.getcwd()
    workspace = Workspace(Path(root))
    configured_target_label = os.environ.get("APPLY_PATCH_TARGET_FILE")
    configured_target_file = None
    if configured_target_label:
        configured_target_file = workspace.resolve_path(configured_target_label, allow_missing=False)
        workspace._check_existing_regular_file(configured_target_file)
    other_target_files = _resolve_other_target_files(
        workspace,
        os.environ.get("APPLY_PATCH_OTHER_FILES"),
    )
    if configured_target_file is not None:
        for other_label, other_path in other_target_files.items():
            if other_path == configured_target_file:
                raise ApplyError(
                    f"APPLY_PATCH_OTHER_FILES entry {other_label} duplicates APPLY_PATCH_TARGET_FILE"
                )
    apply_patch_node = (os.environ.get("APPLY_PATCH_NODE") or "").strip() or None
    if apply_patch_node and configured_target_file is None:
        raise ApplyError("APPLY_PATCH_NODE requires APPLY_PATCH_TARGET_FILE")
    if apply_patch_node and configured_target_file is not None and not _is_lean_path(configured_target_file):
        raise ApplyError("APPLY_PATCH_NODE requires APPLY_PATCH_TARGET_FILE to be a .lean file")
    node_edit_anchor = None
    if apply_patch_node and configured_target_file is not None and configured_target_label is not None:
        node_edit_anchor = compute_node_edit_anchor(
            workspace.read_text(configured_target_file),
            apply_patch_node,
            configured_target_label,
        )
    return ServerConfig(
        workspace=workspace,
        configured_target_file=configured_target_file,
        configured_target_label=configured_target_label,
        other_target_files=other_target_files,
        apply_patch_node=apply_patch_node,
        node_edit_anchor=node_edit_anchor,
    )


def resolve_target_file(arguments: dict[str, Any], config: ServerConfig) -> tuple[Path, str]:
    raw_path = arguments.get("path")
    configured_entries = _configured_file_entries(config)
    if configured_entries and (config.configured_target_file is None or config.other_target_files):
        if not isinstance(raw_path, str):
            raise ApplyError("tool argument 'path' must be a string")
        requested = config.workspace.resolve_path(raw_path, allow_missing=False)
        for label, path in configured_entries:
            if requested == path:
                return path, label
        allowed = ", ".join(label for label, _path in configured_entries)
        raise ApplyError(f"requested path is not one of the configured files: {allowed}")

    if config.configured_target_file is not None:
        assert config.configured_target_label is not None
        if raw_path is not None:
            if not isinstance(raw_path, str):
                raise ApplyError("tool argument 'path' must be a string when provided")
            requested = config.workspace.resolve_path(raw_path, allow_missing=False)
            if requested != config.configured_target_file:
                raise ApplyError("this server is configured for a single target file; requested path is not allowed")
        return config.configured_target_file, config.configured_target_label

    if not isinstance(raw_path, str):
        raise ApplyError("tool argument 'path' must be a string")
    return config.workspace.resolve_path(raw_path, allow_missing=False), raw_path


def validate_tool_arguments(arguments: dict[str, Any]) -> None:
    allowed = {"path", "patch"}
    unexpected = sorted(set(arguments) - allowed)
    if unexpected:
        quoted = ", ".join(f"'{name}'" for name in unexpected)
        raise ApplyError(f"unexpected tool argument(s): {quoted}")


def handle_tool_call(
    name: str,
    arguments: dict[str, Any],
    config: ServerConfig,
) -> dict[str, Any]:
    if name not in {"apply_patch", "apply_patch_dry_run"}:
        raise ApplyError(f"unknown tool: {name}")
    validate_tool_arguments(arguments)
    patch = arguments.get("patch")
    if not isinstance(patch, str):
        raise ApplyError("tool argument 'patch' must be a string")
    target_path, target_label = resolve_target_file(arguments, config)
    node_edit_anchor = None
    if (
        config.apply_patch_node is not None
        and config.configured_target_file is not None
        and target_path == config.configured_target_file
    ):
        node_edit_anchor = config.node_edit_anchor
        if node_edit_anchor is None:
            node_edit_anchor = compute_node_edit_anchor(
                config.workspace.read_text(target_path),
                config.apply_patch_node,
                target_label,
            )

    if name == "apply_patch":
        summary = apply_patch_to_workspace(
            patch,
            target_path,
            target_label,
            config.workspace,
            dry_run=False,
            node_edit_anchor=node_edit_anchor,
        )
        return {
            "content": [{"type": "text", "text": summary.text()}],
            "structuredContent": summary.structured(),
        }
    if name == "apply_patch_dry_run":
        summary = apply_patch_to_workspace(
            patch,
            target_path,
            target_label,
            config.workspace,
            dry_run=True,
            node_edit_anchor=node_edit_anchor,
        )
        preview = diff_preview(patch, target_path, target_label, config.workspace)
        text = summary.text()
        if preview:
            text += "\n" + preview
        structured = summary.structured()
        structured["diff"] = preview
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": structured,
        }

    raise ApplyError(f"unknown tool: {name}")


def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def result_response(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def error_response(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def maybe_emit_result(message_id: Any, result: dict[str, Any]) -> None:
    if message_id is not _MISSING_ID:
        emit(result_response(message_id, result))


def maybe_emit_error(message_id: Any, code: int, message: str) -> None:
    if message_id is not _MISSING_ID:
        emit(error_response(message_id, code, message))


def valid_message_id(message_id: Any) -> bool:
    return (
        message_id is _MISSING_ID
        or message_id is None
        or isinstance(message_id, str)
        or (isinstance(message_id, int) and not isinstance(message_id, bool))
    )


def emit_invalid_request_for_message_id(message_id: Any, message: str) -> None:
    if message_id is _MISSING_ID:
        emit(error_response(None, -32600, message))
    else:
        emit(error_response(message_id, -32600, message))


def serve() -> int:
    config = make_config()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            emit(error_response(None, -32700, f"invalid JSON: {exc}"))
            continue
        if not isinstance(message, dict):
            emit(error_response(None, -32600, "invalid request: JSON-RPC message must be an object"))
            continue

        message_id = message.get("id", _MISSING_ID)
        if not valid_message_id(message_id):
            emit(error_response(None, -32600, "invalid request: id must be a string, integer, null, or omitted"))
            continue
        if message.get("jsonrpc") != "2.0":
            emit_invalid_request_for_message_id(message_id, "invalid request: jsonrpc must be '2.0'")
            continue
        method = message.get("method")
        try:
            if method is not None and not isinstance(method, str):
                emit_invalid_request_for_message_id(message_id, "invalid request: method must be a string")
            elif method == "initialize":
                params = message.get("params")
                if params is None:
                    params = {}
                if not isinstance(params, dict):
                    raise ApplyError("initialize param 'params' must be an object")
                protocol_version = params.get("protocolVersion") or "2024-11-05"
                maybe_emit_result(
                    message_id,
                    {
                        "protocolVersion": protocol_version,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    },
                )
            elif method == "notifications/initialized":
                continue
            elif method == "ping":
                maybe_emit_result(message_id, {})
            elif method == "tools/list":
                maybe_emit_result(message_id, {"tools": tool_schemas(config)})
            elif method == "tools/call":
                params = message.get("params")
                if params is None:
                    params = {}
                if not isinstance(params, dict):
                    raise ApplyError("tools/call param 'params' must be an object")
                name = params.get("name")
                arguments = params.get("arguments")
                if arguments is None:
                    arguments = {}
                if not isinstance(name, str):
                    raise ApplyError("tools/call param 'name' must be a string")
                if not isinstance(arguments, dict):
                    raise ApplyError("tools/call param 'arguments' must be an object")
                try:
                    maybe_emit_result(message_id, handle_tool_call(name, arguments, config))
                except PatchError as exc:
                    maybe_emit_result(
                        message_id,
                        {
                            "content": [{"type": "text", "text": f"Error: {exc}"}],
                            "isError": True,
                        },
                    )
            elif method == "resources/list":
                maybe_emit_result(message_id, {"resources": []})
            elif method == "prompts/list":
                maybe_emit_result(message_id, {"prompts": []})
            elif method is None:
                maybe_emit_error(message_id, -32600, "missing method")
            elif message_id is _MISSING_ID:
                continue
            else:
                maybe_emit_error(message_id, -32601, f"method not found: {method}")
        except PatchError as exc:
            maybe_emit_error(message_id, -32602, str(exc))
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            maybe_emit_error(message_id, -32603, str(exc))
    return 0


def _run_self_test() -> int:
    import subprocess as _subprocess
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(Path(tmp))
        Path(tmp, "hello.txt").write_text("hello\n", encoding="utf-8")

        summary = apply_patch_to_workspace(
            "*** Begin Patch\n@@\n-hello\n+goodbye\n*** End Patch",
            ws.resolve_path("hello.txt", allow_missing=False),
            "hello.txt",
            ws,
            dry_run=False,
        )
        assert summary.modified == ["hello.txt"]
        assert Path(tmp, "hello.txt").read_text(encoding="utf-8") == "goodbye\n"

        for patch in [
            "*** Begin Patch\n*** Add File: added.txt\n+hello\n*** End Patch",
            "*** Begin Patch\n*** Delete File: hello.txt\n*** End Patch",
            "*** Begin Patch\n*** Update File: hello.txt\n@@\n-goodbye\n+renamed\n*** End Patch",
        ]:
            try:
                apply_patch_to_workspace(
                    patch,
                    ws.resolve_path("hello.txt", allow_missing=False),
                    "hello.txt",
                    ws,
                    dry_run=False,
                )
            except PatchError as exc:
                assert "file operation markers are not supported" in str(exc)
            else:
                raise AssertionError("file operation marker was not rejected")

        summary = apply_patch_to_workspace(
            "*** Begin Patch\n@@\n-goodbye\n+renamed\n*** End Patch",
            ws.resolve_path("hello.txt", allow_missing=False),
            "hello.txt",
            ws,
            dry_run=False,
        )
        assert summary.modified == ["hello.txt"]
        assert Path(tmp, "hello.txt").read_text(encoding="utf-8") == "renamed\n"

        try:
            apply_patch_to_workspace(
                "*** Begin Patch\n@@\n-no\n+yes\n*** End Patch",
                ws.resolve_path("../escape.txt", allow_missing=False),
                "../escape.txt",
                ws,
                dry_run=False,
            )
        except ApplyError:
            pass
        else:
            raise AssertionError("path traversal was not rejected")

        Path(tmp, "hello-link.txt").symlink_to(Path(tmp, "hello.txt"))
        try:
            ws.resolve_path("hello-link.txt", allow_missing=False)
        except ApplyError as exc:
            assert "refusing to follow symlink" in str(exc)
        else:
            raise AssertionError("symlink target was not rejected")
        try:
            ws.resolve_path("hello.txt\x00suffix", allow_missing=False)
        except ApplyError as exc:
            assert "NUL bytes" in str(exc)
        else:
            raise AssertionError("NUL byte path was not rejected")
        Path(tmp, "loop").symlink_to(Path(tmp, "loop"))
        try:
            ws.resolve_path("loop/file.txt", allow_missing=False)
        except ApplyError as exc:
            assert "failed to inspect path" in str(exc) or "failed to resolve path" in str(exc)
        else:
            raise AssertionError("symlink loop path was not rejected")

        protocol_env = os.environ.copy()
        protocol_env.update(
            {
                "APPLY_PATCH_WORKSPACE": tmp,
                "APPLY_PATCH_TARGET_FILE": "hello.txt",
                "APPLY_PATCH_NODE": "",
                "APPLY_PATCH_OTHER_FILES": "",
            }
        )
        protocol_messages = [
            "[]",
            json.dumps({"jsonrpc": "2.0", "id": {"bad": "id"}, "method": "ping"}),
            json.dumps({"jsonrpc": "2.0", "id": True, "method": "ping"}),
            json.dumps({"jsonrpc": "2.0", "id": 1.5, "method": "ping"}),
            json.dumps({"id": 2, "method": "ping"}),
            json.dumps({"jsonrpc": "1.0", "id": 3, "method": "ping"}),
            json.dumps({"jsonrpc": 2.0, "id": 4, "method": "ping"}),
            json.dumps({"jsonrpc": "2.0", "id": 5, "method": 42}),
            json.dumps({"jsonrpc": "2.0", "id": None, "method": "ping"}),
            json.dumps({"jsonrpc": "2.0", "method": "ping"}),
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []}),
        ]
        protocol_proc = _subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input="\n".join(protocol_messages) + "\n",
            text=True,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            env=protocol_env,
            timeout=5,
        )
        assert protocol_proc.returncode == 0
        assert protocol_proc.stderr == ""
        protocol_responses = [json.loads(line) for line in protocol_proc.stdout.splitlines()]
        assert len(protocol_responses) == 10
        assert protocol_responses[0]["id"] is None
        assert protocol_responses[0]["error"]["code"] == -32600
        for response in protocol_responses[1:4]:
            assert response["id"] is None
            assert response["error"]["code"] == -32600
            assert "id must be" in response["error"]["message"]
        for response in protocol_responses[4:7]:
            assert response["error"]["code"] == -32600
            assert "jsonrpc must be" in response["error"]["message"]
        assert [response["id"] for response in protocol_responses[4:7]] == [2, 3, 4]
        assert protocol_responses[7]["id"] == 5
        assert protocol_responses[7]["error"]["code"] == -32600
        assert "method must be" in protocol_responses[7]["error"]["message"]
        assert protocol_responses[8]["id"] is None
        assert protocol_responses[8]["result"] == {}
        assert protocol_responses[9]["id"] == 1
        assert protocol_responses[9]["error"]["code"] == -32602

        startup_env = os.environ.copy()
        startup_env.update(
            {
                "APPLY_PATCH_WORKSPACE": tmp,
                "APPLY_PATCH_NODE": "target_without_configured_file",
            }
        )
        startup_proc = _subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input="",
            text=True,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            env=startup_env,
            timeout=5,
        )
        assert startup_proc.returncode == 1
        assert startup_proc.stdout == ""
        assert startup_proc.stderr == "Error: APPLY_PATCH_NODE requires APPLY_PATCH_TARGET_FILE\n"
        missing_workspace_env = os.environ.copy()
        missing_workspace_env["APPLY_PATCH_WORKSPACE"] = str(Path(tmp, "missing-workspace"))
        missing_workspace_proc = _subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input="",
            text=True,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            env=missing_workspace_env,
            timeout=5,
        )
        assert missing_workspace_proc.returncode == 1
        assert missing_workspace_proc.stdout == ""
        assert "workspace root does not exist or is inaccessible" in missing_workspace_proc.stderr
        workspace_file = Path(tmp, "workspace-file")
        workspace_file.write_text("not a directory\n", encoding="utf-8")
        workspace_file_env = os.environ.copy()
        workspace_file_env["APPLY_PATCH_WORKSPACE"] = str(workspace_file)
        workspace_file_proc = _subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input="",
            text=True,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            env=workspace_file_env,
            timeout=5,
        )
        assert workspace_file_proc.returncode == 1
        assert workspace_file_proc.stdout == ""
        assert workspace_file_proc.stderr == f"Error: workspace root is not a directory: {workspace_file}\n"
        loop_workspace = Path(tmp, "workspace-loop")
        loop_workspace.symlink_to(loop_workspace)
        loop_workspace_env = os.environ.copy()
        loop_workspace_env["APPLY_PATCH_WORKSPACE"] = str(loop_workspace)
        loop_workspace_proc = _subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input="",
            text=True,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            env=loop_workspace_env,
            timeout=5,
        )
        assert loop_workspace_proc.returncode == 1
        assert loop_workspace_proc.stdout == ""
        assert "workspace root does not exist or is inaccessible" in loop_workspace_proc.stderr
        assert "Traceback" not in loop_workspace_proc.stderr

        config = ServerConfig(
            workspace=ws,
            configured_target_file=ws.resolve_path("hello.txt", allow_missing=False),
            configured_target_label="hello.txt",
            other_target_files={},
            apply_patch_node=None,
            node_edit_anchor=None,
        )
        assert tool_schemas(config)[0]["inputSchema"]["required"] == ["patch"]
        assert resolve_target_file({"patch": "ignored"}, config)[1] == "hello.txt"
        try:
            resolve_target_file({"path": "other.txt"}, config)
        except ApplyError as exc:
            assert "single target file" in str(exc)
        else:
            raise AssertionError("configured target did not reject a different requested path")
        try:
            validate_tool_arguments({"path": "hello.txt", "patch": "ignored", "cwd": "/tmp"})
        except ApplyError as exc:
            assert "unexpected tool argument" in str(exc)
        else:
            raise AssertionError("unexpected tool argument was not rejected")
        try:
            handle_tool_call("not_a_tool", {"patch": "ignored"}, config)
        except ApplyError as exc:
            assert "unknown tool" in str(exc)
        else:
            raise AssertionError("unknown tool was not rejected")

        Path(tmp, "state.md").write_text("state: none\n", encoding="utf-8")
        Path(tmp, "delivery.yml").write_text("kind: none\n", encoding="utf-8")
        multi_config = ServerConfig(
            workspace=ws,
            configured_target_file=ws.resolve_path("hello.txt", allow_missing=False),
            configured_target_label="hello.txt",
            other_target_files={
                "state.md": ws.resolve_path("state.md", allow_missing=False),
                "delivery.yml": ws.resolve_path("delivery.yml", allow_missing=False),
            },
            apply_patch_node=None,
            node_edit_anchor=None,
        )
        multi_schema = tool_schemas(multi_config)[0]["inputSchema"]
        assert multi_schema["required"] == ["path", "patch"]
        summary = apply_patch_to_workspace(
            "*** Begin Patch\n@@\n-state: none\n+state: in-progress\n*** End Patch",
            resolve_target_file({"path": "state.md"}, multi_config)[0],
            resolve_target_file({"path": "state.md"}, multi_config)[1],
            ws,
            dry_run=False,
        )
        assert summary.modified == ["state.md"]
        assert Path(tmp, "state.md").read_text(encoding="utf-8") == "state: in-progress\n"
        try:
            resolve_target_file({"path": "not-configured.md"}, multi_config)
        except ApplyError as exc:
            assert "configured files" in str(exc)
        else:
            raise AssertionError("multi-file configuration did not reject an unconfigured path")
        Path(tmp, "Other.lean").write_text("theorem other : True := by\n  trivial\n", encoding="utf-8")
        Path(tmp, "Upper.Lean").write_text("theorem upper : True := by\n  trivial\n", encoding="utf-8")
        try:
            _resolve_other_target_files(ws, '["Other.lean"]')
        except ApplyError as exc:
            assert "must not contain Lean files" in str(exc)
        else:
            raise AssertionError("APPLY_PATCH_OTHER_FILES accepted a Lean file")
        try:
            _resolve_other_target_files(ws, '["Upper.Lean"]')
        except ApplyError as exc:
            assert "must not contain Lean files" in str(exc)
        else:
            raise AssertionError("APPLY_PATCH_OTHER_FILES accepted an uppercase Lean file suffix")
        for raw_list in ('[""]', '["state.md", ""]', "state.md,,delivery.yml"):
            try:
                _resolve_other_target_files(ws, raw_list)
            except ApplyError as exc:
                assert "empty file entries" in str(exc)
            else:
                raise AssertionError("APPLY_PATCH_OTHER_FILES accepted an empty file entry")

        lean_path = Path(tmp, "Main.lean")
        lean_path.write_text(
            """@[blueprint "lem:prev"
  (statement := /-- Previous node. -/)
  (proof := /-- Previous proof. -/)
  (title := /-- Previous title -/)
  (latexEnv := "lemma")]
lemma prev : True := by
  trivial

@[blueprint "thm:target"
  (statement := /-- Target node. -/)
  (proof := /-- Target proof. -/)
  (title := /-- Target title -/)
  (latexEnv := "theorem")]
theorem target : True := by
  sorry

@[blueprint "lem:next"
  (statement := /-- Next node. -/)
  (proof := /-- Next proof. -/)
  (title := /-- Next title -/)
  (latexEnv := "lemma")]
lemma next : True := by
  trivial
""",
            encoding="utf-8",
        )
        lean_target = ws.resolve_path("Main.lean", allow_missing=False)
        target_anchor = compute_node_edit_anchor(
            ws.read_text(lean_target),
            "target",
            "Main.lean",
        )
        original_lean_text = lean_path.read_text(encoding="utf-8")
        lean_path.write_text(
            "-- external edit before target shifts stale anchor\n" + original_lean_text,
            encoding="utf-8",
        )
        try:
            apply_patch_to_workspace(
                """*** Begin Patch
@@
-lemma prev : True := by
+lemma prev : False := by
*** End Patch""",
                lean_target,
                "Main.lean",
                ws,
                dry_run=False,
                node_edit_anchor=target_anchor,
            )
        except ApplyError as exc:
            assert "helper anchor changed" in str(exc)
        else:
            raise AssertionError("stale node anchor allowed an edit before the target")
        lean_path.write_text(original_lean_text, encoding="utf-8")
        target_anchor = compute_node_edit_anchor(
            ws.read_text(lean_target),
            "target",
            "Main.lean",
        )
        lean_path.write_text(
            original_lean_text.replace(
                "theorem target : True := by",
                "theorem target : False := by",
            ),
            encoding="utf-8",
        )
        try:
            apply_patch_to_workspace(
                """*** Begin Patch
@@
 theorem target : False := by
-  sorry
+  trivial
*** End Patch""",
                lean_target,
                "Main.lean",
                ws,
                dry_run=False,
                node_edit_anchor=target_anchor,
            )
        except ApplyError as exc:
            assert "frozen content" in str(exc)
        else:
            raise AssertionError("frozen target statement drift was not rejected")
        lean_path.write_text(original_lean_text, encoding="utf-8")
        target_anchor = compute_node_edit_anchor(
            ws.read_text(lean_target),
            "target",
            "Main.lean",
        )
        lean_path.write_text(
            original_lean_text.replace(
                "  sorry\n\n@[blueprint \"lem:next\"",
                "  sorry\n@[blueprint \"lem:next\"",
            ),
            encoding="utf-8",
        )
        try:
            apply_patch_to_workspace(
                """*** Begin Patch
@@
 theorem target : True := by
-  sorry
+  trivial
*** End Patch""",
                lean_target,
                "Main.lean",
                ws,
                dry_run=False,
                node_edit_anchor=target_anchor,
            )
        except ApplyError as exc:
            assert "frozen content" in str(exc)
        else:
            raise AssertionError("separator drift before the next node was not rejected")
        lean_path.write_text(original_lean_text, encoding="utf-8")
        target_anchor = compute_node_edit_anchor(
            ws.read_text(lean_target),
            "target",
            "Main.lean",
        )

        def apply_node_patch(patch: str) -> None:
            apply_patch_to_workspace(
                patch,
                lean_target,
                "Main.lean",
                ws,
                dry_run=False,
                node_edit_anchor=target_anchor,
            )

        def assert_node_rejected(patch: str) -> None:
            try:
                apply_patch_to_workspace(
                    patch,
                    lean_target,
                    "Main.lean",
                    ws,
                    dry_run=False,
                    node_edit_anchor=target_anchor,
                )
            except ApplyError:
                return
            raise AssertionError("node edit restriction failed to reject an invalid patch")

        apply_node_patch(
            """*** Begin Patch
@@
 lemma prev : True := by
   trivial
-
+@[blueprint "lem:target-helper"
+  (statement := /-- Target helper. -/)
+  (proof := /-- Target helper proof. -/)
+  (title := /-- Target helper -/)
+  (latexEnv := "lemma")]
+lemma target_helper : True := by
+  trivial
+
 @[blueprint "thm:target"
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
-  (title := /-- Target helper -/)
+  (title := /-- Target helper, revised -/)
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
-@[blueprint "lem:target-helper"
-  (statement := /-- Target helper. -/)
-  (proof := /-- Target helper proof. -/)
-  (title := /-- Target helper, revised -/)
-  (latexEnv := "lemma")]
-lemma target_helper : True := by
-  trivial
-
+
 @[blueprint "thm:target"
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
 lemma prev : True := by
   trivial
-
+@[blueprint "def:local-helper-object"
+  (statement := /-- Local helper object. -/)
+  (title := /-- Local helper object -/)
+  (latexEnv := "definition")]
+def local_helper_object : True := True
+
 @[blueprint "thm:target"
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
-@[blueprint "def:local-helper-object"
-  (statement := /-- Local helper object. -/)
-  (title := /-- Local helper object -/)
-  (latexEnv := "definition")]
-def local_helper_object : True := True
-
+
 @[blueprint "thm:target"
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
-  (statement := /-- Target node. -/)
+  (statement := /-- Target node, revised. -/)
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
-  (proof := /-- Target proof. -/)
+  (proof := /-- Target proof, revised. -/)
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
-  (title := /-- Target title -/)
+  (title := /-- Target title, revised -/)
*** End Patch"""
        )
        assert_node_rejected(
            """*** Begin Patch
@@
 theorem target : True := by
+lemma not_owned_before_placeholder : True := by
+  trivial
   sorry
*** End Patch"""
        )
        assert_node_rejected(
            """*** Begin Patch
@@
 theorem target : True := by
-  sorry
+lemma not_owned_replacement : True := by
+  trivial
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
 theorem target : True := by
-  sorry
+  trivial
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
 theorem target : True := by
-  trivial
+  sorry
*** End Patch"""
        )
        assert_node_rejected(
            """*** Begin Patch
@@
 theorem target : True := by
   sorry
+  -- inserted after placeholder line
 
 @[blueprint "lem:next"
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
 theorem target : True := by
-  sorry
+  have target_placeholder_rewrite_smoke : True := by
+    trivial
+  exact target_placeholder_rewrite_smoke
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
 theorem target : True := by
-  have target_placeholder_rewrite_smoke : True := by
-    trivial
-  exact target_placeholder_rewrite_smoke
+  sorry
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
-  sorry
+  trivial
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
 theorem target : True := by
-  trivial
+  have target_body_rewrite_smoke : True := by
+    trivial
+  exact target_body_rewrite_smoke
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
 theorem target : True := by
-  have target_body_rewrite_smoke : True := by
-    trivial
-  exact target_body_rewrite_smoke
+  trivial
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
 theorem target : True := by
   trivial
+  exact True.intro
 
 @[blueprint "lem:next"
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
 theorem target : True := by
   trivial
-  exact True.intro
 
 @[blueprint "lem:next"
*** End Patch"""
        )

        for rejected_patch in [
            """*** Begin Patch
@@
-theorem target : True := by
+theorem target : False := by
*** End Patch""",
            """*** Begin Patch
@@
 theorem target : True := by
   trivial
   
 @[blueprint "lem:next"
*** End Patch""",
            """*** Begin Patch
@@
 theorem target : True := by
   trivial
+@[blueprint "lem:not-owned-after-target"
+  (statement := /-- Not owned. -/)
+  (proof := /-- Not owned proof. -/)
+  (title := /-- Not owned -/)
+  (latexEnv := "lemma")]
+lemma not_owned_after_target : True := by
+  trivial
 
 @[blueprint "lem:next"
*** End Patch""",
            """*** Begin Patch
@@
-  trivial
-
+  trivial
+-- separator blank line is not target-owned
 @[blueprint "lem:next"
*** End Patch""",
            """*** Begin Patch
@@
-lemma next : True := by
+lemma next : False := by
*** End Patch""",
        ]:
            assert_node_rejected(rejected_patch)

        lean_path.write_text(
            lean_path.read_text(encoding="utf-8").replace(
                "theorem target : True := by\n  trivial",
                "theorem target : True := by\n  -- placeholder comment\n  sorry",
            ),
            encoding="utf-8",
        )
        target_anchor = compute_node_edit_anchor(
            ws.read_text(lean_target),
            "target",
            "Main.lean",
        )
        assert_node_rejected(
            """*** Begin Patch
@@
-theorem target : True := by
+theorem target : True := by exact True.intro
*** End Patch"""
        )
        apply_node_patch(
            """*** Begin Patch
@@
-  sorry
+  trivial
*** End Patch"""
        )

    print("self-test passed", file=sys.stderr)
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        return _run_self_test()
    try:
        return serve()
    except PatchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
