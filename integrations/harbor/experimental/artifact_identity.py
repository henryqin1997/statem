from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


DEFAULT_EXCLUDED_PARTS = {
    ".git",
    ".statem",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}
DEFAULT_EXCLUDED_NAMES = {"progress.md"}


def stable_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_identity(
    root: Path,
    *,
    excluded_parts: Iterable[str] = DEFAULT_EXCLUDED_PARTS,
) -> str:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"artifact root is not a directory: {root}")
    excluded = set(excluded_parts)
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in excluded for part in relative.parts):
            continue
        if relative.name in DEFAULT_EXCLUDED_NAMES:
            continue
        if path.is_symlink():
            entries.append(
                {
                    "path": relative.as_posix(),
                    "type": "symlink",
                    "target": os.readlink(path),
                }
            )
        elif path.is_file():
            entries.append(
                {
                    "path": relative.as_posix(),
                    "type": "file",
                    "executable": bool(path.stat().st_mode & 0o111),
                    "sha256": file_sha256(path),
                }
            )
    return "tree-sha256:" + stable_sha256(entries)


def artifact_progress_identity(
    root: Path,
    *,
    excluded_parts: Iterable[str] = DEFAULT_EXCLUDED_PARTS,
) -> str:
    """Return a content-free metadata witness for same-session progress."""

    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"artifact root is not a directory: {root}")
    excluded = set(excluded_parts)
    entries: list[dict[str, Any]] = []
    for current_root, directory_names, file_names in os.walk(root, topdown=True):
        current = Path(current_root)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            path = current / name
            relative = path.relative_to(root)
            if name in excluded:
                continue
            if path.is_symlink():
                entries.append(
                    {
                        "path": relative.as_posix(),
                        "type": "symlink",
                        "target": os.readlink(path),
                    }
                )
            else:
                kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in sorted(file_names):
            if name in DEFAULT_EXCLUDED_NAMES:
                continue
            path = current / name
            relative = path.relative_to(root)
            if path.is_symlink():
                entries.append(
                    {
                        "path": relative.as_posix(),
                        "type": "symlink",
                        "target": os.readlink(path),
                    }
                )
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if not path.is_file():
                continue
            entries.append(
                {
                    "path": relative.as_posix(),
                    "type": "file",
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "executable": bool(stat.st_mode & 0o111),
                }
            )
    return "progress-sha256:" + stable_sha256(entries)


def public_contract_snapshot(root: Path) -> dict[str, dict[str, str]]:
    root = root.expanduser().resolve()
    snapshot: dict[str, dict[str, str]] = {}
    if not root.is_dir():
        return snapshot
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(
            part.startswith(".") or part in DEFAULT_EXCLUDED_PARTS
            for part in relative.parts
        ):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        prefix = relative.as_posix()
        module_doc = ast.get_docstring(tree, clean=False)
        if module_doc:
            snapshot[f"{prefix}::module"] = {
                "signature": "module",
                "docstring": module_doc,
            }
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    snapshot[f"{prefix}::{node.name}"] = _callable_contract(node)
            elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                bases = ", ".join(ast.unparse(base) for base in node.bases)
                snapshot[f"{prefix}::{node.name}"] = {
                    "signature": f"class {node.name}({bases})" if bases else f"class {node.name}",
                    "docstring": ast.get_docstring(node, clean=False) or "",
                }
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and not member.name.startswith("_"):
                        snapshot[f"{prefix}::{node.name}.{member.name}"] = _callable_contract(member)
    return snapshot


def _callable_contract(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, str]:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return {
        "signature": f"{prefix} {node.name}({ast.unparse(node.args)}){returns}",
        "docstring": ast.get_docstring(node, clean=False) or "",
    }
