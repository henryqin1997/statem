from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from integrations.harbor.experimental.tb3_public_artifact_gate import (
    evaluate_artifacts,
    main,
)


class PublicArtifactGateTests(unittest.TestCase):
    def test_complete_declared_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("output.csv", "stats.tsv", "leading.txt"):
                (root / name).write_text("value\n", encoding="utf-8")
            declarations = {
                "task": "example",
                "artifacts": [
                    "/results/output.csv",
                    "/results/stats.tsv",
                    "/results/leading.txt",
                ],
            }
            manifest = [
                {
                    "source": f"/results/{name}",
                    "destination": name,
                    "type": "file",
                    "status": "ok",
                }
                for name in ("output.csv", "stats.tsv", "leading.txt")
            ]

            receipt = evaluate_artifacts(
                declarations=declarations,
                manifest=manifest,
                artifact_root=root,
            )

            self.assertTrue(receipt["complete"])
            self.assertEqual(receipt["matched_count"], 3)
            self.assertEqual(receipt["extra_sources"], [])
            self.assertNotIn("artifact_root", receipt)
            self.assertEqual(len(receipt["observed_destinations"]), 3)
            self.assertTrue(
                all(item["size_bytes"] > 0 for item in receipt["observed_destinations"])
            )

    def test_failed_declared_export_is_blocking_but_extra_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "memo.json").write_text("{}\n", encoding="utf-8")
            declarations = {
                "task": "intrastat-example",
                "artifacts": [
                    "/workspace/memo.json",
                    {"service": "api", "source": "/var/lib/runtime"},
                ],
            }
            manifest = [
                {
                    "source": "/workspace/memo.json",
                    "destination": "memo.json",
                    "type": "file",
                    "status": "ok",
                },
                {
                    "source": "/var/lib/runtime",
                    "destination": "runtime",
                    "type": "file",
                    "status": "failed",
                },
                {
                    "source": "/logs/artifacts",
                    "destination": "logs",
                    "type": "directory",
                    "status": "empty",
                },
            ]

            receipt = evaluate_artifacts(
                declarations=declarations,
                manifest=manifest,
                artifact_root=root,
            )

            self.assertFalse(receipt["complete"])
            self.assertEqual(
                receipt["failed_sources"],
                [{"source": "/var/lib/runtime", "status": "failed"}],
            )
            self.assertEqual(receipt["extra_sources"], ["/logs/artifacts"])

    def test_missing_duplicate_empty_and_unsafe_destinations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "empty.txt").touch()
            declarations = {
                "task": "example",
                "artifacts": ["/missing", "/duplicate", "/empty", "/unsafe"],
            }
            manifest = [
                {
                    "source": "/duplicate",
                    "destination": "one",
                    "type": "file",
                    "status": "ok",
                },
                {
                    "source": "/duplicate",
                    "destination": "two",
                    "type": "file",
                    "status": "ok",
                },
                {
                    "source": "/empty",
                    "destination": "empty.txt",
                    "type": "file",
                    "status": "ok",
                },
                {
                    "source": "/unsafe",
                    "destination": "../escape",
                    "type": "file",
                    "status": "ok",
                },
            ]

            receipt = evaluate_artifacts(
                declarations=declarations,
                manifest=manifest,
                artifact_root=root,
            )

            self.assertFalse(receipt["complete"])
            self.assertEqual(receipt["missing_sources"], ["/missing"])
            self.assertEqual(receipt["duplicate_sources"], ["/duplicate"])
            self.assertEqual(receipt["empty_destinations"], ["empty.txt"])
            self.assertEqual(receipt["unsafe_destinations"], ["../escape"])

    def test_cli_require_complete_returns_two_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            declarations = root / "declarations.json"
            manifest = root / "manifest.json"
            output = root / "receipt.json"
            declarations.write_text(
                json.dumps({"task": "example", "artifacts": ["/missing"]}),
                encoding="utf-8",
            )
            manifest.write_text("[]", encoding="utf-8")

            exit_code = main(
                [
                    "--declarations",
                    str(declarations),
                    "--manifest",
                    str(manifest),
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                    "--require-complete",
                ]
            )

            self.assertEqual(exit_code, 2)
            self.assertFalse(json.loads(output.read_text())["complete"])


if __name__ == "__main__":
    unittest.main()
