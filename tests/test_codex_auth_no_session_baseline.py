from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from harbor.agents.installed.codex import Codex

from integrations.harbor.codex_auth_no_session_baseline import (
    AuthNoSessionCodex,
)


class AuthNoSessionCodexTest(unittest.IsolatedAsyncioTestCase):
    def test_identity_and_file_auth_flag_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = AuthNoSessionCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
            with patch.dict(
                os.environ,
                {"CODEX_AUTH_JSON_PATH": "/tmp/test-auth.json"},
                clear=False,
            ):
                self.assertIn(
                    "cli_auth_credentials_store=file",
                    agent.build_cli_flags(),
                )
        self.assertEqual(agent.name(), "codex-auth-no-session-baseline-v1")

    async def test_run_keeps_native_instruction_and_removes_raw_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir)
            sessions = logs_dir / "sessions"
            sessions.mkdir()
            (sessions / "raw.jsonl").write_text("opaque", encoding="utf-8")
            agent = AuthNoSessionCodex(
                logs_dir=logs_dir,
                model_name="gpt-5.6-sol",
            )
            agent.exec_as_agent = AsyncMock()
            environment = SimpleNamespace()
            context = SimpleNamespace()

            with (
                patch.object(Codex, "run", new=AsyncMock()) as native_run,
                patch.object(Codex, "populate_context_post_run") as populate,
            ):
                await agent.run("unchanged benchmark instruction", environment, context)

            native_run.assert_awaited_once_with(
                "unchanged benchmark instruction",
                environment,
                context,
            )
            populate.assert_called_once_with(agent, context)
            self.assertFalse(sessions.exists())
            cleanup = agent.exec_as_agent.await_args.kwargs["command"]
            self.assertIn("sessions", cleanup)


if __name__ == "__main__":
    unittest.main()
