from __future__ import annotations

from typing import Any

from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from integrations.harbor.codex_auth_no_session_baseline import (
    sync_remote_codex_sessions_for_atif,
)
from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    select_thin_family_practice,
)
from integrations.harbor.statem_codex_thin_family_v4p69_exp import (
    ThinFamilyV4p69ExperimentalStatemCodex,
)


class ThinFamilyV4p70ExperimentalStatemCodex(
    ThinFamilyV4p69ExperimentalStatemCodex
):
    """Route unmatched or unadmitted tasks through native direct solve."""

    def __init__(self, *args: Any, **kwargs: Any):
        self._direct_bypass_active = False
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin-family-v4p70-exp"

    def build_cli_flags(self) -> str:
        if not self._direct_bypass_active:
            return super().build_cli_flags()
        flags = Codex.build_cli_flags(self)
        if self._get_env("CODEX_AUTH_JSON_PATH"):
            flags = f"{flags} -c cli_auth_credentials_store=file".strip()
        return flags

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        self._thin_family_selection = select_thin_family_practice(
            instruction,
            self._practice_catalog_path,
            activation_mode=self._activation_mode,
        )
        if self._thin_family_selection.get("activated"):
            await super().run(instruction, environment, context)
            return
        await self._run_native_direct(instruction, environment, context)

    async def _run_native_direct(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        self._direct_bypass_active = True
        if self._source_manifest is None:
            self._source_manifest = self._build_source_manifest()
        try:
            if environment.default_user is None:
                effective_user = await self._effective_agent_user(environment)
                with environment.with_default_user(effective_user):
                    await Codex.run(self, instruction, environment, context)
            else:
                await Codex.run(self, instruction, environment, context)
        finally:
            try:
                await sync_remote_codex_sessions_for_atif(
                    environment, self.logs_dir
                )
                Codex.populate_context_post_run(self, context)
            finally:
                await self._remove_codex_session_logs(environment)
                self._record_direct_route_metadata(context)
                self._direct_bypass_active = False

    def _record_direct_route_metadata(self, context: AgentContext) -> None:
        context.metadata = dict(context.metadata or {})
        statem_metadata = dict(context.metadata.get("statem") or {})
        statem_metadata.update(
            {
                "agent": self.name(),
                "execution_mode": "native_direct_bypass",
                "thin_family_selection": self._thin_family_selection,
            }
        )
        if self._source_manifest is not None:
            statem_metadata["source_manifest_sha256"] = (
                self._source_manifest.get("manifest_sha256")
            )
            statem_metadata["source_manifest_file_count"] = (
                self._source_manifest.get("file_count")
            )
        context.metadata["statem"] = statem_metadata
