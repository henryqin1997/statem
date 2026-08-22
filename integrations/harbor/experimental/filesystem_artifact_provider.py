from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import (
        DEFAULT_EXCLUDED_NAMES,
        DEFAULT_EXCLUDED_PARTS,
        artifact_identity,
        file_sha256,
        stable_sha256,
    )
except ImportError:
    from artifact_identity import (  # type: ignore[no-redef]
        DEFAULT_EXCLUDED_NAMES,
        DEFAULT_EXCLUDED_PARTS,
        artifact_identity,
        file_sha256,
        stable_sha256,
    )


DEFAULT_DIR = Path("/tmp/statem-verification-checks/artifact-provider")
DEFAULT_BASELINE = DEFAULT_DIR / "baseline-snapshot.json"
DEFAULT_CANDIDATE = DEFAULT_DIR / "candidate-snapshot.json"
DEFAULT_APPLICATION = DEFAULT_DIR / "application.json"
SNAPSHOT_KINDS = {"baseline", "candidate"}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "snapshot":
            receipt = snapshot_artifact(
                artifact_root=args.artifact_root,
                provider_root=args.provider_root,
                kind=args.kind,
                expected_receipt=(
                    _read_json(args.expected_receipt)
                    if args.expected_receipt is not None
                    else None
                ),
            )
            _write_json(args.output, receipt)
        elif args.action == "apply":
            receipt = apply_snapshot(
                artifact_root=args.artifact_root,
                snapshot=_read_json(args.snapshot),
                mode=args.mode,
            )
            _write_json(args.output, receipt)
        elif args.action == "export":
            receipt = export_provider_bundle(
                provider_root=args.provider_root,
                destination=args.destination,
                receipt_only=args.receipt_only,
            )
            if args.output is not None:
                _write_json(args.output, receipt)
        else:
            parser.error(f"unknown action: {args.action}")
            return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"filesystem artifact provider: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provider-owned immutable snapshots for filesystem benchmark artifacts."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--artifact-root", type=Path, default=Path("/app"))
    snapshot.add_argument("--provider-root", type=Path, default=DEFAULT_DIR / "snapshots")
    snapshot.add_argument("--kind", choices=sorted(SNAPSHOT_KINDS), required=True)
    snapshot.add_argument("--expected-receipt", type=Path)
    snapshot.add_argument("--output", type=Path, required=True)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--artifact-root", type=Path, default=Path("/app"))
    apply_parser.add_argument("--snapshot", type=Path, required=True)
    apply_parser.add_argument(
        "--mode", choices=("activate", "quarantine", "restore"), required=True
    )
    apply_parser.add_argument("--output", type=Path, default=DEFAULT_APPLICATION)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--provider-root", type=Path, default=DEFAULT_DIR)
    export_parser.add_argument("--destination", type=Path, required=True)
    export_parser.add_argument("--receipt-only", action="store_true")
    export_parser.add_argument("--output", type=Path)
    return parser


