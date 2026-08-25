from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from integrations.harbor.experimental.tb3_prelaunch_route_check import (
    build_prelaunch_route_receipt,
    validate_prelaunch_route_receipt,
    write_prelaunch_route_receipt,
)


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v4.json"
ADAPTER = (
    "integrations.harbor.statem_codex_thin_family_v4p76_exp:"
    "ThinFamilyV4p76ExperimentalStatemCodex"
)
PRACTICE = "structured_transformation_compact"
MATCHING_INSTRUCTION = (
    "Repair the parser for malformed nested encoded input while preserving ordering."
)


class Tb3PrelaunchRouteCheckTest(unittest.TestCase):
    def _dataset(self, root: Path, instruction: str = MATCHING_INSTRUCTION) -> Path:
        task = root / "sample"
        task.mkdir(parents=True)
        (task / "instruction.md").write_text(instruction, encoding="utf-8")
        return root

    def _kwargs(self, **overrides: str) -> list[str]:
        values = {
            "activation_mode": "active",
            "development_practice_id": PRACTICE,
            "practice_catalog_path": str(CATALOG),
        }
        values.update(overrides)
        return [f"{key}={value}" for key, value in values.items()]

    def _build(self, dataset: Path, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "dataset_path": dataset,
            "task": "terminal-bench/sample",
            "job_name": "prelaunch-test",
            "agent_name": "thin-family-test",
            "agent_import_path": ADAPTER,
            "agent_kwargs": self._kwargs(),
            "expected_practice_id": PRACTICE,
            "catalog_path": CATALOG,
        }
        values.update(overrides)
        return build_prelaunch_route_receipt(**values)

    def test_exact_visible_route_match_is_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            receipt = self._build(self._dataset(Path(temp_dir)))
        self.assertEqual(receipt["decision"], "admit")
        self.assertEqual(receipt["selected_practice_id"], PRACTICE)
        self.assertEqual(validate_prelaunch_route_receipt(receipt), [])

    def test_different_visible_route_is_rejected(self) -> None:
        instruction = (
            "Improve graph search performance and cache scaling while preserving "
            "exact semantics."
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = self._dataset(Path(temp_dir), instruction)
            receipt = self._build(dataset)
        self.assertEqual(receipt["decision"], "reject")
        self.assertEqual(receipt["reason"], "visible_route_selected_different_practice")
        self.assertNotEqual(receipt["selected_practice_id"], PRACTICE)

    def test_runtime_catalog_and_expected_practice_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = self._dataset(Path(temp_dir))
            with self.assertRaisesRegex(ValueError, "catalogs do not match"):
                self._build(
                    dataset,
                    agent_kwargs=self._kwargs(
                        practice_catalog_path=str(Path(temp_dir) / "other.json")
                    ),
                )
            with self.assertRaisesRegex(ValueError, "development_practice_id"):
                self._build(
                    dataset,
                    agent_kwargs=self._kwargs(development_practice_id="other"),
                )

    def test_unknown_field_and_tampering_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            receipt = self._build(self._dataset(Path(temp_dir)))
        unknown = copy.deepcopy(receipt)
        unknown["extra"] = True
        self.assertTrue(
            any("unknown fields" in item for item in validate_prelaunch_route_receipt(unknown))
        )
        tampered = copy.deepcopy(receipt)
        tampered["decision"] = "reject"
        errors = validate_prelaunch_route_receipt(tampered)
        self.assertIn("decision does not match the selected practice", errors)
        self.assertIn("receipt_sha256 mismatch", errors)

    def test_receipt_write_is_validated_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            receipt = self._build(self._dataset(root / "dataset"))
            destination = root / "receipts" / "route.json"
            self.assertEqual(
                write_prelaunch_route_receipt(receipt, destination),
                destination.resolve(),
            )
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), receipt)
            self.assertEqual(list(destination.parent.glob(".*.tmp")), [])

            invalid = copy.deepcopy(receipt)
            invalid["instruction_sha256"] = "not-a-sha"
            with self.assertRaisesRegex(ValueError, "lowercase SHA256"):
                write_prelaunch_route_receipt(invalid, destination)

    def test_cli_prelaunch_only_finishes_before_harbor_or_auth_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = self._dataset(root / "dataset")
            receipt = root / "receipt.json"
            command = [
                sys.executable,
                str(REPO / ".statem" / "benchmarks" / "run_harbor_batch.py"),
                "--dataset-path",
                str(dataset),
                "--task",
                "terminal-bench/sample",
                "--job-name",
                "prelaunch-cli-test",
                "--agent-name",
                "thin-family-test",
                "--agent-import-path",
                ADAPTER,
                "--agent-kwarg",
                "activation_mode=active",
                "--agent-kwarg",
                f"development_practice_id={PRACTICE}",
                "--agent-kwarg",
                f"practice_catalog_path={CATALOG}",
                "--prelaunch-expected-practice",
                PRACTICE,
                "--prelaunch-practice-catalog",
                str(CATALOG),
                "--prelaunch-route-receipt",
                str(receipt),
                "--prelaunch-only",
            ]
            env = os.environ.copy()
            env.pop("OPENAI_API_KEY", None)
            env["STATEM_HARBOR_BIN"] = str(root / "missing-harbor")
            completed = subprocess.run(
                command,
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Prelaunch route: admit", completed.stdout)
            self.assertTrue(receipt.is_file())

    def test_cli_rejects_mismatch_and_preserves_receipt_before_harbor(self) -> None:
        instruction = (
            "Improve graph search performance and cache scaling while preserving "
            "exact semantics."
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = self._dataset(root / "dataset", instruction)
            receipt_path = root / "receipt.json"
            command = [
                sys.executable,
                str(REPO / ".statem" / "benchmarks" / "run_harbor_batch.py"),
                "--dataset-path",
                str(dataset),
                "--task",
                "terminal-bench/sample",
                "--job-name",
                "prelaunch-cli-reject",
                "--agent-name",
                "thin-family-test",
                "--agent-import-path",
                ADAPTER,
                "--agent-kwarg",
                "activation_mode=active",
                "--agent-kwarg",
                f"development_practice_id={PRACTICE}",
                "--agent-kwarg",
                f"practice_catalog_path={CATALOG}",
                "--prelaunch-expected-practice",
                PRACTICE,
                "--prelaunch-practice-catalog",
                str(CATALOG),
                "--prelaunch-route-receipt",
                str(receipt_path),
                "--prelaunch-only",
            ]
            env = os.environ.copy()
            env.pop("OPENAI_API_KEY", None)
            env["STATEM_HARBOR_BIN"] = str(root / "missing-harbor")
            completed = subprocess.run(
                command,
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("prelaunch route rejected", completed.stderr)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["decision"], "reject")
            self.assertEqual(
                receipt["reason"],
                "visible_route_selected_different_practice",
            )


if __name__ == "__main__":
    unittest.main()
