from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

try:
    from .artifact_identity import stable_sha256
except ImportError:
    from artifact_identity import stable_sha256  # type: ignore[no-redef]


DEFAULT_CATALOG = Path("/tmp/statem-verification-checks/develop-family-router-v1.yaml")
DEFAULT_PROFILE = Path("/tmp/statem-verification-checks/multirole/review-profile.json")
DEFAULT_OUTPUT = Path("/tmp/statem-verification-checks/family/family-selection.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select one deterministic development family from a bound review profile."
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--review-profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        receipt = select_family(
            catalog=_read_yaml(args.catalog),
            review_profile=_read_json(args.review_profile),
        )
        _write_json(args.output, receipt)
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"develop family router: {exc}")
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def select_family(
    *,
    catalog: dict[str, Any],
    review_profile: dict[str, Any],
) -> dict[str, Any]:
    if catalog.get("version") != 1 or not isinstance(catalog.get("families"), dict):
        raise ValueError("family catalog must be a version-1 mapping")
    if (
        review_profile.get("version") != 1
        or review_profile.get("kind") != "review_profile_selection"
    ):
        raise ValueError("expected a version-1 review_profile_selection receipt")
    primary = _text(review_profile.get("primary"))
    secondary = review_profile.get("secondary")
    if (
        not primary
        or not isinstance(secondary, list)
        or not all(_text(item) for item in secondary)
    ):
        raise ValueError("review profile primary and secondary selections are required")

    matches: list[tuple[str, dict[str, Any]]] = []
    for family_id, raw in catalog["families"].items():
        if not isinstance(raw, dict):
            raise ValueError(f"family {family_id!r} must be a mapping")
        profiles = raw.get("primary_profiles")
        if (
            not isinstance(profiles, list)
            or not profiles
            or not all(_text(item) for item in profiles)
        ):
            raise ValueError(f"family {family_id!r} requires primary_profiles")
        if primary in profiles:
            matches.append((_text(family_id), raw))
    if len(matches) != 1:
        raise ValueError(
            f"primary review profile {primary!r} must select exactly one family; got {len(matches)}"
        )

    family_id, family = matches[0]
    reserve = family.get("retry_reserve_seconds")
    if not isinstance(reserve, int) or reserve < 300:
        raise ValueError("family retry_reserve_seconds must be an integer of at least 300")
    contract_scope = _bounded_text(family.get("contract_scope"), "contract_scope")
    practice_scope = _bounded_text(family.get("practice_scope"), "practice_scope")
    run_id = _text(review_profile.get("run_id") or os.environ.get("STATEM_RUN_ID"))
    node = _text(review_profile.get("node") or os.environ.get("STATEM_CURRENT"))
    entry_id = _text(review_profile.get("entry_id") or os.environ.get("STATEM_ENTRY_ID"))
    if not all((run_id, node, entry_id)):
        raise ValueError("family selection requires StateM run, node, and entry identity")

    return {
        "version": 1,
        "kind": "develop_family_selection",
        "run_id": run_id,
        "node": node,
        "entry_id": entry_id,
        "family_id": family_id,
        "primary_profile": primary,
        "secondary_profiles": list(secondary),
        "retry_reserve_seconds": reserve,
        "contract_scope": contract_scope,
        "practice_scope": practice_scope,
        "selection_basis": "bound_primary_reviewer_profile",
        "review_profile_sha256": stable_sha256(review_profile),
        "catalog_sha256": stable_sha256(catalog),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _bounded_text(value: Any, field: str) -> str:
    text = _text(value)
    if not text or len(text) > 800:
        raise ValueError(f"family {field} must contain 1-800 characters")
    return text


def _text(value: Any) -> str:
    return str(value or "").strip()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
