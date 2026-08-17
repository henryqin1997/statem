from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

try:
    from integrations.harbor.experimental.deepseek_gpt55_review_overlay import (
        render_review_lens as render_full_review_lens,
    )
    from integrations.harbor.experimental.deepseek_gpt55_review_overlay import (
        select_review_lens as select_full_review_lens,
    )
    from integrations.harbor.experimental.deepseek_gpt55_review_overlay import (
        validate_receipt as validate_full_receipt,
    )
except ImportError:
    render_full_review_lens = None
    select_full_review_lens = None
    validate_full_receipt = None
from integrations.harbor.experimental.deepseek_server_readiness_subset import (
    load_runbook,
    receipt_template,
    render_review_lens,
    select_review_lens,
    validate_receipt,
)


class DeepSeekServerReadinessSubsetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runbook = load_runbook()

    def test_trigger_boundary_is_self_contained(self) -> None:
        positive_cases = (
            "Set up a package server on port 8080, leave it running in the background, "
            "and make it usable by pip install through its public URL.",
            "Create a gRPC server on a port and keep it running in the background.",
            "Start a QEMU virtual machine and expose SSH to a fresh client.",
        )
        negative_cases = (
            "Implement a small HTTP endpoint and run the provided public test.",
            "Start a gRPC server for the duration of a public unit test.",
            "Leave a background worker running without a public client interface.",
        )
        for task_text in positive_cases:
            with self.subTest(task_text=task_text):
                selection = select_review_lens(task_text, self.runbook)
                self.assertTrue(selection["selected"])
                self.assertEqual(
                    selection["lens"]["id"], "service_lifecycle_readiness"
                )
                self.assertIn(
                    "Separate launch, durable lifetime, protocol readiness",
                    render_review_lens(selection, self.runbook),
                )
        for task_text in negative_cases:
            with self.subTest(task_text=task_text):
                selection = select_review_lens(task_text, self.runbook)
                self.assertFalse(selection["selected"])
                self.assertEqual(render_review_lens(selection, self.runbook), "")

    @unittest.skipIf(
        select_full_review_lens is None,
        "full private policy adapter is not part of the public subset",
    )
    def test_trigger_matches_full_policy_for_server_readiness_boundary(self) -> None:
        assert select_full_review_lens is not None
        assert render_full_review_lens is not None
        cases = (
            "Set up a package server on port 8080, leave it running in the background, "
            "and make it usable by pip install through its public URL.",
            "Create a gRPC server on a port and keep it running in the background.",
            "Start a QEMU virtual machine and expose SSH to a fresh client.",
            "Implement a small HTTP endpoint and run the provided public test.",
            "Start a gRPC server for the duration of a public unit test.",
            "Leave a background worker running without a public client interface.",
        )
        for task_text in cases:
            with self.subTest(task_text=task_text):
                subset = select_review_lens(task_text, self.runbook)
                full = select_full_review_lens(task_text)
                self.assertEqual(subset, full)
                self.assertEqual(
                    render_review_lens(subset, self.runbook),
                    render_full_review_lens(full),
                )

    def test_subset_contains_only_one_family_and_one_lens(self) -> None:
        self.assertEqual(self.runbook["family"], "server_readiness")
        self.assertEqual(
            self.runbook["lens"]["id"], "service_lifecycle_readiness"
        )
        self.assertEqual(
            [item["name"] for item in self.runbook["selection"]["require_all_groups"]],
            ["service", "public_client", "persistence"],
        )
        self.assertNotIn("routes", self.runbook)
        self.assertNotIn("catalog", self.runbook)

    def test_subset_loads_without_site_packages(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                (
                    "from integrations.harbor.experimental."
                    "deepseek_server_readiness_subset import load_runbook; "
                    "assert load_runbook()['family'] == 'server_readiness'"
                ),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_receipt_contract_matches_full_policy(self) -> None:
        selection = select_review_lens(
            "Start an HTTP server on port 8080 in the background and leave it running "
            "for a fresh client connection.",
            self.runbook,
        )
        receipt = receipt_template(selection, self.runbook)
        assert receipt is not None
        receipt.update(
            {
                "status": "passed",
                "process_identity": "public process identity receipt",
                "parent_identity": "durable parent identity receipt",
                "session_identity": "detached session identity receipt",
                "detached_from_agent_session": True,
                "fresh_client_command": "task-visible client invocation",
                "fresh_client_result": "task-visible round trip passed",
            }
        )
        self.assertEqual(validate_receipt(selection, receipt, self.runbook), [])
        if validate_full_receipt is not None:
            self.assertEqual(validate_full_receipt(selection, receipt), [])

        receipt["detached_from_agent_session"] = False
        subset_errors = validate_receipt(selection, receipt, self.runbook)
        self.assertEqual(subset_errors, ["service is not detached from the agent session"])
        if validate_full_receipt is not None:
            self.assertEqual(subset_errors, validate_full_receipt(selection, receipt))

    def test_tampered_selection_cannot_weaken_receipt_contract(self) -> None:
        selection = select_review_lens(
            "Start an HTTP server on port 8080 in the background and leave it running "
            "for a fresh client connection.",
            self.runbook,
        )
        tampered = deepcopy(selection)
        tampered["lens"]["receipt"]["required_fields"] = []
        incomplete_receipt = {
            "lens_id": "service_lifecycle_readiness",
            "status": "passed",
            "detached_from_agent_session": True,
        }

        self.assertEqual(
            validate_receipt(tampered, incomplete_receipt, self.runbook),
            ["selection receipt fields do not match runbook"],
        )
        with self.assertRaisesRegex(
            ValueError, "selection receipt fields do not match runbook"
        ):
            render_review_lens(tampered, self.runbook)
        with self.assertRaisesRegex(
            ValueError, "selection receipt fields do not match runbook"
        ):
            receipt_template(tampered, self.runbook)

    def test_public_cli_selects_and_validates_a_receipt(self) -> None:
        module = (
            "integrations.harbor.experimental.deepseek_server_readiness_subset"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_path = root / "task.txt"
            task_path.write_text(
                "Start an HTTP server on port 8080 in the background and leave it "
                "running for a fresh client connection.",
                encoding="utf-8",
            )
            selected = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-m",
                    module,
                    "select",
                    "--task-text",
                    str(task_path),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(selected.returncode, 0, selected.stderr)
            selection = json.loads(selected.stdout)
            self.assertTrue(selection["selected"])

            selection_path = root / "selection.json"
            receipt_path = root / "receipt.json"
            selection_path.write_text(json.dumps(selection), encoding="utf-8")
            receipt = receipt_template(selection, self.runbook)
            assert receipt is not None
            receipt.update(
                {
                    "status": "passed",
                    "process_identity": "pid 123",
                    "parent_identity": "supervisor pid 1",
                    "session_identity": "session 456",
                    "detached_from_agent_session": True,
                    "fresh_client_command": "curl http://127.0.0.1:8080/health",
                    "fresh_client_result": "200 OK",
                }
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            validated = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-m",
                    module,
                    "validate",
                    "--selection",
                    str(selection_path),
                    "--receipt",
                    str(receipt_path),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertEqual(json.loads(validated.stdout)["status"], "passed")


if __name__ == "__main__":
    unittest.main()
