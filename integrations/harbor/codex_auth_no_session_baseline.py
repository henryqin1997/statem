from __future__ import annotations

import shlex
import shutil

from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths


class AuthNoSessionCodex(Codex):
    """Native Codex baseline with file auth and no retained raw sessions."""

    @staticmethod
    def name() -> str:
        return "codex-auth-no-session-baseline-v1"

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
            await super().run(instruction, environment, context)
        finally:
            try:
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
