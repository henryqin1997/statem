"""A tiny YAML subset parser used when PyYAML is not available.

This parser intentionally supports only the boring YAML that agents should emit
for statem specs: nested mappings, lists, scalar values, and block strings.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from typing import Any


class MiniYamlError(ValueError):
    pass


@dataclass(frozen=True)
class Line:
    number: int
    indent: int
    text: str


def loads(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)

    parser = _Parser(_logical_lines(text))
    value = parser.parse_block(0)
    parser.expect_done()
    return value


def _logical_lines(text: str) -> list[Line]:
    lines: list[Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise MiniYamlError(f"Line {number}: tabs are not supported for indentation")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append(Line(number=number, indent=indent, text=raw[indent:].rstrip()))
    return lines


class _Parser:
    def __init__(self, lines: list[Line]) -> None:
        self.lines = lines
        self.index = 0

    def expect_done(self) -> None:
        if self.index < len(self.lines):
            line = self.lines[self.index]
            raise MiniYamlError(f"Line {line.number}: unexpected content")

    def parse_block(self, indent: int) -> Any:
        if self.index >= len(self.lines):
            return {}
        line = self.lines[self.index]
        if line.indent < indent:
            return {}
        if line.indent > indent:
            raise MiniYamlError(f"Line {line.number}: unexpected indentation")
        if line.text.startswith("- "):
            return self.parse_list(indent)
        return self.parse_mapping(indent)

    def parse_mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise MiniYamlError(f"Line {line.number}: unexpected indentation")
            if line.text.startswith("- "):
                break

            key, value_text = _split_key_value(line)
            self.index += 1
            if value_text in {"|", ">"}:
                result[key] = self.collect_block_scalar(line.indent, folded=value_text == ">")
            elif value_text == "":
                result[key] = self.parse_child_or_empty(line.indent)
            else:
                result[key] = _parse_scalar(value_text)
        return result

    def parse_list(self, indent: int) -> list[Any]:
        result: list[Any] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise MiniYamlError(f"Line {line.number}: unexpected indentation")
            if not line.text.startswith("- "):
                break

            item_text = line.text[2:].strip()
            self.index += 1
            if item_text == "":
                result.append(self.parse_child_or_empty(line.indent))
                continue

            if _looks_like_key_value(item_text):
                key, value_text = _split_inline_key_value(item_text, line.number)
                item: dict[str, Any] = {}
                if value_text in {"|", ">"}:
                    item[key] = self.collect_block_scalar(line.indent, folded=value_text == ">")
                elif value_text == "":
                    item[key] = self.parse_child_or_empty(line.indent)
                else:
                    item[key] = _parse_scalar(value_text)

                if self.index < len(self.lines) and self.lines[self.index].indent > indent:
                    child = self.parse_block(self.lines[self.index].indent)
                    if not isinstance(child, dict):
                        raise MiniYamlError(
                            f"Line {self.lines[self.index - 1].number}: list item continuation must be a mapping"
                        )
                    item.update(child)
                result.append(item)
            else:
                result.append(_parse_scalar(item_text))
        return result

    def parse_child_or_empty(self, parent_indent: int) -> Any:
        if self.index >= len(self.lines) or self.lines[self.index].indent <= parent_indent:
            return {}
        return self.parse_block(self.lines[self.index].indent)

    def collect_block_scalar(self, parent_indent: int, *, folded: bool) -> str:
        block_lines: list[Line] = []
        while self.index < len(self.lines) and self.lines[self.index].indent > parent_indent:
            block_lines.append(self.lines[self.index])
            self.index += 1
        if not block_lines:
            return ""

        min_indent = min((line.indent for line in block_lines if line.text), default=parent_indent + 2)
        values = [line.text if line.indent < min_indent else " " * (line.indent - min_indent) + line.text for line in block_lines]
        if folded:
            return " ".join(value.strip() for value in values).strip()
        return "\n".join(values).rstrip("\n")


def _split_key_value(line: Line) -> tuple[str, str]:
    if ":" not in line.text:
        raise MiniYamlError(f"Line {line.number}: expected 'key: value'")
    key, value = line.text.split(":", 1)
    key = key.strip()
    if not key:
        raise MiniYamlError(f"Line {line.number}: empty mapping key")
    return key, value.strip()


def _split_inline_key_value(text: str, number: int) -> tuple[str, str]:
    if ":" not in text:
        raise MiniYamlError(f"Line {number}: expected 'key: value'")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise MiniYamlError(f"Line {number}: empty mapping key")
    return key, value.strip()


def _looks_like_key_value(text: str) -> bool:
    if ":" not in text:
        return False
    first = text[: text.index(":")]
    return bool(first.strip()) and not first.startswith(("'", '"'))


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    lowered = value.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(value)
            except (SyntaxError, ValueError):
                return value
    if value.startswith(("'", '"')):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value.strip("'\"")
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value

