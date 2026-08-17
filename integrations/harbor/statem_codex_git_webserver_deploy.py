from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths


FAMILY_METADATA = {
    "name": "git_webserver_deploy",
    "policy_surface": "single_family",
    "selection_basis": "task_visible_contract",
}


class GitWebserverDeployFamilyStatemCodex(Codex):
    """Self-contained Harbor adapter for one executable StateM task family."""

    _PINNED_CODEX_VERSION = "0.146.0"
    _REMOTE_STATEM_SRC = PurePosixPath("/tmp/statem-src")
    _REMOTE_RUNBOOK_DIR = PurePosixPath("/tmp/statem-runbooks")
    _REMOTE_STATE_DIR = PurePosixPath("/tmp/statem-state")
    _REMOTE_CHECKS = PurePosixPath("/tmp/statem-verification-checks")
    _REMOTE_RUNBOOK = _REMOTE_RUNBOOK_DIR / "git-webserver-family.yaml"
    _REMOTE_HELPER = _REMOTE_CHECKS / "git_webserver_deploy_family.py"
    _REMOTE_STOP_HOOK = _REMOTE_CHECKS / "statem_stop_hook.py"
    _REMOTE_ADAPTER = _REMOTE_CHECKS / "git-webserver-family-adapter.py"
    _PUBLIC_STATEM_FILES = (
        "__init__.py",
        "__main__.py",
        "cli.py",
        "core.py",
        "miniyaml.py",
    )

    def __init__(
        self,
        *args: Any,
        statem_source_dir: str | None = None,
        runbook_path: str | None = None,
        run_id_prefix: str = "tb21-git-webserver-deploy",
        final_state: str = "handoff",
        enforce_final_state: bool = True,
        agent_deadline_seconds: int = 900,
        handoff_buffer_seconds: int = 120,
        heavy_work_buffer_seconds: int = 240,
        **kwargs: Any,
    ) -> None:
        requested_version = kwargs.get("version")
        if requested_version not in (None, self._PINNED_CODEX_VERSION):
            raise ValueError(
                "git_webserver_deploy family reproduction requires Codex "
                f"{self._PINNED_CODEX_VERSION}, got {requested_version}"
            )
        kwargs["version"] = self._PINNED_CODEX_VERSION
        super().__init__(*args, **kwargs)
        repo_root = Path(__file__).resolve().parents[2]
        self._statem_source_dir = (
            Path(statem_source_dir).expanduser().resolve()
            if statem_source_dir
            else repo_root
        )
        self._runbook_path = (
            Path(runbook_path).expanduser().resolve()
            if runbook_path
            else repo_root
            / "examples"
            / "terminal-bench-2.1-git-webserver-deploy-family.yaml"
        )
        self._helper_path = (
            repo_root
            / "integrations"
            / "harbor"
            / "experimental"
            / "git_webserver_deploy_family.py"
        )
        self._stop_hook_path = (
            repo_root / "integrations" / "hooks" / "statem_stop_hook.py"
        )
        self._adapter_path = Path(__file__).resolve()
        self._run_id_prefix = run_id_prefix
        self._final_state = final_state
        self._enforce_final_state = bool(enforce_final_state)
        self._agent_deadline_seconds = max(1, int(agent_deadline_seconds))
        self._handoff_buffer_seconds = max(1, int(handoff_buffer_seconds))
        self._heavy_work_buffer_seconds = max(1, int(heavy_work_buffer_seconds))
        self._source_manifest: dict[str, Any] | None = None

    @staticmethod
    def name() -> str:
        return "statem-codex-git-webserver-deploy-family"

    def build_cli_flags(self) -> str:
        flags = super().build_cli_flags()
        if self._get_env("CODEX_AUTH_JSON_PATH"):
            flags = f"{flags} -c cli_auth_credentials_store=file".strip()
        return f"{flags} --dangerously-bypass-hook-trust".strip()

    async def setup(self, environment: BaseEnvironment) -> None:
        await super().setup(environment)
        await self._install_family_runtime(environment)

    async def _install_family_runtime(self, environment: BaseEnvironment) -> None:
        required = [
            self._runbook_path,
            self._helper_path,
            self._stop_hook_path,
            self._adapter_path,
            *[
                self._statem_source_dir / "statem" / name
                for name in self._PUBLIC_STATEM_FILES
            ],
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "single-family publication is missing required files: "
                + ", ".join(missing)
            )

        await self.exec_as_root(
            environment,
            command=(
                "if command -v python3 >/dev/null 2>&1; then python3 --version; "
                "elif [ -f /etc/alpine-release ]; then apk add --no-cache python3; "
                "elif command -v apt-get >/dev/null 2>&1; then "
                "DEBIAN_FRONTEND=noninteractive apt-get update && "
                "DEBIAN_FRONTEND=noninteractive apt-get install -y python3; "
                "else echo 'python3 is required for statem' >&2; exit 1; fi"
            ),
        )
        await self.exec_as_root(
            environment,
            command=(
                f"rm -rf {shlex.quote(self._REMOTE_STATEM_SRC.as_posix())} "
                f"{shlex.quote(self._REMOTE_RUNBOOK_DIR.as_posix())} "
                f"{shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                f"{shlex.quote(self._REMOTE_CHECKS.as_posix())} && "
                f"mkdir -p {shlex.quote((self._REMOTE_STATEM_SRC / 'statem').as_posix())} "
                f"{shlex.quote(self._REMOTE_RUNBOOK_DIR.as_posix())} "
                f"{shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                f"{shlex.quote(self._REMOTE_CHECKS.as_posix())} && "
                f"chmod -R 777 {shlex.quote(self._REMOTE_STATEM_SRC.as_posix())} "
                f"{shlex.quote(self._REMOTE_RUNBOOK_DIR.as_posix())} "
                f"{shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                f"{shlex.quote(self._REMOTE_CHECKS.as_posix())}"
            ),
        )

        for name in self._PUBLIC_STATEM_FILES:
            await environment.upload_file(
                self._statem_source_dir / "statem" / name,
                (self._REMOTE_STATEM_SRC / "statem" / name).as_posix(),
            )
        for local_path, remote_path in (
            (self._runbook_path, self._REMOTE_RUNBOOK),
            (self._helper_path, self._REMOTE_HELPER),
            (self._stop_hook_path, self._REMOTE_STOP_HOOK),
            (self._adapter_path, self._REMOTE_ADAPTER),
        ):
            await environment.upload_file(local_path, remote_path.as_posix())

        manifest = self._build_source_manifest()
        self._source_manifest = manifest
        await self._write_remote_text(
            environment,
            (self._REMOTE_CHECKS / "source-manifest.json").as_posix(),
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        await self.exec_as_root(
            environment,
            command=(
                "cat >/usr/local/bin/statem <<'SH'\n"
                "#!/bin/sh\n"
                f"PYTHONPATH={shlex.quote(self._REMOTE_STATEM_SRC.as_posix())} "
                "exec python3 -m statem.cli \"$@\"\n"
                "SH\n"
                "chmod +x /usr/local/bin/statem\n"
                f"statem validate {shlex.quote(self._REMOTE_RUNBOOK.as_posix())} "
                "--json >/tmp/statem-family-validate.json"
            ),
        )

    def _build_source_manifest(self) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for name in self._PUBLIC_STATEM_FILES:
            local = self._statem_source_dir / "statem" / name
            entries.append(
                self._manifest_entry(
                    "statem",
                    local,
                    self._REMOTE_STATEM_SRC / "statem" / name,
                )
            )
        entries.extend(
            [
                self._manifest_entry("runbook", self._runbook_path, self._REMOTE_RUNBOOK),
                self._manifest_entry("family_helper", self._helper_path, self._REMOTE_HELPER),
                self._manifest_entry("stop_hook", self._stop_hook_path, self._REMOTE_STOP_HOOK),
                self._manifest_entry("family_adapter", self._adapter_path, self._REMOTE_ADAPTER),
            ]
        )
        payload: dict[str, Any] = {
            "version": 1,
            "agent": self.name(),
            "family": FAMILY_METADATA,
            "runbook": self._local_relative(self._runbook_path),
            "file_count": len(entries),
            "files": entries,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
        return payload

    def _manifest_entry(
        self,
        group: str,
        path: Path,
        remote_path: PurePosixPath,
    ) -> dict[str, Any]:
        return {
            "group": group,
            "local_relative_path": self._local_relative(path),
            "remote_path": remote_path.as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def _local_relative(self, path: Path) -> str:
        try:
            return path.relative_to(self._statem_source_dir).as_posix()
        except ValueError:
            return path.name

    async def _write_remote_text(
        self,
        environment: BaseEnvironment,
        remote_path: str,
        text: str,
    ) -> None:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        await self.exec_as_root(
            environment,
            command=(
                "python3 -c "
                + shlex.quote(
                    "import base64, pathlib; "
                    f"pathlib.Path({remote_path!r}).write_bytes(base64.b64decode({encoded!r}))"
                )
            ),
        )

    def _run_id(self, environment: BaseEnvironment) -> str:
        raw = f"{self._run_id_prefix}-{environment.session_id}"
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-") or self._run_id_prefix

    def _statem_env(self, run_id: str) -> dict[str, str]:
        return {
            "STATEM_STATE_DIR": self._REMOTE_STATE_DIR.as_posix(),
            "STATEM_AGENT_ID": self.name(),
            "STATEM_AGENT_ROLE": "benchmark-agent",
            "STATEM_RUN_ID": run_id,
            "STATEM_DEADLINE_FILE": (self._REMOTE_CHECKS / "deadline.json").as_posix(),
        }

    async def _write_task_and_deadline(
        self,
        environment: BaseEnvironment,
        run_id: str,
        instruction: str,
    ) -> None:
        await self._write_remote_text(
            environment,
            (self._REMOTE_CHECKS / "task.txt").as_posix(),
            instruction,
        )
        started = time.time()
        deadline = {
            "version": 1,
            "source": "git_webserver_deploy_family_adapter",
            "run_id": run_id,
            "started_at_epoch": started,
            "deadline_at_epoch": started + self._agent_deadline_seconds,
            "agent_deadline_seconds": self._agent_deadline_seconds,
            "handoff_buffer_seconds": self._handoff_buffer_seconds,
            "heavy_work_buffer_seconds": self._heavy_work_buffer_seconds,
        }
        await self._write_remote_text(
            environment,
            (self._REMOTE_CHECKS / "deadline.json").as_posix(),
            json.dumps(deadline, indent=2, sort_keys=True) + "\n",
        )

    async def _start_statem(self, environment: BaseEnvironment, run_id: str) -> None:
        result = await self.exec_as_agent(
            environment,
            command=(
                f"statem start {shlex.quote(self._REMOTE_RUNBOOK.as_posix())} "
                f"--state-dir {shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                f"--run-id {shlex.quote(run_id)} "
                f"--agent-id {shlex.quote(self.name())} "
                "--agent-role benchmark-agent"
            ),
            env=self._statem_env(run_id),
        )
        return_code = getattr(
            result,
            "return_code",
            getattr(result, "returncode", 0),
        )
        if return_code not in (None, 0):
            raise RuntimeError(f"could not start StateM family run: {result.stderr}")

    async def _current_context(self, environment: BaseEnvironment, run_id: str) -> str:
        result = await self.exec_as_agent(
            environment,
            command=(
                "statem cur "
                f"--state-dir {shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                f"--run-id {shlex.quote(run_id)} --json"
            ),
            env=self._statem_env(run_id),
        )
        return (result.stdout or "").strip()

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        state_dir = self._REMOTE_STATE_DIR.as_posix()
        return f"""You are {self.name()}, a Codex agent using one executable StateM task-family runbook.

Required StateM protocol:
- Inspect the current state before substantive work with:
  `statem cur --state-dir {state_dir} --run-id {run_id}`
- Follow the current state's prompt and hooks. Inspect the graph with:
  `statem state --state-dir {state_dir} --run-id {run_id}`
- Move only through explicit transitions with `statem goto TARGET --state-dir {state_dir} --run-id {run_id}`.
- Use `--yes` only after satisfying a transition's checklist and machine checks.
- If a transition fails, remain in the current state, repair the recorded issue, and retry it.
- Keep progress.md current with the visible contract, candidate identity, checks, and residual risk.
- The graph is `direct_solve -> task_contract_check -> self_review`, followed by a selected
  `family_evidence_check`, targeted `repair`, ordinary non-match `handoff`, or explicit
  `deadline_handoff`. There is no broad catalog or unrelated family route.
- Solve normally before self_review. Only the immutable task-visible selector may expose the
  git_webserver_deploy reviewer practice. A selected task normally requires the fixed stateful
  gate receipt before handoff; do not replace it with proxy evidence or rerun it at final handoff.
- Do not inspect benchmark answers, hidden tests, verifier internals, credentials, or unrelated files.

Current StateM state:
{current_context}

Benchmark task:
{instruction}
"""

    def _codex_stop_hook_payload(self) -> dict[str, Any]:
        command = (
            f"STATEM_STATE_DIR={shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
            "STATEM_COMMAND=statem STATEM_HOST=codex "
            f"python3 {shlex.quote(self._REMOTE_STOP_HOOK.as_posix())}"
        )
        return {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": command,
                                "timeout": 15,
                                "statusMessage": "Checking active StateM run",
                            }
                        ]
                    }
                ]
            }
        }

    async def _install_codex_stop_hook(self, environment: BaseEnvironment) -> None:
        await self.exec_as_agent(
            environment,
            command=f"mkdir -p {shlex.quote(self._REMOTE_CODEX_HOME.as_posix())}",
            env={"CODEX_HOME": self._REMOTE_CODEX_HOME.as_posix()},
        )
        await self._write_remote_text(
            environment,
            (self._REMOTE_CODEX_HOME / "hooks.json").as_posix(),
            json.dumps(self._codex_stop_hook_payload(), indent=2, sort_keys=True) + "\n",
        )

    async def _effective_agent_user(self, environment: BaseEnvironment) -> str | int:
        if environment.default_user is not None:
            return environment.default_user
        result = await self.exec_as_agent(environment, command="id -u")
        user = (result.stdout or "").strip()
        if not user.isdigit():
            raise RuntimeError(f"could not resolve container agent uid: {user!r}")
        return int(user)

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        run_id = self._run_id(environment)
        await self._write_task_and_deadline(environment, run_id, instruction)
        await self._start_statem(environment, run_id)
        current_context = await self._current_context(environment, run_id)
        augmented = self._augment_instruction(instruction, run_id, current_context)
        await self._install_codex_stop_hook(environment)
        try:
            if environment.default_user is None:
                effective_user = await self._effective_agent_user(environment)
                with environment.with_default_user(effective_user):
                    await super().run(augmented, environment, context)
            else:
                await super().run(augmented, environment, context)
        finally:
            try:
                Codex.populate_context_post_run(self, context)
            finally:
                await self._remove_session_logs(environment)
                await self._collect_family_artifacts(environment, context, run_id)

    async def _remove_session_logs(self, environment: BaseEnvironment) -> None:
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    f"rm -rf {shlex.quote((EnvironmentPaths.agent_dir / 'sessions').as_posix())}"
                ),
            )
        except Exception:
            return

    async def _collect_family_artifacts(
        self,
        environment: BaseEnvironment,
        context: AgentContext,
        run_id: str,
    ) -> None:
        current: dict[str, Any] | None = None
        try:
            current_raw = await self._current_context(environment, run_id)
            current = json.loads(current_raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            current = None
        agent_statem = (EnvironmentPaths.agent_dir / "statem").as_posix()
        copy_names = (
            "git-webserver-selection.json",
            "task-contract-receipt.json",
            "self-review.json",
            "git-webserver-receipt.json",
            "task.txt",
            "deadline.json",
            "source-manifest.json",
        )
        commands = [f"mkdir -p {shlex.quote(agent_statem)}"]
        commands.extend(
            f"cp {shlex.quote((self._REMOTE_CHECKS / name).as_posix())} "
            f"{shlex.quote(f'{agent_statem}/{name}')} || true"
            for name in copy_names
        )
        commands.extend(
            [
                f"statem cur --state-dir {shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                f"--run-id {shlex.quote(run_id)} --json >"
                f"{shlex.quote(f'{agent_statem}/current.json')} || true",
                f"statem history --state-dir {shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                f"--run-id {shlex.quote(run_id)} --limit 100 --json >"
                f"{shlex.quote(f'{agent_statem}/history.json')} || true",
                f"cp -R {shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                f"{shlex.quote(f'{agent_statem}/state')} || true",
            ]
        )
        await self.exec_as_agent(
            environment,
            command="\n".join(commands),
            env=self._statem_env(run_id),
        )
        context.metadata = dict(context.metadata or {})
        context.metadata["statem"] = {
            "run_id": run_id,
            "agent": self.name(),
            "family": FAMILY_METADATA,
            "current": current.get("current") if current else None,
            "current_entry_id": current.get("current_entry_id") if current else None,
            "source_manifest_sha256": (
                self._source_manifest.get("manifest_sha256")
                if self._source_manifest
                else None
            ),
            "family_artifacts": list(copy_names),
        }
        if self._enforce_final_state and (
            not current or current.get("current") != self._final_state
        ):
            raise RuntimeError(
                f"statem final state is {(current or {}).get('current')!r}, "
                f"expected {self._final_state!r}"
            )


class DeepSeekGitWebserverDeployFamilyStatemCodex(
    GitWebserverDeployFamilyStatemCodex
):
    """Self-contained family adapter with DeepSeek's official Codex config."""

    _EXPECTED_MODEL = "deepseek-v4-flash"

    def __init__(
        self,
        *args: Any,
        deepseek_config_home: str | None = None,
        **kwargs: Any,
    ) -> None:
        config_home = deepseek_config_home or os.environ.get(
            "DEEPSEEK_CODEX_CONFIG_HOME", ""
        )
        if not config_home:
            raise ValueError(
                "deepseek_config_home or DEEPSEEK_CODEX_CONFIG_HOME is required"
            )
        self._deepseek_config_home = Path(config_home).expanduser().resolve()
        self._deepseek_config = self._deepseek_config_home / "config.toml"
        self._deepseek_models = self._deepseek_config_home / "models.json"
        self._validate_deepseek_config()
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return "statem-deepseek-git-webserver-deploy-family"

    def _validate_deepseek_config(self) -> None:
        if not self._deepseek_config.is_file() or not self._deepseek_models.is_file():
            raise FileNotFoundError(
                "DeepSeek Codex config home must contain config.toml and models.json"
            )
        models = json.loads(self._deepseek_models.read_text(encoding="utf-8"))
        slugs = {
            str(item.get("slug"))
            for item in models.get("models", [])
            if isinstance(item, dict)
        }
        if self._EXPECTED_MODEL not in slugs:
            raise ValueError(f"DeepSeek model catalog is missing {self._EXPECTED_MODEL}")
        config_text = self._deepseek_config.read_text(encoding="utf-8")
        required_fragments = (
            'model_provider = "deepseek"',
            'base_url = "https://api.deepseek.com/"',
            'wire_api = "responses"',
            "experimental_bearer_token",
        )
        if any(fragment not in config_text for fragment in required_fragments):
            raise ValueError("DeepSeek config.toml is not an official provider config")

    @classmethod
    def _container_config_text(cls, source: str) -> str:
        catalog_path = cls._REMOTE_CODEX_HOME / "models.json"
        replacement = f'model_catalog_json = "{catalog_path}"'
        rendered, count = re.subn(
            r"(?m)^\s*model_catalog_json\s*=\s*[^\n]+$",
            replacement,
            source,
            count=1,
        )
        if count != 1:
            raise ValueError("DeepSeek config.toml must contain one model_catalog_json")
        return rendered

    async def _stage_deepseek_config(self, environment: BaseEnvironment) -> None:
        remote_home = self._REMOTE_CODEX_HOME.as_posix()
        await self.exec_as_agent(
            environment,
            command=f"mkdir -p {shlex.quote(remote_home)} && chmod 700 {shlex.quote(remote_home)}",
        )
        rendered = self._container_config_text(
            self._deepseek_config.read_text(encoding="utf-8")
        )
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="statem-deepseek-family-",
                suffix=".toml",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                handle.write(rendered)
            os.chmod(temporary_name, 0o600)
            await environment.upload_file(
                Path(temporary_name),
                (self._REMOTE_CODEX_HOME / "config.toml").as_posix(),
            )
            await environment.upload_file(
                self._deepseek_models,
                (self._REMOTE_CODEX_HOME / "models.json").as_posix(),
            )
            if environment.default_user is not None:
                await self.exec_as_root(
                    environment,
                    command=(
                        f"chown {environment.default_user} "
                        f"{remote_home}/config.toml {remote_home}/models.json && "
                        f"chmod 600 {remote_home}/config.toml {remote_home}/models.json"
                    ),
                )
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        await self._stage_deepseek_config(environment)
        await super().run(instruction, environment, context)
