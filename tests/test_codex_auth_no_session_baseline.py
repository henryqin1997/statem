from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from harbor.agents.installed.codex import Codex

from integrations.harbor.codex_auth_no_session_baseline import (
    AuthNoSessionCodex,
)


class _FakeEnvironment:
    def __init__(self, default_user=None):
        self.default_user = default_user

    @contextmanager
    def with_default_user(self, user):
        previous = self.default_user
        self.default_user = user
        try:
            yield
        finally:
            self.default_user = previous


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
        self.assertEqual(agent.name(), "codex-auth-no-session-baseline-v2")

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
            environment = _FakeEnvironment(default_user="runner")
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

    async def test_resolves_image_default_uid_for_private_auth_file(self) -> None:
        agent = object.__new__(AuthNoSessionCodex)
        agent.exec_as_agent = AsyncMock(
            return_value=SimpleNamespace(stdout="65534\n")
        )
        environment = SimpleNamespace(default_user=None)

        user = await agent._effective_agent_user(environment)

        self.assertEqual(user, 65534)
        agent.exec_as_agent.assert_awaited_once_with(
            environment,
            command="id -u",
        )

    async def test_preserves_explicit_harbor_agent_user(self) -> None:
        agent = object.__new__(AuthNoSessionCodex)
        agent.exec_as_agent = AsyncMock()
        environment = SimpleNamespace(default_user="runner")

        user = await agent._effective_agent_user(environment)

        self.assertEqual(user, "runner")
        agent.exec_as_agent.assert_not_awaited()

    async def test_run_temporarily_binds_image_default_uid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = AuthNoSessionCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
            agent.exec_as_agent = AsyncMock(
                return_value=SimpleNamespace(stdout="65534\n")
            )
            environment = _FakeEnvironment(default_user=None)
            context = SimpleNamespace()
            observed_users = []

            async def native_run(_agent, instruction, active_environment, _context):
                self.assertEqual(instruction, "unchanged benchmark instruction")
                observed_users.append(active_environment.default_user)

            with (
                patch.object(Codex, "run", new=native_run),
                patch.object(Codex, "populate_context_post_run"),
            ):
                await agent.run("unchanged benchmark instruction", environment, context)

        self.assertEqual(observed_users, [65534])
        self.assertIsNone(environment.default_user)


if __name__ == "__main__":
    unittest.main()
