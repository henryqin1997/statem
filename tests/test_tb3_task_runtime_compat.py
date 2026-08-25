from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from integrations.harbor.experimental.tb3_task_runtime_compat import (
    build_task_runtime_compat_receipt,
    validate_task_runtime_compat_receipt,
    write_task_runtime_compat_receipt,
)


REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / ".statem" / "benchmarks" / "run_harbor_batch.py"


class Tb3TaskRuntimeCompatTest(unittest.TestCase):
    def _dataset(self, root: Path, artifacts: str) -> Path:
        task = root / "sample"
        task.mkdir(parents=True)
        (task / "task.toml").write_text(
            'schema_version = "1.3"\n' + artifacts + "\n",
            encoding="utf-8",
        )
        return root

    def _build(
        self, dataset: Path, supported: list[str]
    ) -> dict[str, object]:
        return build_task_runtime_compat_receipt(
            dataset_path=dataset,
            task="terminal-bench/sample",
            job_name="runtime-field-test",
            runtime_name="harbor",
            runtime_version="test",
            supported_artifact_fields=supported,
        )

    def test_supported_legacy_artifact_is_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = self._dataset(Path(temp_dir), 'artifacts = ["/results/x"]')
            receipt = self._build(dataset, ["source", "destination", "exclude"])
        self.assertEqual(receipt["decision"], "admit")
        self.assertEqual(receipt["declared_artifact_fields"], ["source"])
        self.assertEqual(validate_task_runtime_compat_receipt(receipt), [])

    def test_unsupported_service_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = self._dataset(
                Path(temp_dir),
                'artifacts = [{ source = "/results/x", service = "loadgen" }]',
            )
            receipt = self._build(dataset, ["source", "destination", "exclude"])
        self.assertEqual(receipt["decision"], "reject")
        self.assertEqual(receipt["unsupported_artifact_fields"], ["service"])
        self.assertEqual(validate_task_runtime_compat_receipt(receipt), [])

    def test_service_field_is_admitted_when_runtime_models_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = self._dataset(
                Path(temp_dir),
                'artifacts = [{ source = "/results/x", service = "loadgen" }]',
            )
            receipt = self._build(
                dataset, ["source", "destination", "exclude", "service"]
            )
        self.assertEqual(receipt["decision"], "admit")

    def test_receipt_validation_rejects_unknown_and_tampered_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = self._dataset(Path(temp_dir), 'artifacts = ["/results/x"]')
            receipt = self._build(dataset, ["source"])
        unknown = copy.deepcopy(receipt)
        unknown["extra"] = True
        self.assertTrue(
            any(
                "unknown fields" in error
                for error in validate_task_runtime_compat_receipt(unknown)
            )
        )
        tampered = copy.deepcopy(receipt)
        tampered["decision"] = "reject"
        errors = validate_task_runtime_compat_receipt(tampered)
        self.assertIn("decision does not match unsupported fields", errors)
        self.assertIn("receipt_sha256 mismatch", errors)

    def test_receipt_write_is_atomic_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = self._dataset(root / "dataset", 'artifacts = ["/results/x"]')
            receipt = self._build(dataset, ["source"])
            destination = root / "receipts" / "runtime.json"
            self.assertEqual(
                write_task_runtime_compat_receipt(receipt, destination),
                destination.resolve(),
            )
            self.assertEqual(json.loads(destination.read_text()), receipt)
            self.assertEqual(list(destination.parent.glob(".*.tmp")), [])

    def test_cli_rejects_before_auth_or_environment_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = self._dataset(
                root / "dataset",
                'artifacts = [{ source = "/results/x", service = "loadgen" }]',
            )
            receipt = root / "runtime.json"
            harbor_bin = root / "harbor"
            harbor_bin.write_text("", encoding="utf-8")
            harbor_python = root / "harbor-python"
            harbor_python.write_text(
                f"#!{sys.executable}\n"
                "import json\n"
                "print(json.dumps({'runtime_name':'harbor',"
                "'runtime_version':'test',"
                "'artifact_fields':['destination','exclude','source']}))\n",
                encoding="utf-8",
            )
            harbor_python.chmod(0o755)
            env = os.environ.copy()
            env["STATEM_HARBOR_BIN"] = str(harbor_bin)
            env["STATEM_HARBOR_PYTHON"] = str(harbor_python)
            env.pop("OPENAI_API_KEY", None)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--dataset-path",
                    str(dataset),
                    "--task",
                    "terminal-bench/sample",
                    "--job-name",
                    "runtime-cli-test",
                    "--prelaunch-task-field-receipt",
                    str(receipt),
                    "--prelaunch-only",
                ],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("prelaunch task fields rejected", completed.stderr)
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(saved["decision"], "reject")
            self.assertEqual(saved["unsupported_artifact_fields"], ["service"])


if __name__ == "__main__":
    unittest.main()