def snapshot_artifact(
    *,
    artifact_root: Path,
    provider_root: Path,
    kind: str,
    expected_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kind not in SNAPSHOT_KINDS:
        raise ValueError(f"unsupported snapshot kind: {kind}")
    context = _state_context()
    artifact_root = artifact_root.expanduser().resolve()
    identity = artifact_identity(artifact_root)
    mode_manifest = _mode_manifest(artifact_root)
    if expected_receipt is not None:
        expected_kind = "contract_seal" if kind == "baseline" else "candidate_proposal"
        _require_receipt(expected_receipt, expected_kind)
        key = "baseline_artifact_identity" if kind == "baseline" else "candidate_artifact_identity"
        if expected_receipt.get(key) != identity:
            raise ValueError(f"live {kind} identity does not match {expected_kind}")

    snapshot_id = stable_sha256(
        {
            "run_id": context["run_id"],
            "entry_id": context["entry_id"],
            "kind": kind,
            "artifact_identity": identity,
        }
    )[:24]
    provider_root = provider_root.expanduser().resolve()
    provider_root.mkdir(parents=True, exist_ok=True)
    destination = provider_root / f"{kind}-{snapshot_id}"
    if destination.exists():
        if artifact_identity(destination) != identity:
            raise ValueError("immutable snapshot path already contains another artifact")
    else:
        temporary = provider_root / f".{destination.name}.{os.getpid()}.tmp"
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        _copy_artifact(artifact_root, temporary)
        if artifact_identity(temporary) != identity:
            shutil.rmtree(temporary)
            raise ValueError("snapshot identity differs from the live artifact")
        os.replace(temporary, destination)
        _make_read_only(destination)

    return {
        "version": 1,
        "kind": "filesystem_artifact_snapshot",
        **context,
        "producer": {
            "agent_id": f"artifact-provider:{context['run_id']}:{context['entry_id']}",
            "role": "artifact_provider",
        },
        "snapshot_kind": kind,
        "artifact_identity": identity,
        "snapshot_path": str(destination),
        "snapshot_identity": artifact_identity(destination),
        "mode_manifest": mode_manifest,
        "immutable": True,
        "expected_receipt_sha256": (
            stable_sha256(expected_receipt) if expected_receipt is not None else None
        ),
        "created_at": _now(),
    }


def apply_snapshot(
    *,
    artifact_root: Path,
    snapshot: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    _require_receipt(snapshot, "filesystem_artifact_snapshot")
    context = _state_context()
    artifact_root = artifact_root.expanduser().resolve()
    snapshot_root = Path(_text(snapshot.get("snapshot_path"))).expanduser().resolve()
    expected = _text(snapshot.get("artifact_identity"))
    if not snapshot_root.is_dir() or artifact_identity(snapshot_root) != expected:
        raise ValueError("snapshot is missing or no longer matches its sealed identity")

    if mode in {"activate", "quarantine"}:
        if snapshot.get("snapshot_kind") != "candidate":
            raise ValueError(f"{mode} requires a candidate snapshot")
        observed_before = artifact_identity(artifact_root)
        if mode == "activate" and observed_before != expected:
            raise ValueError("live artifact is not the snapshotted candidate")
        if mode == "quarantine" and observed_before != expected:
            rescue = snapshot_artifact(
                artifact_root=artifact_root,
                provider_root=snapshot_root.parent,
                kind="candidate",
            )
            try:
                _replace_artifact_contents(snapshot_root, artifact_root)
                _restore_modes(artifact_root, snapshot.get("mode_manifest"))
                if artifact_identity(artifact_root) != expected:
                    raise ValueError(
                        "selected candidate identity does not match the reviewed snapshot"
                    )
            except Exception:
                rescue_root = Path(rescue["snapshot_path"])
                _replace_artifact_contents(rescue_root, artifact_root)
                _restore_modes(artifact_root, rescue.get("mode_manifest"))
                raise
            operation = "transactional_candidate_selection"
        else:
            operation = (
                "verified_quarantined_candidate"
                if mode == "quarantine"
                else "verified_live_candidate"
            )
    elif mode == "restore":
        if snapshot.get("snapshot_kind") != "baseline":
            raise ValueError("restore requires a baseline snapshot")
        rescue = snapshot_artifact(
            artifact_root=artifact_root,
            provider_root=snapshot_root.parent,
            kind="candidate",
        )
        try:
            _replace_artifact_contents(snapshot_root, artifact_root)
            _restore_modes(artifact_root, snapshot.get("mode_manifest"))
            if artifact_identity(artifact_root) != expected:
                raise ValueError("restored artifact identity does not match the baseline")
        except Exception:
            rescue_root = Path(rescue["snapshot_path"])
            _replace_artifact_contents(rescue_root, artifact_root)
            _restore_modes(artifact_root, rescue.get("mode_manifest"))
            raise
        operation = "transactional_restore"
    else:
        raise ValueError(f"unsupported application mode: {mode}")

    return {
        "version": 1,
        "kind": "filesystem_artifact_application",
        **context,
        "producer": {
            "agent_id": f"artifact-provider:{context['run_id']}:{context['entry_id']}",
            "role": "artifact_provider",
        },
        "mode": mode,
        "operation": operation,
        "snapshot_receipt_sha256": stable_sha256(snapshot),
        "expected_artifact_identity": expected,
        "observed_artifact_identity": artifact_identity(artifact_root),
        "verified": True,
        "created_at": _now(),
    }


def export_provider_bundle(
    *,
    provider_root: Path,
    destination: Path,
    receipt_only: bool = False,
) -> dict[str, Any]:
    provider_root = provider_root.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not provider_root.is_dir():
        raise ValueError("provider root is missing")
    if destination == provider_root or provider_root in destination.parents:
        raise ValueError("provider export destination must be outside the provider root")
    destination.mkdir(parents=True, exist_ok=True)

    file_count = 0
    if receipt_only:
        export_sources = []
        for path in sorted(provider_root.glob("*.json")):
            try:
                kind = _text(_read_json(path).get("kind"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if kind in {
                "filesystem_artifact_snapshot",
                "filesystem_artifact_application",
            }:
                export_sources.append(path)
    else:
        export_sources = sorted(provider_root.rglob("*"))
    for source in export_sources:
        relative = source.relative_to(provider_root)
        target = destination / relative
        if source.is_symlink():
            if target.exists() or target.is_symlink():
                _remove_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.readlink(source))
        elif source.is_dir():
            if target.is_symlink() or (target.exists() and not target.is_dir()):
                _remove_path(target)
            target.mkdir(parents=True, exist_ok=True)
            target.chmod(0o755)
        elif source.is_file():
            if target.exists() or target.is_symlink():
                _remove_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target, follow_symlinks=False)
            target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
            file_count += 1

    verified_snapshots: list[dict[str, Any]] = []
    for receipt_path in sorted(provider_root.glob("*snapshot.json")):
        receipt = _read_json(receipt_path)
        _require_receipt(receipt, "filesystem_artifact_snapshot")
        source_snapshot = Path(_text(receipt.get("snapshot_path"))).resolve()
        try:
            relative = source_snapshot.relative_to(provider_root)
        except ValueError as exc:
            raise ValueError("snapshot locator escapes the provider root") from exc
        observed_root = source_snapshot if receipt_only else destination / relative
        observed = artifact_identity(observed_root)
        expected = _text(receipt.get("snapshot_identity"))
        if observed != expected:
            raise ValueError("exported snapshot identity does not match its receipt")
        verified_snapshots.append(
            {
                "snapshot_kind": _text(receipt.get("snapshot_kind")),
                "artifact_identity": observed,
                "relative_path": None if receipt_only else relative.as_posix(),
                "content_exported": not receipt_only,
            }
        )

    if not verified_snapshots:
        raise ValueError("provider export contains no verified snapshots")
    return {
        "version": 1,
        "kind": "filesystem_artifact_provider_export",
        "provider_root": str(provider_root),
        "destination": str(destination),
        "receipt_only": receipt_only,
        "regular_file_count": file_count,
        "verified_snapshots": verified_snapshots,
        "created_at": _now(),
    }


def _replace_artifact_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    source_paths = _artifact_paths(source)
    destination_paths = _artifact_paths(destination)

    for relative in sorted(
        destination_paths.keys() - source_paths.keys(),
        key=lambda path: (len(path.parts), path.as_posix()),
        reverse=True,
    ):
        _remove_path(destination / relative)

    for relative, source_path in sorted(
        source_paths.items(),
        key=lambda item: (len(item[0].parts), item[0].as_posix()),
    ):
        target = destination / relative
        if source_path.is_symlink():
            if target.is_symlink() and os.readlink(target) == os.readlink(source_path):
                continue
            if target.exists() or target.is_symlink():
                _remove_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.readlink(source_path))
        elif source_path.is_dir():
            if target.is_symlink() or (target.exists() and not target.is_dir()):
                _remove_path(target)
            target.mkdir(parents=True, exist_ok=True)
        elif source_path.is_file():
            if (
                target.is_file()
                and not target.is_symlink()
                and file_sha256(target) == file_sha256(source_path)
            ):
                continue
            if target.exists() or target.is_symlink():
                _remove_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{os.getpid()}.restore")
            shutil.copy2(source_path, temporary, follow_symlinks=False)
            os.replace(temporary, target)


def _artifact_paths(root: Path) -> dict[Path, Path]:
    paths: dict[Path, Path] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in DEFAULT_EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.name in DEFAULT_EXCLUDED_NAMES:
            continue
        paths[relative] = path
    return paths


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _copy_artifact(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in DEFAULT_EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.name in DEFAULT_EXCLUDED_NAMES:
            continue
        target = destination / relative
        if path.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.readlink(path))
        elif path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target, follow_symlinks=False)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        path.chmod(mode & ~0o222)
    root.chmod(root.stat().st_mode & ~0o222)


