from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any


def stable_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_declarations(value: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(value, dict) or set(value) != {"task", "artifacts"}:
        raise ValueError("declarations require exactly task and artifacts")
    task = _text(value["task"], "task")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("artifacts must be a non-empty list")

    normalized: list[dict[str, Any]] = []
    for index, artifact in enumerate(artifacts):
        if isinstance(artifact, str):
            normalized.append(
                {"source": _text(artifact, f"artifacts[{index}]"), "service": None}
            )
            continue
        if not isinstance(artifact, dict):
            raise ValueError(f"artifacts[{index}] must be a string or object")
        if set(artifact) - {"source", "service"} or "source" not in artifact:
            raise ValueError(
                f"artifacts[{index}] object allows only source and service"
            )
        service = artifact.get("service")
        normalized.append(
            {
                "source": _text(artifact["source"], f"artifacts[{index}].source"),
                "service": (
                    _text(service, f"artifacts[{index}].service")
                    if service is not None
                    else None
                ),
            }
        )
    identities = [(item["service"], item["source"]) for item in normalized]
    if len(set(identities)) != len(identities):
        raise ValueError("declared artifact identities must be unique")
    return task, normalized


def _normalize_manifest(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("artifact manifest must be a list")
    normalized: list[dict[str, str]] = []
    required = {"source", "destination", "type", "status"}
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValueError(f"manifest[{index}] is missing required fields")
        normalized.append(
            {
                field: _text(item[field], f"manifest[{index}].{field}")
                for field in sorted(required)
            }
        )
    return normalized


def _safe_destination(root: Path, destination: str) -> Path | None:
    pure = PurePosixPath(destination)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    resolved_root = root.resolve()
    resolved = (root / Path(*pure.parts)).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _empty_artifact(path: Path) -> bool:
    if path.is_file():
        return path.stat().st_size == 0
    if path.is_dir():
        return not any(child.is_file() for child in path.rglob("*"))
    return True


def _artifact_descriptor(*, source: str, destination: str, path: Path) -> dict[str, Any]:
    if path.is_file():
        return {
            "source": source,
            "destination": destination,
            "type": "file",
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }
    files = sorted(child for child in path.rglob("*") if child.is_file())
    digest = hashlib.sha256()
    total_bytes = 0
    for child in files:
        size = child.stat().st_size
        total_bytes += size
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha256(child).encode("ascii"))
        digest.update(b"\n")
    return {
        "source": source,
        "destination": destination,
        "type": "directory",
        "file_count": len(files),
        "size_bytes": total_bytes,
        "tree_sha256": digest.hexdigest(),
    }


def evaluate_artifacts(
    *,
    declarations: Any,
    manifest: Any,
    artifact_root: Path,
) -> dict[str, Any]:
    task, declared = _normalize_declarations(declarations)
    entries = _normalize_manifest(manifest)
    by_source: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        by_source.setdefault(entry["source"], []).append(entry)

    declared_sources = {item["source"] for item in declared}
    missing_sources: list[str] = []
    duplicate_sources: list[str] = []
    failed_sources: list[dict[str, str]] = []
    unsafe_destinations: list[str] = []
    absent_destinations: list[str] = []
    empty_destinations: list[str] = []
    observed_destinations: list[dict[str, Any]] = []
    matched_count = 0

    for item in declared:
        source = item["source"]
        matches = by_source.get(source, [])
        if not matches:
            missing_sources.append(source)
            continue
        if len(matches) != 1:
            duplicate_sources.append(source)
            continue
        matched_count += 1
        entry = matches[0]
        if entry["status"] != "ok":
            failed_sources.append({"source": source, "status": entry["status"]})
            continue
        destination = _safe_destination(artifact_root, entry["destination"])
        if destination is None:
            unsafe_destinations.append(entry["destination"])
        elif not destination.exists():
            absent_destinations.append(entry["destination"])
        elif _empty_artifact(destination):
            empty_destinations.append(entry["destination"])
        else:
            observed_destinations.append(
                _artifact_descriptor(
                    source=source,
                    destination=entry["destination"],
                    path=destination,
                )
            )

    extra_sources = sorted(
        source for source in by_source if source not in declared_sources
    )
    blocking = any(
        (
            missing_sources,
            duplicate_sources,
            failed_sources,
            unsafe_destinations,
            absent_destinations,
            empty_destinations,
        )
    )
    receipt = {
        "version": 1,
        "kind": "tb3_public_artifact_gate",
        "task": task,
        "declarations_sha256": stable_sha256(
            {"task": task, "artifacts": declared}
        ),
        "manifest_sha256": stable_sha256(entries),
        "declared_count": len(declared),
        "manifest_entry_count": len(entries),
        "matched_count": matched_count,
        "missing_sources": sorted(missing_sources),
        "duplicate_sources": sorted(duplicate_sources),
        "failed_sources": sorted(failed_sources, key=lambda item: item["source"]),
        "unsafe_destinations": sorted(unsafe_destinations),
        "absent_destinations": sorted(absent_destinations),
        "empty_destinations": sorted(empty_destinations),
        "observed_destinations": sorted(
            observed_destinations, key=lambda item: item["source"]
        ),
        "extra_sources": extra_sources,
        "complete": not blocking,
    }
    receipt["receipt_sha256"] = stable_sha256(receipt)
    return receipt


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate public TB3 artifact-harvest completeness."
    )
    parser.add_argument("--declarations", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)

    receipt = evaluate_artifacts(
        declarations=_read_json(args.declarations),
        manifest=_read_json(args.manifest),
        artifact_root=args.artifact_root,
    )
    _write_json_atomic(args.output, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 2 if args.require_complete and not receipt["complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
