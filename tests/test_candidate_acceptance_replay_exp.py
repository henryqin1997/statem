from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from integrations.harbor.experimental.artifact_identity import (
    artifact_identity,
    stable_sha256,
)
from integrations.harbor.experimental.candidate_acceptance_replay import (
    MAX_STREAM_BYTES,
    replay_acceptance_checks,
)
from integrations.harbor.experimental.filesystem_artifact_provider import (
    snapshot_artifact,
)


class CandidateAcceptanceReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "worker.py").write_text("VALUE = 7\n", encoding="utf-8")
        self.state_dir = self.root / "state"
        self.run_id = "acceptance-replay-test"
        self.entry_id = "solve-entry"
        self.env = {
            "STATEM_STATE_DIR": str(self.state_dir),
            "STATEM_RUN_ID": self.run_id,
            "STATEM_AGENT_ID": "lead-solver",
            "STATEM_AGENT_ROLE": "solver",
        }
        self._state("solve", self.entry_id)
        identity = artifact_identity(self.app)
        self.proposal = {
            "version": 1,
            "kind": "candidate_proposal",
            "run_id": self.run_id,
            "node": "solve",
            "entry_id": self.entry_id,
            "producer": {"agent_id": "lead-solver", "role": "solver"},
            "candidate_artifact_identity": identity,
        }
        with patch.dict(os.environ, self.env, clear=False):
            self.snapshot = snapshot_artifact(
                artifact_root=self.app,
                provider_root=self.root / "provider",
                kind="candidate",
                expected_receipt=self.proposal,
            )
        self.acceptance = {
            "version": 1,
            "kind": "candidate_bound_acceptance_evidence",
            "run_id": self.run_id,
            "node": "solve",
            "entry_id": self.entry_id,
            "producer": {"agent_id": "lead-solver", "role": "solver"},
            "proposal_sha256": stable_sha256(self.proposal),
            "candidate_snapshot_sha256": stable_sha256(self.snapshot),
            "candidate_artifact_identity": identity,
            "attestation_scope": "solver_recorded_public_execution",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _state(self, node: str, entry_id: str) -> None:
        path = self.state_dir / "runs" / self.run_id / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "current": node,
                    "current_entry_id": entry_id,
                }
            ),
            encoding="utf-8",
        )

    def _plan(self, argv: list[str] | None = None) -> dict[str, object]:
        return {
            "candidate_artifact_identity": artifact_identity(self.app),
            "checks": [
                {
                    "check_id": "public-smoke",
                    "public_surface": "worker.py public value",
                    "method": "load the submitted module from the candidate copy",
                    "argv": argv
                    or [
                        sys.executable,
                        "-c",
                        "import pathlib; assert 'VALUE = 7' in pathlib.Path('worker.py').read_text()",
                    ],
                    "cwd": ".",
                    "timeout_seconds": 5,
                    "expected_exit_codes": [0],
                }
            ],
        }

    def _replay(
        self,
        plan: dict[str, object],
        *,
        existing: dict[str, object] | None = None,
    ) -> dict[str, object]:
        with patch.dict(os.environ, self.env, clear=False):
            return replay_acceptance_checks(
                plan=plan,
                proposal=self.proposal,
                acceptance_evidence=self.acceptance,
                candidate_snapshot=self.snapshot,
                artifact_root=self.app,
                work_root=self.root / "replays",
                existing_receipt=existing,
            )

    def _candidate_blind_inputs(
        self,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
        preflight: dict[str, object] = {
            "version": 1,
            "kind": "plan_preflight_evidence",
            "run_id": self.run_id,
            "node": "solve",
            "entry_id": self.entry_id,
            "acceptance_plan": {
                "requirements": [
                    {
                        "requirement_id": "public-boundaries",
                        "evidence_mode": "adapter_replay",
                        "required_strata": ["zero", "one"],
                    },
                    {
                        "requirement_id": "public-signature",
                        "evidence_mode": "adapter_replay",
                        "required_strata": ["call-shape"],
                    },
                    {
                        "requirement_id": "semantic-variant",
                        "evidence_mode": "paired_review",
                        "required_strata": ["variant-a", "variant-b"],
                    },
                ]
            },
        }
        proposal = {
            **self.proposal,
            "preflight_evidence_sha256": stable_sha256(preflight),
        }
        with patch.dict(os.environ, self.env, clear=False):
            snapshot = snapshot_artifact(
                artifact_root=self.app,
                provider_root=self.root / "blind-provider",
                kind="candidate",
                expected_receipt=proposal,
            )
        acceptance = {
            **self.acceptance,
            "proposal_sha256": stable_sha256(proposal),
            "candidate_snapshot_sha256": stable_sha256(snapshot),
        }
        plan = self._plan()
        plan["preflight_evidence_sha256"] = stable_sha256(preflight)
        plan["checks"][0]["requirement_ids"] = [
            "public-boundaries",
            "public-signature",
        ]
        return preflight, proposal, snapshot, acceptance | {"plan": plan}

    def _blind_replay(
        self,
        *,
        mutate_plan=None,
        require_strata_coverage: bool = False,
    ) -> dict[str, object]:
        preflight, proposal, snapshot, bundle = self._candidate_blind_inputs()
        plan = bundle.pop("plan")
        if require_strata_coverage:
            plan["checks"][0]["covered_strata"] = {
                "public-boundaries": ["zero", "one"],
                "public-signature": ["call-shape"],
            }
        if mutate_plan is not None:
            mutate_plan(plan)
        with patch.dict(os.environ, self.env, clear=False):
            return replay_acceptance_checks(
                plan=plan,
                proposal=proposal,
                acceptance_evidence=bundle,
                preflight_evidence=preflight,
                candidate_snapshot=snapshot,
                artifact_root=self.app,
                work_root=self.root / "blind-replays",
                require_strata_coverage=require_strata_coverage,
            )

    def test_replay_binds_and_executes_on_disposable_snapshot_copy(self) -> None:
        before = artifact_identity(self.app)
        receipt = self._replay(self._plan())
        self.assertEqual(receipt["kind"], "candidate_acceptance_replay")
        self.assertEqual(receipt["attestation_scope"], "adapter_executed_snapshot_copy")
        self.assertEqual(receipt["producer"]["role"], "acceptance_replay_adapter")
        self.assertTrue(receipt["execution_complete"])
        self.assertTrue(receipt["all_passed"])
        self.assertEqual(receipt["results"][0]["status"], "passed")
        self.assertEqual(receipt["proposal_sha256"], stable_sha256(self.proposal))
        self.assertEqual(
            receipt["acceptance_evidence_sha256"], stable_sha256(self.acceptance)
        )
        self.assertEqual(
            receipt["candidate_snapshot_sha256"], stable_sha256(self.snapshot)
        )
        self.assertEqual(artifact_identity(self.app), before)
        self.assertEqual(list((self.root / "replays").iterdir()), [])

    def test_failed_check_is_evidence_not_a_protocol_exception(self) -> None:
        receipt = self._replay(
            self._plan([sys.executable, "-c", "raise SystemExit(3)"])
        )
        self.assertTrue(receipt["execution_complete"])
        self.assertFalse(receipt["all_passed"])
        self.assertEqual(receipt["overall_status"], "failed")
        self.assertEqual(receipt["results"][0]["status"], "failed")
        self.assertEqual(receipt["results"][0]["observed_exit_code"], 3)

    def test_existing_exact_receipt_is_reused_without_reexecution(self) -> None:
        plan = self._plan()
        receipt = self._replay(plan)
        with patch(
            "integrations.harbor.experimental.candidate_acceptance_replay._run_check",
            side_effect=AssertionError("exact replay should be reused"),
        ):
            reused = self._replay(plan, existing=receipt)
        self.assertEqual(reused, receipt)

    def test_stale_candidate_and_sensitive_values_are_rejected(self) -> None:
        stale = self._plan()
        stale["candidate_artifact_identity"] = "tree-sha256:stale"
        with self.assertRaisesRegex(ValueError, "another candidate"):
            self._replay(stale)

        secret = "private-test-value-12345"
        sensitive = self._plan(
            [sys.executable, "-c", f"print({secret!r})"]
        )
        with patch.dict(os.environ, {**self.env, "EXAMPLE_AUTH_TOKEN": secret}, clear=False):
            with self.assertRaisesRegex(ValueError, "sensitive environment value"):
                replay_acceptance_checks(
                    plan=sensitive,
                    proposal=self.proposal,
                    acceptance_evidence=self.acceptance,
                    candidate_snapshot=self.snapshot,
                    artifact_root=self.app,
                    work_root=self.root / "replays",
                )

    def test_live_candidate_mutation_is_a_hard_protocol_failure(self) -> None:
        command = (
            "import pathlib; "
            f"pathlib.Path({str(self.app / 'worker.py')!r}).write_text('VALUE = 9\\n')"
        )
        with self.assertRaisesRegex(ValueError, "mutated the live candidate"):
            self._replay(self._plan([sys.executable, "-c", command]))

    def test_output_budget_is_reported_without_storing_output_content(self) -> None:
        command = f"import sys; sys.stdout.write('x' * {MAX_STREAM_BYTES + 1})"
        receipt = self._replay(self._plan([sys.executable, "-c", command]))
        result = receipt["results"][0]
        self.assertEqual(result["status"], "output_limit")
        self.assertGreater(result["stdout_bytes"], MAX_STREAM_BYTES)
        self.assertNotIn("stdout", result)

    def test_successful_group_leader_cannot_leave_a_background_child(self) -> None:
        marker = self.root / "background-child-survived"
        child = (
            "import pathlib,time; time.sleep(0.7); "
            f"pathlib.Path({str(marker)!r}).write_text('survived')"
        )
        parent = (
            "import subprocess,sys; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}])"
        )
        receipt = self._replay(self._plan([sys.executable, "-c", parent]))
        self.assertTrue(receipt["all_passed"])
        time.sleep(0.9)
        self.assertFalse(marker.exists())

    def test_candidate_blind_plan_requires_every_executable_obligation(self) -> None:
        receipt = self._blind_replay()
        self.assertTrue(receipt["all_passed"])
        self.assertEqual(
            receipt["plan"]["checks"][0]["requirement_ids"],
            ["public-boundaries", "public-signature"],
        )

        with self.assertRaisesRegex(ValueError, "does not cover candidate-blind"):
            self._blind_replay(
                mutate_plan=lambda plan: plan["checks"][0].__setitem__(
                    "requirement_ids", ["public-boundaries"]
                )
            )

    def test_candidate_blind_plan_rejects_semantic_proxy_and_stale_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-executable requirements"):
            self._blind_replay(
                mutate_plan=lambda plan: plan["checks"][0].__setitem__(
                    "requirement_ids", ["semantic-variant"]
                )
            )

    def test_candidate_blind_plan_requires_every_predeclared_stratum(self) -> None:
        receipt = self._blind_replay(require_strata_coverage=True)
        self.assertTrue(receipt["all_passed"])
        self.assertTrue(receipt["limits"]["required_strata_coverage"])
        self.assertEqual(
            receipt["plan"]["checks"][0]["covered_strata"],
            {
                "public-boundaries": ["one", "zero"],
                "public-signature": ["call-shape"],
            },
        )

        with self.assertRaisesRegex(ValueError, "does not cover candidate-blind required strata"):
            self._blind_replay(
                require_strata_coverage=True,
                mutate_plan=lambda plan: plan["checks"][0]["covered_strata"].__setitem__(
                    "public-boundaries", ["zero"]
                ),
            )

        with self.assertRaisesRegex(ValueError, "references unknown strata"):
            self._blind_replay(
                require_strata_coverage=True,
                mutate_plan=lambda plan: plan["checks"][0]["covered_strata"].__setitem__(
                    "public-signature", ["wrong-shape"]
                ),
            )
        with self.assertRaisesRegex(ValueError, "not bound to preflight evidence"):
            self._blind_replay(
                mutate_plan=lambda plan: plan.__setitem__(
                    "preflight_evidence_sha256", "0" * 64
                )
            )


if __name__ == "__main__":
    unittest.main()