def _mode_manifest(root: Path) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in DEFAULT_EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.name in DEFAULT_EXCLUDED_NAMES or path.is_symlink():
            continue
        if path.is_file() or path.is_dir():
            manifest.append(
                {
                    "path": relative.as_posix(),
                    "mode": path.stat().st_mode & 0o777,
                }
            )
    return manifest


def _restore_modes(root: Path, manifest: Any) -> None:
    if not isinstance(manifest, list):
        raise ValueError("snapshot mode manifest is missing")
    for item in sorted(
        manifest,
        key=lambda value: len(Path(str(value.get("path", ""))).parts),
        reverse=True,
    ):
        if not isinstance(item, dict):
            raise ValueError("snapshot mode manifest is invalid")
        path = root / _text(item.get("path"))
        mode = item.get("mode")
        if not path.exists() or path.is_symlink() or not isinstance(mode, int):
            raise ValueError("snapshot mode manifest does not match restored artifact")
        if path.stat().st_mode & 0o777 != mode:
            path.chmod(mode)


def _state_context() -> dict[str, str]:
    run_id = _text(os.environ.get("STATEM_RUN_ID"))
    state_dir = Path(os.environ.get("STATEM_STATE_DIR") or ".statem").expanduser().resolve()
    state: dict[str, Any] = {}
    if run_id:
        for candidate in (state_dir / "runs").glob("*/state.json"):
            try:
                value = _read_json(candidate)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if value.get("run_id") == run_id:
                state = value
                break
    context = {
        "run_id": run_id or _text(state.get("run_id")),
        "node": _text(state.get("current") or os.environ.get("STATEM_CURRENT")),
        "entry_id": _text(state.get("current_entry_id") or os.environ.get("STATEM_ENTRY_ID")),
    }
    if not all(context.values()):
        raise ValueError("StateM run, node, and entry identity are required")
    return context


def _require_receipt(receipt: dict[str, Any], kind: str) -> None:
    if receipt.get("version") != 1 or receipt.get("kind") != kind:
        raise ValueError(f"expected version-1 {kind} receipt")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()) or "entry"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
