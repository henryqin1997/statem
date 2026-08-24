from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths


async def sync_remote_codex_sessions_for_atif(
    environment: BaseEnvironment,
    logs_dir: Path,
) -> bool:
    """Download cloud session logs only long enough to produce public ATIF."""

    sessions_dir = logs_dir / "sessions"
    if sessions_dir.is_dir() and any(sessions_dir.rglob("*.jsonl")):
        return False

    remote_sessions = (EnvironmentPaths.agent_dir / "sessions").as_posix()
    try:
        if not await environment.is_dir(remote_sessions):
            return False
        sessions_dir.mkdir(parents=True, exist_ok=True)
        await environment.download_dir(remote_sessions, sessions_dir)
    except Exception:
        shutil.rmtree(sessions_dir, ignore_errors=True)
        return False
    return sessions_dir.is_dir() and any(sessions_dir.rglob("*.jsonl"))


class AuthNoSessionCodex(Codex):
    """Native Codex baseline with file auth and no retained raw sessions."""

    @staticmethod
    def name() -> str:
        return "codex-auth-no-session-baseline-v2"

    async def _effective_agent_user(
        self,
        environment: BaseEnvironment,
    ) -> str | int:
        if environment.default_user is not None:
            return environment.default_user
        result = await self.exec_as_agent(environment, command="id -u")
        user = (result.stdout or "").strip()
        if not user.isdigit():
            raise RuntimeError(f"could not resolve container agent uid: {user!r}")
        return int(user)

    def build_cli_flags(self) -> str:
        flags = super().build_cli_flags()
        if self._get_env("CODEX_AUTH_JSON_PATH"):
            flags = f"{flags} -c cli_auth_credentials_store=file".strip()
        return flags

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        try:
            if environment.default_user is None:
                effective_user = await self._effective_agent_user(environment)
                with environment.with_default_user(effective_user):
                    await super().run(instruction, environment, context)
            else:
                await super().run(instruction, environment, context)
        finally:
            try:
                await sync_remote_codex_sessions_for_atif(
                    environment, self.logs_dir
                )
                Codex.populate_context_post_run(self, context)
            finally:
                await self.exec_as_agent(
                    environment,
                    command=(
                        "rm -rf "
                        + shlex.quote(
                            (EnvironmentPaths.agent_dir / "sessions").as_posix()
                        )
                    ),
                )
                shutil.rmtree(self.logs_dir / "sessions", ignore_errors=True)
