from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import time
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from harbor.agents.installed.base import CliFlag
from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths

from integrations.harbor.codex_auth_no_session_baseline import (
    sync_remote_codex_sessions_for_atif,
)


_SOURCE_EXCLUDED_DIRS = {"__pycache__", ".statem"}
_SOURCE_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
_SOURCE_EXCLUDED_PATHS = {"tests/test_harbor_verification_checks.py"}


def _should_upload_source_file(path: Path) -> bool:
    normalized = path.as_posix()
    return not (
        any(part in _SOURCE_EXCLUDED_DIRS for part in path.parts)
        or path.suffix in _SOURCE_EXCLUDED_SUFFIXES
        or normalized in _SOURCE_EXCLUDED_PATHS
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _instruction_uses_teamrun_runbook(instruction: str) -> bool:
    """Route only bounded-search task families to the TeamRun runbook.

    This deliberately uses visible task semantics rather than task ids. The
    default runbook should remain thin for tasks the model can solve directly.
    """
    enabled = str(os.environ.get("STATEM_ENABLE_TEAMRUN_VIDEO") or "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False
    lower = instruction.lower()
    video_or_ocr = bool(
        re.search(r"\b(?:video|mp4|screen recording|recording|frame(?:s)?|timestamp|motion event)\b", lower)
        and re.search(
            r"\b(?:extract|detect|analy[sz]e|write|output|transcribe|ocr|event|frame|frame_number|move|"
            r"timestamp|command|text|jump|takeoff|take-off|landing)\b",
            lower,
        )
    )
    return video_or_ocr


def _instruction_needs_extended_mature_gate_deadline(instruction: str) -> bool:
    """Give narrow mature-gate families enough time to materialize evidence.

    The match is intentionally based on task-visible semantics, not task ids.
    These families tended to fail when the global internal deadline shortened
    before an already-identified mature gate could run.
    """
    lower = instruction.lower()
    html_sanitizer = (
        "html" in lower
        and any(term in lower for term in ("xss", "javascript", "script", "sanitize", "sanitization", "filter"))
        and any(term in lower for term in ("preserve", "legitimate", "structure", "content", "benign", "safe"))
    )
    protein_assembly = (
        any(term in lower for term in ("protein", "gblock", "fusion", "codon", "amino acid"))
        and any(term in lower for term in ("sequence", "assembly", "gc content", "optimization", "optimize", "constraint"))
    )
    return html_sanitizer or protein_assembly


class StatemCodex(Codex):
    """Codex benchmark adapter with statem runbook control.

    This intentionally reuses Harbor's built-in Codex implementation and wraps
    the instruction with a statem run initialized inside each benchmark sandbox.
    It is a runbook layer, not a hard workflow harness.
    """

    _REMOTE_STATEM_SRC = PurePosixPath("/tmp/statem-src")
    _REMOTE_RUNBOOK_DIR = PurePosixPath("/tmp/statem-runbooks")
    _REMOTE_STATE_DIR = PurePosixPath("/tmp/statem-state")
    _REMOTE_VERIFICATION_CHECKS = PurePosixPath("/tmp/statem-verification-checks")
    _REMOTE_TEAMRUN_DIR = PurePosixPath("/tmp/statem-teamrun")
    _REMOTE_RUNBOOK = _REMOTE_RUNBOOK_DIR / "coding-agent.yaml"
    _REMOTE_TEAMRUN_RUNBOOK = _REMOTE_RUNBOOK_DIR / "teamrun-agent.yaml"
    _REMOTE_STOP_HOOK = _REMOTE_VERIFICATION_CHECKS / "statem_stop_hook.py"

    def __init__(
        self,
        *args: Any,
        statem_source_dir: str | None = None,
        runbook_path: str | None = None,
        run_id_prefix: str = "tb21",
        final_state: str = "handoff",
        enforce_final_state: bool = False,
        bootstrap_auto_route: bool = False,
        bootstrap_risk_probe: bool = False,
        bootstrap_direct_solve: bool = False,
        include_full_current: bool = False,
        agent_deadline_seconds: int | None = None,
        handoff_buffer_seconds: int | None = None,
        heavy_work_buffer_seconds: int | None = None,
        max_session_resumes: int = 0,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        repo_root = Path(__file__).resolve().parents[2]
        self._statem_source_dir = Path(statem_source_dir).resolve() if statem_source_dir else repo_root
        self._runbook_path = (
            Path(runbook_path).resolve()
            if runbook_path
            else repo_root / "examples" / "terminal-bench-agent-thin-review.yaml"
        )
        self._run_id_prefix = run_id_prefix
        self._final_state = final_state
        self._enforce_final_state = bool(enforce_final_state)
        self._bootstrap_auto_route = bool(bootstrap_auto_route) and not bootstrap_risk_probe and not bootstrap_direct_solve
        self._bootstrap_risk_probe = bool(bootstrap_risk_probe)
        self._bootstrap_direct_solve = bool(bootstrap_direct_solve) and not self._bootstrap_risk_probe
        self._include_full_current = bool(include_full_current)
        self._agent_deadline_seconds = agent_deadline_seconds or _env_int("STATEM_AGENT_DEADLINE_SECONDS", 750)
        self._handoff_buffer_seconds = handoff_buffer_seconds or _env_int("STATEM_HANDOFF_BUFFER_SECONDS", 120)
        self._heavy_work_buffer_seconds = heavy_work_buffer_seconds or _env_int("STATEM_HEAVY_WORK_BUFFER_SECONDS", 240)
        if not 0 <= max_session_resumes <= 12:
            raise ValueError("max_session_resumes must be between 0 and 12")
        self._max_session_resumes = int(max_session_resumes)
        self._session_resume_attempts = 0
        self._session_resume_trace: list[dict[str, Any]] = []
        self._source_manifest: dict[str, Any] | None = None

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex"

    def build_cli_flags(self) -> str:
        flags = super().build_cli_flags()
        if self._get_env("CODEX_AUTH_JSON_PATH"):
            flags = f"{flags} -c cli_auth_credentials_store=file".strip()
        # The adapter installs this exact audited hook into an isolated
        # CODEX_HOME. Non-interactive runs cannot approve its hash in the TUI.
        return f"{flags} --dangerously-bypass-hook-trust".strip()

    def _session_resume_prompt(self, current: dict[str, Any]) -> str:
        state = str(current.get("current") or "unknown")
        entry_id = str(current.get("current_entry_id") or "unknown")
        return (
            "Resume the existing benchmark task in this same session and context. "
            f"The prior turn ended while StateM was in nonterminal state {state!r} "
            f"at entry {entry_id!r}. Inspect `statem cur`, execute the current "
            "node prompt and its public checks, then move only through explicit "
            f"StateM transitions until {self._final_state!r} or a genuine terminal "
            "blocker. Do not redo completed states and do not return a prose-only "
            "status while an allowed transition remains."
        )

    async def _session_deadline_remaining_seconds(
        self,
        environment: BaseEnvironment,
    ) -> float | None:
        deadline_path = self._REMOTE_VERIFICATION_CHECKS / "deadline.json"
        script = "\n".join(
            [
                "import json, time",
                f"data = json.load(open({str(deadline_path)!r}, encoding='utf-8'))",
                "deadline = data.get('deadline_at_epoch')",
                "print('' if deadline is None else max(0.0, float(deadline) - time.time()))",
            ]
        )
        try:
            result = await self.exec_as_agent(
                environment,
                command="python3 -c " + shlex.quote(script),
            )
            value = (result.stdout or "").strip()
            return float(value) if value else None
        except (OSError, TypeError, ValueError):
            return None

    async def _session_progress_identity(
        self,
        environment: BaseEnvironment,
        run_id: str,
        current: dict[str, Any],
    ) -> tuple[str, ...]:
        """Return the bounded witness used to detect stalled resumes."""

        del environment, run_id
        return (
            str(current.get("current") or ""),
            str(current.get("current_entry_id") or ""),
        )

    def _session_no_progress_limit(self) -> int:
        """Consecutive unchanged resumes allowed before lifecycle handoff."""

        return 2

    async def _run_codex_with_state_resumes(
        self,
        instruction: str,
        environment: BaseEnvironment,
        run_id: str,
    ) -> None:
        """Run Codex once, then boundedly resume the same nonterminal session."""

        if not self.model_name:
            raise ValueError("Model name is required")

        model = self.model_name.split("/")[-1]
        cli_flags = self.build_cli_flags()
        cli_flags_arg = (cli_flags + " ") if cli_flags else ""
        auth_json_path = self._resolve_auth_json_path()
        remote_secrets_dir = self._REMOTE_CODEX_SECRETS_DIR.as_posix()
        remote_auth_path = (self._REMOTE_CODEX_SECRETS_DIR / "auth.json").as_posix()
        agent_output = (EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME).as_posix()
        env: dict[str, str] = {
            **self._statem_env(run_id),
            "CODEX_HOME": self._REMOTE_CODEX_HOME.as_posix(),
        }

        await self.exec_as_agent(
            environment,
            command=(
                f'mkdir -p "$CODEX_HOME" {shlex.quote(remote_secrets_dir)} '
                f"{shlex.quote(EnvironmentPaths.agent_dir.as_posix())}"
            ),
            env=env,
        )

        if auth_json_path:
            await environment.upload_file(auth_json_path, remote_auth_path)
            if environment.default_user is not None:
                await self.exec_as_root(
                    environment,
                    command=f"chown {environment.default_user} {remote_auth_path}",
                )
            setup_command = (
                f'ln -sf {shlex.quote(remote_auth_path)} "$CODEX_HOME/auth.json"\n'
            )
        else:
            env["OPENAI_API_KEY"] = self._get_env("OPENAI_API_KEY") or ""
            setup_command = (
                f"cat >{shlex.quote(remote_auth_path)} <<EOF\n"
                '{\n  "OPENAI_API_KEY": "${OPENAI_API_KEY}"\n}\nEOF\n'
                f"ln -sf {shlex.quote(remote_auth_path)} "
                '"$CODEX_HOME/auth.json"\n'
            )

        if openai_base_url := self._get_env("OPENAI_BASE_URL"):
            env["OPENAI_BASE_URL"] = openai_base_url
            setup_command += (
                '\ncat >>"$CODEX_HOME/config.toml" <<TOML\n'
                'openai_base_url = "${OPENAI_BASE_URL}"\n'
                "TOML"
            )

        if skills_command := self._build_register_skills_command():
            setup_command += f"\n{skills_command}"
        if mcp_command := self._build_register_mcp_servers_command():
            setup_command += f"\n{mcp_command}"
        if setup_command.strip():
            await self.exec_as_agent(environment, command=setup_command, env=env)

        initial_command = (
            "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
            "codex exec --dangerously-bypass-approvals-and-sandbox "
            "--skip-git-repo-check "
            f"--model {shlex.quote(model)} --json --enable unified_exec "
            f"{cli_flags_arg}-- {shlex.quote(instruction)} "
            f"2>&1 </dev/null | tee {shlex.quote(agent_output)}"
        )

        try:
            await self.exec_as_agent(environment, command=initial_command, env=env)
            no_progress_resumes = 0
            for _ in range(self._max_session_resumes):
                _, current = await self._current_statem(environment, run_id)
                if not current or current.get("current") == self._final_state:
                    break
                if not current.get("next"):
                    break
                remaining = await self._session_deadline_remaining_seconds(environment)
                if remaining is not None and remaining <= 30:
                    break
                before = await self._session_progress_identity(
                    environment,
                    run_id,
                    current,
                )
                resume_prompt = self._session_resume_prompt(current)
                resume_command = (
                    "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
                    "codex exec resume --last "
                    "--dangerously-bypass-approvals-and-sandbox "
                    "--skip-git-repo-check "
                    f"--model {shlex.quote(model)} --json --enable unified_exec "
                    f"{cli_flags_arg}-- {shlex.quote(resume_prompt)} "
                    f"2>&1 </dev/null | tee -a {shlex.quote(agent_output)}"
                )
                self._session_resume_attempts += 1
                await self.exec_as_agent(environment, command=resume_command, env=env)
                _, after = await self._current_statem(environment, run_id)
                after_identity = await self._session_progress_identity(
                    environment,
                    run_id,
                    after or {},
                )
                progress_changed = after_identity != before
                self._session_resume_trace.append(
                    {
                        "attempt": self._session_resume_attempts,
                        "before_state": before[0] if before else "",
                        "after_state": after_identity[0] if after_identity else "",
                        "progress_changed": progress_changed,
                    }
                )
                if not progress_changed:
                    no_progress_resumes += 1
                    if no_progress_resumes >= self._session_no_progress_limit():
                        break
                else:
                    no_progress_resumes = 0
        finally:
            try:
                await self.exec_as_agent(
                    environment,
                    command=(
                        f"mkdir -p {EnvironmentPaths.agent_dir.as_posix()}\n"
                        'if [ -d "$CODEX_HOME/sessions" ]; then\n'
                        f"  rm -rf {(EnvironmentPaths.agent_dir / 'sessions').as_posix()}\n"
                        f'  cp -R "$CODEX_HOME/sessions" {(EnvironmentPaths.agent_dir / "sessions").as_posix()}\n'
                        "fi"
                    ),
                    env=env,
                )
            except Exception:
                pass
            try:
                await self.exec_as_agent(
                    environment,
                    command=(
                        f'rm -rf {shlex.quote(remote_secrets_dir)} "$CODEX_HOME"'
                    ),
                    env=env,
                )
            except Exception:
                pass

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

    async def setup(self, environment: BaseEnvironment) -> None:
        await super().setup(environment)
        await self._install_statem(environment)

    async def _install_statem(self, environment: BaseEnvironment) -> None:
        if not (self._statem_source_dir / "statem").is_dir():
            raise FileNotFoundError(f"statem package not found in {self._statem_source_dir}")
        if not self._runbook_path.is_file():
            raise FileNotFoundError(f"statem runbook not found: {self._runbook_path}")

        await self.exec_as_root(
            environment,
            command=(
                "if command -v python3 >/dev/null 2>&1; then "
                "  python3 --version; "
                "elif [ -f /etc/alpine-release ]; then "
                "  apk add --no-cache python3; "
                "elif command -v apt-get >/dev/null 2>&1; then "
                "  apt-get update && apt-get install -y python3; "
                "elif command -v yum >/dev/null 2>&1; then "
                "  yum install -y python3; "
                "else "
                "  echo 'python3 is required for statem' >&2; exit 1; "
                "fi"
            ),
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )

        remote_src = self._REMOTE_STATEM_SRC.as_posix()
        remote_runbook_dir = self._REMOTE_RUNBOOK_DIR.as_posix()
        remote_state_dir = self._REMOTE_STATE_DIR.as_posix()
        remote_verification_checks = self._REMOTE_VERIFICATION_CHECKS.as_posix()

        await self.exec_as_root(
            environment,
            command=(
                f"rm -rf {shlex.quote(remote_src)} {shlex.quote(remote_runbook_dir)} "
                f"{shlex.quote(remote_verification_checks)} "
                f"{shlex.quote(remote_state_dir)} && "
                f"mkdir -p {shlex.quote(remote_src)} {shlex.quote(remote_runbook_dir)} "
                f"{shlex.quote(remote_state_dir)} {shlex.quote(remote_verification_checks)} && "
                f"chmod -R 777 {shlex.quote(remote_src)} {shlex.quote(remote_runbook_dir)} "
                f"{shlex.quote(remote_state_dir)} {shlex.quote(remote_verification_checks)}"
            ),
        )

        source_manifest = self._build_source_manifest()
        self._source_manifest = source_manifest

        statem_files = [
            Path(item["_local_path"])
            for item in source_manifest["files"]
            if item["group"] == "statem"
        ]
        remote_parent_dirs = sorted({
            PurePosixPath(item["remote_path"]).parent.as_posix()
            for item in source_manifest["files"]
        })
        if remote_parent_dirs:
            await self.exec_as_root(
                environment,
                command="mkdir -p " + " ".join(shlex.quote(path) for path in remote_parent_dirs),
            )

        for path in statem_files:
            relative = path.relative_to(self._statem_source_dir / "statem")
            remote_path = PurePosixPath(remote_src) / "statem" / relative.as_posix()
            await environment.upload_file(path, remote_path.as_posix())

        for item in source_manifest["files"]:
            if item["group"] in {"teamrun", "additional_runbook"}:
                await environment.upload_file(Path(item["_local_path"]), item["remote_path"])

        await environment.upload_file(self._runbook_path, self._REMOTE_RUNBOOK.as_posix())
        for path in self._verification_check_paths():
            await environment.upload_file(path, f"{remote_verification_checks}/{path.name}")

        await self._write_remote_text(
            environment,
            (self._REMOTE_VERIFICATION_CHECKS / "source-manifest.json").as_posix(),
            json.dumps(self._public_source_manifest(source_manifest), indent=2, sort_keys=True) + "\n",
        )

        await self.exec_as_root(
            environment,
            command=(
                "cat >/usr/local/bin/statem <<'SH'\n"
                "#!/bin/sh\n"
                f"PYTHONPATH={shlex.quote(remote_src)} exec python3 -m statem.cli \"$@\"\n"
                "SH\n"
                "chmod +x /usr/local/bin/statem\n"
                "statem validate "
                f"{shlex.quote(self._REMOTE_RUNBOOK.as_posix())} --json >/tmp/statem-validate.json"
            ),
        )
        await self._post_install_statem(environment)

    def _build_source_manifest(self) -> dict[str, Any]:
        files: list[dict[str, Any]] = []

        statem_root = self._statem_source_dir / "statem"
        for path in sorted(statem_root.rglob("*")):
            if path.is_file() and _should_upload_source_file(path.relative_to(statem_root)):
                relative = path.relative_to(statem_root)
                files.append(self._manifest_entry("statem", path, PurePosixPath("/tmp/statem-src/statem") / relative.as_posix()))

        files.append(self._manifest_entry("runbook", self._runbook_path, self._REMOTE_RUNBOOK))

        for path in self._verification_check_paths():
            files.append(
                self._manifest_entry(
                    "verification_check",
                    path,
                    self._REMOTE_VERIFICATION_CHECKS / path.name,
                )
            )

        files.extend(self._extra_source_manifest_entries())

        payload: dict[str, Any] = {
            "version": 1,
            "agent": self.name(),
            # Source identity must not change when an identical tree is checked
            # out under a different worktree basename.
            "source_root": "statem",
            "runbook": str(self._runbook_path.relative_to(self._statem_source_dir))
            if self._runbook_path.is_relative_to(self._statem_source_dir)
            else self._runbook_path.name,
            "file_count": len(files),
            "files": files,
        }
        encoded = json.dumps(self._public_source_manifest(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
        return payload

    def _extra_source_manifest_entries(self) -> list[dict[str, Any]]:
        return []

    def _verification_check_paths(self) -> list[Path]:
        """Return checks exposed to the agent for this adapter.

        The default adapter preserves the complete established check set.
        Experimental cross-benchmark adapters can override this method with a
        narrow allowlist so unrelated task-family guidance is not present in
        the sandbox at all.
        """
        checks_dir = (
            self._statem_source_dir
            / "integrations"
            / "harbor"
            / "verification_checks"
        )
        paths = (
            [
                path
                for path in sorted(checks_dir.iterdir())
                if path.suffix in {".py", ".json"} and path.is_file()
            ]
            if checks_dir.is_dir()
            else []
        )
        stop_hook = (
            self._statem_source_dir
            / "integrations"
            / "hooks"
            / "statem_stop_hook.py"
        )
        if stop_hook.is_file():
            paths.append(stop_hook)
        return paths

    def _codex_stop_hook_payload(self) -> dict[str, Any]:
        command_env = {
            "STATEM_STATE_DIR": self._REMOTE_STATE_DIR.as_posix(),
            "STATEM_COMMAND": "statem",
            "STATEM_HOST": "codex",
            "STATEM_STOP_REQUIRE_STATE_HOOKS": "true",
        }
        prefix = " ".join(
            f"{key}={shlex.quote(value)}" for key, value in command_env.items()
        )
        command = (
            f"{prefix} python3 {shlex.quote(self._REMOTE_STOP_HOOK.as_posix())}"
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
        remote_home = self._REMOTE_CODEX_HOME.as_posix()
        await self.exec_as_agent(
            environment,
            command=f"mkdir -p {shlex.quote(remote_home)}",
            env={"CODEX_HOME": remote_home},
        )
        await self._write_remote_text(
            environment,
            (self._REMOTE_CODEX_HOME / "hooks.json").as_posix(),
            json.dumps(self._codex_stop_hook_payload(), indent=2, sort_keys=True)
            + "\n",
        )

    async def _post_install_statem(self, environment: BaseEnvironment) -> None:
        return None

    def _manifest_entry(self, group: str, path: Path, remote_path: PurePosixPath) -> dict[str, Any]:
        try:
            local_relative = path.relative_to(self._statem_source_dir).as_posix()
        except ValueError:
            local_relative = path.name
        return {
            "group": group,
            "local_relative_path": local_relative,
            "_local_path": str(path),
            "remote_path": remote_path.as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }

    def _public_source_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        public = {key: value for key, value in manifest.items() if not key.startswith("_")}
        files = []
        for item in manifest.get("files") or []:
            if isinstance(item, dict):
                files.append({key: value for key, value in item.items() if not key.startswith("_")})
        public["files"] = files
        return public

    async def _write_remote_text(self, environment: BaseEnvironment, remote_path: str, text: str) -> None:
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

    async def _write_task_prompt(self, environment: BaseEnvironment, instruction: str) -> None:
        payload = instruction.encode("utf-8")
        encoded = base64.b64encode(payload).decode("ascii")
        remote_task = (self._REMOTE_VERIFICATION_CHECKS / "task.txt").as_posix()
        await self.exec_as_agent(
            environment,
            command=(
                "python3 -c "
                + shlex.quote(
                    "import base64, pathlib; "
                    f"pathlib.Path({remote_task!r}).write_bytes(base64.b64decode({encoded!r}))"
                )
            ),
        )

    def _agent_deadline_seconds_for_instruction(self, instruction: str) -> int:
        return int(self._agent_deadline_info_for_instruction(instruction)["agent_deadline_seconds"])

    def _agent_deadline_info_for_instruction(
        self,
        instruction: str,
        environment: BaseEnvironment | None = None,
    ) -> dict[str, Any]:
        fallback_deadline = self._fallback_agent_deadline_seconds_for_instruction(instruction)
        official_timeout = self._official_agent_timeout_seconds(environment)
        if official_timeout is not None:
            return {
                "agent_deadline_seconds": official_timeout,
                "deadline_source": "official_task_timeout",
                "official_agent_timeout_seconds": official_timeout,
                "fallback_agent_deadline_seconds": fallback_deadline,
            }
        return {
            "agent_deadline_seconds": fallback_deadline,
            "deadline_source": "configured_internal_budget",
            "fallback_agent_deadline_seconds": fallback_deadline,
        }

    def _fallback_agent_deadline_seconds_for_instruction(self, instruction: str) -> int:
        deadline = self._agent_deadline_seconds
        if _instruction_needs_extended_mature_gate_deadline(instruction):
            return max(deadline, 900)
        return deadline

    def _official_agent_timeout_seconds(self, environment: BaseEnvironment | None) -> int | None:
        if environment is None:
            return None
        task_config = self._official_task_config(environment)
        agent_config = task_config.get("agent") if isinstance(task_config, dict) else None
        if not isinstance(agent_config, dict):
            return None

        trial_config = self._trial_config(environment)
        trial_agent_config = trial_config.get("agent") if isinstance(trial_config.get("agent"), dict) else {}
        base_timeout = _positive_float(trial_agent_config.get("override_timeout_sec"))
        if base_timeout is None:
            base_timeout = _positive_float(agent_config.get("timeout_sec"))
        if base_timeout is None:
            return None

        max_timeout = _positive_float(trial_agent_config.get("max_timeout_sec"))
        if max_timeout is not None:
            base_timeout = min(base_timeout, max_timeout)

        multiplier = _positive_float(trial_config.get("agent_timeout_multiplier"))
        if multiplier is None:
            multiplier = _positive_float(trial_config.get("timeout_multiplier")) or 1.0
        return max(1, int(base_timeout * multiplier))

    def _official_task_config(self, environment: BaseEnvironment) -> dict[str, Any]:
        for path in self._official_task_config_candidates(environment):
            if not path.is_file():
                continue
            try:
                return tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                continue
        return {}

    def _official_task_config_candidates(self, environment: BaseEnvironment) -> list[Path]:
        candidates: list[Path] = []
        raw_environment_dir = getattr(environment, "environment_dir", None)
        if raw_environment_dir:
            environment_dir = Path(raw_environment_dir)
            candidates.extend([environment_dir / "task.toml", environment_dir.parent / "task.toml"])

        task_name = self._task_short_name(environment)
        if task_name:
            candidates.append(
                self._statem_source_dir
                / ".statem"
                / "benchmarks"
                / "tasks"
                / "terminal-bench-2-1"
                / task_name
                / "task.toml"
            )

        unique: list[Path] = []
        seen: set[Path] = set()
        for path in candidates:
            resolved = path.expanduser()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(resolved)
        return unique

    def _task_short_name(self, environment: BaseEnvironment) -> str:
        trial_config = self._trial_config(environment)
        task_config = trial_config.get("task") if isinstance(trial_config.get("task"), dict) else {}
        raw_name = str(task_config.get("name") or getattr(environment, "environment_name", "") or "")
        return raw_name.rsplit("/", 1)[-1].strip()

    def _trial_config(self, environment: BaseEnvironment) -> dict[str, Any]:
        trial_paths = getattr(environment, "trial_paths", None)
        config_path = getattr(trial_paths, "config_path", None)
        if not config_path:
            return {}
        try:
            value = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    async def _write_deadline_file(
        self,
        environment: BaseEnvironment,
        run_id: str,
        instruction: str = "",
    ) -> None:
        remote_deadline = (self._REMOTE_VERIFICATION_CHECKS / "deadline.json").as_posix()
        started_at = time.time()
        deadline_info = self._agent_deadline_info_for_instruction(instruction, environment)
        agent_deadline_seconds = int(deadline_info["agent_deadline_seconds"])
        payload = {
            "version": 1,
            "source": "statem_codex",
            "run_id": run_id,
            "started_at_epoch": started_at,
            "deadline_at_epoch": started_at + agent_deadline_seconds,
            "handoff_buffer_seconds": self._handoff_buffer_seconds,
            "heavy_work_buffer_seconds": self._heavy_work_buffer_seconds,
            **deadline_info,
        }
        await self._write_remote_text(
            environment,
            remote_deadline,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )

    def _statem_env(self, run_id: str) -> dict[str, str]:
        return {
            "PYTHONPATH": self._REMOTE_STATEM_SRC.as_posix(),
            "STATEM_STATE_DIR": self._REMOTE_STATE_DIR.as_posix(),
            "STATEM_AGENT_ID": self.name(),
            "STATEM_AGENT_ROLE": "benchmark-agent",
            "STATEM_RUN_ID": run_id,
            "STATEM_DEADLINE_FILE": (self._REMOTE_VERIFICATION_CHECKS / "deadline.json").as_posix(),
            "STATEM_RUNTIME_ANCHOR_FILE": (self._REMOTE_VERIFICATION_CHECKS / "runtime-anchor.json").as_posix(),
        }

    def _run_id(self, environment: BaseEnvironment) -> str:
        raw = f"{self._run_id_prefix}-{environment.session_id}"
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-") or self._run_id_prefix

    def _statem_cmd(self, subcommand: str, run_id: str) -> str:
        return (
            "statem "
            f"{subcommand} "
            f"--state-dir {shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
            f"--run-id {shlex.quote(run_id)}"
        )

    def _remote_runbook_for_instruction(self, instruction: str) -> PurePosixPath:
        return self._REMOTE_RUNBOOK

    async def _start_statem(
        self,
        environment: BaseEnvironment,
        run_id: str,
        remote_runbook: PurePosixPath | None = None,
    ) -> str:
        runbook = remote_runbook or self._REMOTE_RUNBOOK
        statem_env = self._statem_env(run_id)
        agent_id = statem_env.get("STATEM_AGENT_ID") or self.name()
        agent_role = statem_env.get("STATEM_AGENT_ROLE") or "benchmark-agent"
        result = await self.exec_as_agent(
            environment,
            command=(
                "statem start "
                f"{shlex.quote(runbook.as_posix())} "
                f"--state-dir {shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                f"--run-id {shlex.quote(run_id)} "
                "--agent-id "
                f"{shlex.quote(agent_id)} "
                "--agent-role "
                f"{shlex.quote(agent_role)}"
            ),
            env=statem_env,
        )
        return result.stdout or ""

    async def _current_statem(self, environment: BaseEnvironment, run_id: str) -> tuple[str, dict[str, Any] | None]:
        result = await self.exec_as_agent(
            environment,
            command=f"{self._statem_cmd('cur', run_id)} --json",
            env=self._statem_env(run_id),
        )
        raw = result.stdout or ""
        try:
            return raw, json.loads(raw)
        except json.JSONDecodeError:
            return raw, None

    async def _bootstrap_to_risk_probe(self, environment: BaseEnvironment, run_id: str) -> str:
        progress_note = (
            "## Host bootstrap\n"
            "- The benchmark task prompt was written to /tmp/statem-verification-checks/task.txt.\n"
            "- The benchmark deadline status was written to /tmp/statem-verification-checks/deadline.json.\n"
            "- Host advanced the run from triage to risk_probe because legacy bootstrap_risk_probe was enabled.\n"
            "- The agent still owns route selection, gate selection, solving, verification, repair, and handoff.\n"
        )
        encoded = base64.b64encode(progress_note.encode("utf-8")).decode("ascii")
        await self.exec_as_agent(
            environment,
            command=(
                "python3 -c "
                + shlex.quote(
                    "import base64, pathlib; "
                    "path = pathlib.Path('progress.md'); "
                    f"text = base64.b64decode({encoded!r}).decode('utf-8'); "
                    "path.write_text((path.read_text(encoding='utf-8') if path.exists() else '') + text, encoding='utf-8')"
                )
            ),
            env=self._statem_env(run_id),
        )
        result = await self.exec_as_agent(
            environment,
            command=f"{self._statem_cmd('goto risk_probe', run_id)} --yes",
            env=self._statem_env(run_id),
        )
        return result.stdout or ""

    async def _bootstrap_to_direct_solve(self, environment: BaseEnvironment, run_id: str) -> str:
        progress_note = (
            "## Host bootstrap\n"
            "- The benchmark task prompt was written to /tmp/statem-verification-checks/task.txt.\n"
            "- The benchmark deadline status was written to /tmp/statem-verification-checks/deadline.json.\n"
            "- Host advanced the run from triage to direct_solve so the agent starts on the default thin path.\n"
            "- The agent still owns solving, task-visible verification, optional risk_probe escalation, repair, and handoff.\n"
        )
        encoded = base64.b64encode(progress_note.encode("utf-8")).decode("ascii")
        await self.exec_as_agent(
            environment,
            command=(
                "python3 -c "
                + shlex.quote(
                    "import base64, pathlib; "
                    "path = pathlib.Path('progress.md'); "
                    f"text = base64.b64decode({encoded!r}).decode('utf-8'); "
                    "path.write_text((path.read_text(encoding='utf-8') if path.exists() else '') + text, encoding='utf-8')"
                )
            ),
            env=self._statem_env(run_id),
        )
        result = await self.exec_as_agent(
            environment,
            command=f"{self._statem_cmd('goto direct_solve', run_id)} --yes",
            env=self._statem_env(run_id),
        )
        return result.stdout or ""

    async def _bootstrap_by_auto_route(self, environment: BaseEnvironment, run_id: str) -> str:
        # V1.1 keeps the host bootstrap thin. The agent can still enter
        # risk_probe after direct_solve when task-visible evidence or a concrete
        # gap justifies the focused harness, while preflight in_hooks cover
        # mutation-prone inputs that must be protected before the first probe.
        return await self._bootstrap_to_direct_solve(environment, run_id)

    async def _initial_hook_context(self, environment: BaseEnvironment, run_id: str) -> str:
        """Return compact start-state guidance that would otherwise stay in statem history."""
        deadline = (self._REMOTE_VERIFICATION_CHECKS / "deadline.json").as_posix()
        early = (self._REMOTE_VERIFICATION_CHECKS / "early-domain-guidance.json").as_posix()
        script = f"""
import json
import pathlib
import subprocess

deadline = {deadline!r}
early = pathlib.Path({early!r})
parts = []
try:
    completed = subprocess.run(
        ["python3", "/tmp/statem-verification-checks/deadline_status.py", "--deadline", deadline],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if completed.stdout.strip():
        parts.append(completed.stdout.strip())
except Exception:
    pass
try:
    payload = json.loads(early.read_text(encoding="utf-8"))
except Exception:
    payload = {{}}
families = payload.get("families") if isinstance(payload.get("families"), list) else []
lines = []
for family in families[:3]:
    if not isinstance(family, dict):
        continue
    guidance = family.get("guidance") if isinstance(family.get("guidance"), list) else []
    family_limit = 1600 if len(families) == 1 else 650
    pieces = []
    for item in guidance:
        piece = str(item).strip()
        if not piece:
            continue
        candidate = "; ".join(pieces + [piece])
        if len(candidate) > family_limit:
            if not pieces:
                pieces.append(piece[: max(0, family_limit - 3)].rstrip() + "...")
            break
        pieces.append(piece)
    compact = "; ".join(pieces)
    if compact:
        lines.append(f"- {{family.get('name', 'early_guidance')}}: {{compact}}")
if lines:
    parts.append("early_domain_guidance:\\n" + "\\n".join(lines))
print("\\n".join(parts)[:1800])
"""
        result = await self.exec_as_agent(
            environment,
            command="python3 -c " + shlex.quote(script),
            env=self._statem_env(run_id),
        )
        return (result.stdout or "").strip()

    def _current_context(
        self,
        current_text: str,
        current: dict[str, Any] | None,
        initial_hook_context: str = "",
    ) -> str:
        if self._include_full_current or not current:
            return current_text.strip()

        next_states = []
        for edge in current.get("next") or []:
            if isinstance(edge, dict) and edge.get("to"):
                next_states.append(str(edge["to"]))
        hooks = []
        for hook in current.get("state_hooks") or []:
            if isinstance(hook, dict) and hook.get("name"):
                hooks.append(str(hook["name"]))
        prompt = str(current.get("prompt") or "").strip().splitlines()
        prompt_summary = " ".join(line.strip() for line in prompt[:3] if line.strip())
        if len(prompt_summary) > 500:
            prompt_summary = prompt_summary[:497].rstrip() + "..."

        lines = [
            f"Run: {current.get('run_id', '')}",
            f"Current: {current.get('current', '')}",
            f"Entry: {current.get('current_entry_id', '')}",
            f"Next: {', '.join(next_states) if next_states else '(none)'}",
            f"State hooks: {', '.join(hooks) if hooks else '(none)'}",
        ]
        if prompt_summary:
            lines.append(f"Prompt summary: {prompt_summary}")
        if initial_hook_context.strip():
            lines.append("Initial in-hook context:")
            lines.extend(f"  {line}" for line in initial_hook_context.strip().splitlines()[:12])
        lines.append(
            "Full state prompt, hooks, and blocking checks are available with "
            f"`statem cur --state-dir {self._REMOTE_STATE_DIR.as_posix()} --run-id {current.get('run_id', '')}`."
        )
        return "\n".join(lines)

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        state_dir = self._REMOTE_STATE_DIR.as_posix()
        return f"""You are {self.name()}, a Codex agent using statem as a thin phase-control runbook for this benchmark task.

Required statem protocol:
- The statem run has already been started for this trial.
- Before substantive work, inspect the current state with:
  `statem cur --state-dir {state_dir} --run-id {run_id}`
- Follow the current state's prompt and hooks. You may inspect the whole graph with:
  `statem state --state-dir {state_dir} --run-id {run_id}`
- Move only through explicit transitions with `statem goto TARGET --state-dir {state_dir} --run-id {run_id}`.
- If a transition has manual or checklist checks, rerun with `--yes` only after you actually verified the requested evidence.
- If `statem goto` fails, stay in the current state, fix the issue, and retry. Do not pretend the transition happened.
- Keep `progress.md` updated so statem predicates and later recovery have durable evidence.
- Solve from the visible task contract first. The default graph is thin:
  `direct_solve -> task_contract_check -> self_review -> soft_guard -> handoff`.
- `soft_guard` is a lightweight post-review audit; it should catch review gaps
  without running mature templates or broad catalog work.
- Optional focused guard states are entered only after self-review or receipts
  show a concrete evidence gap. Do not load broad harness guidance early.
- Preflight in_hooks may warn about mutation-prone local inputs. Follow those
  narrow preservation reminders before the first destructive probe.
- Do not use hidden benchmark artifacts, public benchmark solutions, verifier
  files, known answer artifacts, or task-name lookups. Use the sandbox files,
  standard tools, and ordinary package documentation.

Current statem state summary:
{current_context.strip()}

Benchmark task:
{instruction}
"""

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        run_id = self._run_id(environment)
        await self._write_task_prompt(environment, instruction)
        await self._write_deadline_file(environment, run_id, instruction)
        await self._start_statem(environment, run_id, self._remote_runbook_for_instruction(instruction))
        if self._bootstrap_risk_probe:
            await self._bootstrap_to_risk_probe(environment, run_id)
        elif self._bootstrap_direct_solve:
            await self._bootstrap_to_direct_solve(environment, run_id)
        elif self._bootstrap_auto_route:
            await self._bootstrap_by_auto_route(environment, run_id)
        current_text, current = await self._current_statem(environment, run_id)
        initial_hook_context = await self._initial_hook_context(environment, run_id)
        current_context = self._current_context(current_text, current, initial_hook_context)
        augmented_instruction = self._augment_instruction(instruction, run_id, current_context)
        await self._install_codex_stop_hook(environment)

        try:
            if environment.default_user is None:
                effective_user = await self._effective_agent_user(environment)
                with environment.with_default_user(effective_user):
                    if self._max_session_resumes:
                        await self._run_codex_with_state_resumes(
                            self.render_instruction(augmented_instruction),
                            environment,
                            run_id,
                        )
                    else:
                        await super().run(augmented_instruction, environment, context)
            else:
                if self._max_session_resumes:
                    await self._run_codex_with_state_resumes(
                        self.render_instruction(augmented_instruction),
                        environment,
                        run_id,
                    )
                else:
                    await super().run(augmented_instruction, environment, context)
        finally:
            try:
                # Harbor normally converts the copied Codex session after
                # run() returns. Generate ATIF first because the public
                # artifact cleanup below intentionally removes that session.
                await sync_remote_codex_sessions_for_atif(
                    environment, self.logs_dir
                )
                Codex.populate_context_post_run(self, context)
            finally:
                await self._remove_codex_session_logs(environment)
                await self._collect_statem_artifacts(environment, context, run_id)

    async def _remove_codex_session_logs(self, environment: BaseEnvironment) -> None:
        """Keep public Harbor artifacts focused on task-visible logs.

        The upstream Codex Harbor agent copies CODEX_HOME/sessions into the
        agent artifact directory. Those JSONL files can contain opaque
        encrypted payloads from the Codex client. They are removed only after
        Harbor has converted them to the public ATIF trajectory.
        """
        try:
            await self.exec_as_agent(
                environment,
                command=f"rm -rf {shlex.quote((EnvironmentPaths.agent_dir / 'sessions').as_posix())}",
            )
        except Exception:
            pass
        finally:
            # Cloud environments download the remote session into logs_dir so
            # Harbor can build ATIF before the remote workspace is released.
            shutil.rmtree(self.logs_dir / "sessions", ignore_errors=True)

    async def _collect_statem_artifacts(
        self,
        environment: BaseEnvironment,
        context: AgentContext,
        run_id: str,
    ) -> None:
        metadata: dict[str, Any] = {
            "run_id": run_id,
            "agent": self.name(),
            "session_resume_attempts": self._session_resume_attempts,
            "session_resume_trace": self._session_resume_trace,
        }
        if self._source_manifest:
            metadata["source_manifest_sha256"] = self._source_manifest.get("manifest_sha256")
            metadata["source_manifest_file_count"] = self._source_manifest.get("file_count")
        current: dict[str, Any] | None = None
        errors: list[str] = []

        try:
            _, current = await self._current_statem(environment, run_id)
            if current:
                metadata["current"] = current.get("current")
                metadata["current_entry_id"] = current.get("current_entry_id")
        except Exception as exc:
            errors.append(f"cur: {exc}")

        agent_dir = EnvironmentPaths.agent_dir.as_posix()
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    f"mkdir -p {shlex.quote(agent_dir)}/statem\n"
                    f"{self._statem_cmd('cur', run_id)} --json "
                    f">{shlex.quote(agent_dir)}/statem/current.json || true\n"
                    f"{self._statem_cmd('history', run_id)} --limit 100 --json "
                    f">{shlex.quote(agent_dir)}/statem/history.json || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'selection.json').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/verification-selection.json || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'risk-profile.json').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/risk-profile.json || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'gate-catalog.json').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/gate-catalog.json || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'verifier-evidence.json').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/verifier-evidence.json || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'self-review.json').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/self-review.json || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'task.txt').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/task.txt || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'source-manifest.json').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/source-manifest.json || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'deadline.json').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/deadline.json || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'runtime-anchor.json').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/runtime-anchor.json || true\n"
                    f"cp {shlex.quote((self._REMOTE_VERIFICATION_CHECKS / 'preflight-hazards.json').as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/preflight-hazards.json || true\n"
                    f"cp -R {shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                    f"{shlex.quote(agent_dir)}/statem/state || true\n"
                ),
                env=self._statem_env(run_id),
            )
        except Exception as exc:
            errors.append(f"artifacts: {exc}")

        if errors:
            metadata["errors"] = errors

        context.metadata = dict(context.metadata or {})
        context.metadata["statem"] = metadata

        if (
            self._enforce_final_state
            and current
            and current.get("current") != self._final_state
        ):
            raise RuntimeError(
                f"statem final state is {current.get('current')!r}, expected {self._final_state!r}"
            )


class NoIntermediaryUpdatesStatemCodex(StatemCodex):
    """A/B-only Codex adapter that removes the Intermediary updates prompt block.

    The model-instructions file is supplied externally and uploaded into each
    benchmark container. This class is intentionally not the default submission
    path; it isolates whether Codex's base prompt block is affecting thin-path
    reasoning without changing statem's runbook or focused guards.
    """

    _REMOTE_MODEL_INSTRUCTIONS = PurePosixPath("/tmp/statem-model-instructions-no-intermediary.md")

    CLI_FLAGS = [
        *Codex.CLI_FLAGS,
        CliFlag(
            "model_instructions_file",
            cli="-c",
            type="str",
            default=_REMOTE_MODEL_INSTRUCTIONS.as_posix(),
            format="-c model_instructions_file={value}",
        ),
    ]

    def __init__(
        self,
        *args: Any,
        model_instructions_source: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        source = (
            model_instructions_source
            or os.environ.get("STATEM_NO_INTERMEDIARY_MODEL_INSTRUCTIONS")
            or ".statem/benchmarks/private/gpt55-no-intermediary-model-instructions.md"
        )
        self._model_instructions_source = Path(source).expanduser()
        if not self._model_instructions_source.is_absolute():
            self._model_instructions_source = self._statem_source_dir / self._model_instructions_source

    @staticmethod
    def name() -> str:
        return "statem-codex-no-intermediary-ab"

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        if not self._model_instructions_source.is_file():
            raise FileNotFoundError(
                "No-intermediary model instructions file not found: "
                f"{self._model_instructions_source}"
            )
        await environment.upload_file(
            self._model_instructions_source,
            self._REMOTE_MODEL_INSTRUCTIONS.as_posix(),
        )
        if environment.default_user is not None:
            await self.exec_as_root(
                environment,
                command=(
                    f"chown {environment.default_user} "
                    f"{shlex.quote(self._REMOTE_MODEL_INSTRUCTIONS.as_posix())}"
                ),
            )
        await super().run(instruction, environment, context)


class TeamRunStatemCodex(StatemCodex):
    """Experimental statem-Codex variant with opt-in TeamRun CLI support.

    This does not assume nested LLM workers are available in the benchmark
    sandbox. It exposes TeamRun task ledgers and a host-side worker-loop helper
    for bounded deterministic workers or manual scoped worker execution.
    """

    def __init__(
        self,
        *args: Any,
        statem_source_dir: str | None = None,
        runbook_path: str | None = None,
        bootstrap_auto_route: bool = False,
        bootstrap_risk_probe: bool = False,
        bootstrap_direct_solve: bool = False,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        teamrun_runbook = repo_root / "examples" / "terminal-bench-agent-teamrun-video.yaml"
        super().__init__(
            *args,
            statem_source_dir=statem_source_dir,
            runbook_path=runbook_path or str(teamrun_runbook),
            bootstrap_auto_route=bootstrap_auto_route,
            bootstrap_risk_probe=bootstrap_risk_probe,
            bootstrap_direct_solve=bootstrap_direct_solve,
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-teamrun-exp"

    def _extra_source_manifest_entries(self) -> list[dict[str, Any]]:
        teamrun_dir = self._statem_source_dir / "integrations" / "teamrun"
        entries: list[dict[str, Any]] = []
        if teamrun_dir.is_dir():
            for path in sorted(teamrun_dir.iterdir()):
                if path.is_file() and path.suffix == ".py":
                    entries.append(self._manifest_entry("teamrun", path, self._REMOTE_TEAMRUN_DIR / path.name))
        return entries

    async def _post_install_statem(self, environment: BaseEnvironment) -> None:
        remote_src = self._REMOTE_STATEM_SRC.as_posix()
        worker_loop = (self._REMOTE_TEAMRUN_DIR / "teamrun_worker_loop.py").as_posix()
        reducer = (self._REMOTE_TEAMRUN_DIR / "teamrun_reduce.py").as_posix()
        codex_worker = (self._REMOTE_TEAMRUN_DIR / "teamrun_codex_worker.py").as_posix()
        codex_workers = (self._REMOTE_TEAMRUN_DIR / "teamrun_codex_workers.py").as_posix()
        await self.exec_as_root(
            environment,
            command=(
                "cat >/usr/local/bin/statem-teamrun-worker-loop <<'SH'\n"
                "#!/bin/sh\n"
                f"PYTHONPATH={shlex.quote(remote_src)} exec python3 {shlex.quote(worker_loop)} \"$@\"\n"
                "SH\n"
                "cat >/usr/local/bin/statem-teamrun-reduce <<'SH'\n"
                "#!/bin/sh\n"
                f"PYTHONPATH={shlex.quote(remote_src)} exec python3 {shlex.quote(reducer)} \"$@\"\n"
                "SH\n"
                "cat >/usr/local/bin/statem-teamrun-codex-worker <<'SH'\n"
                "#!/bin/sh\n"
                "export NVM_DIR=\"${NVM_DIR:-$HOME/.nvm}\"\n"
                "if [ -s \"$NVM_DIR/nvm.sh\" ]; then . \"$NVM_DIR/nvm.sh\"; fi\n"
                f"PYTHONPATH={shlex.quote(remote_src)} exec python3 {shlex.quote(codex_worker)} \"$@\"\n"
                "SH\n"
                "cat >/usr/local/bin/statem-teamrun-codex-workers <<'SH'\n"
                "#!/bin/sh\n"
                "export NVM_DIR=\"${NVM_DIR:-$HOME/.nvm}\"\n"
                "if [ -s \"$NVM_DIR/nvm.sh\" ]; then . \"$NVM_DIR/nvm.sh\"; fi\n"
                f"PYTHONPATH={shlex.quote(remote_src)} exec python3 {shlex.quote(codex_workers)} \"$@\"\n"
                "SH\n"
                "chmod +x /usr/local/bin/statem-teamrun-worker-loop /usr/local/bin/statem-teamrun-reduce "
                "/usr/local/bin/statem-teamrun-codex-worker /usr/local/bin/statem-teamrun-codex-workers"
            ),
        )

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        state_dir = self._REMOTE_STATE_DIR.as_posix()
        return f"""You are {self.name()}, an experimental Codex agent using statem TeamRun for bounded search tasks.

Use the normal visible task contract first. TeamRun is optional and should be
used only when the task has real bounded search uncertainty, such as video
frame events, video-to-text/OCR/transcript spans, or ambiguous visual evidence
where independent bounded coverage can reduce uncertainty. Scientific/numeric
fits should stay on the thin runbook; use state-conditioned domain guidance and
focused scientific evidence there instead of TeamRun.

Required statem protocol:
- Inspect the current state before substantive work:
  `statem cur --state-dir {state_dir} --run-id {run_id}`
- Move through explicit transitions with:
  `statem goto TARGET --state-dir {state_dir} --run-id {run_id}`
- If the task does not need bounded search, stay on the normal solve -> verify
  -> handoff path.
- If TeamRun is useful, move to `team_search`, write task-visible assignments
  to `/tmp/statem-teamrun/tasks.json`, run `statem team init`, claim/submit
  scoped results, then run `statem team advance reducing`. After that, choose
  one reducer path: use `statem team reduce --strategy all-claims-table --json`
  as the built-in reducer path, or use `statem team reduce-input --output
  /tmp/statem-teamrun/reducer-input.json` followed by a compact
  `/tmp/statem-teamrun/DECISION.json` and `statem team decide
  /tmp/statem-teamrun/DECISION.json` as the agent reducer path. Do not run
  both `reduce` and `decide` for the same TeamRun entry.
- Long-running child agents may append stage-visible findings with
  `statem team report`; reports keep the task open and do not manage subagent
  lifecycle.
- Minimal TeamRun task file shape:
  `{{"tasks":[{{"task_id":"boundary_semantics","priority":1,
  "assignment":"Inspect task-visible frames and report boundary convention evidence in claims."}}]}}`.
- If nested Codex subagents are available and budget allows for
  visual/OCR/frame evidence, use
  `statem-teamrun-codex-workers --run-id {run_id} --state-dir {state_dir}
  --entry-id <current-entry-id> --cwd /app --max-workers 2 --max-rounds 1
  --timeout 90 --wall-timeout 180 --return-slack 20 --lease-seconds 120
  --reasoning-effort medium --json` after `statem team init` to run scoped
  workers in parallel. Treat this as an optional accelerator, not a required
  proof path. Fall back to manual
  claim/submit only if the launcher is unavailable, no result appears before
  the lease expires, or deadline pressure makes nested workers too risky. Keep
  workers bounded; the lead agent still owns the final reducer decision and
  artifact. If the launcher exits nonzero and leaves leased tasks without
  results, run `statem team release --all-leased --reason launcher_failed`
  before manual fallback.
- For video/frame-event tasks, TeamRun evidence should produce a detector that
  recomputes boundaries on each input video. Do not hard-code sample frame
  numbers or fixed example-relative offsets unless justified by runtime-visible
  evidence from the current input. Prefer full-timeline or candidate-window
  coverage: workers should scan disjoint spans, plausible event windows, or
  competing boundary definitions and report the runtime-visible rule that
  selected each candidate. Require a complete temporal event sandwich before
  accepting a candidate window: task-visible non-event/baseline or approach
  context before the event, a distinct event phase such as flight/apex/motion
  change, and task-visible return or completion context afterward. Do not
  choose the first foreground change, frame-0 residual, or an isolated partial
  cue as the event unless the prompt explicitly defines that as the target.
  Calibrate event semantics from the task wording:
  labels such as "begins" or "starts" usually refer to the onset of a
  transition. For a binary transition, list the adjacent candidates on both
  sides; when wording is otherwise ambiguous, prefer the transition-adjacent
  frame rather than a stable-state frame. For departure/takeoff begins, this
  usually means the last contact/onset frame just before the fully-airborne
  state; for landing it usually means the first sustained return-to-contact
  window, not a single weak touch frame, unless the prompt explicitly asks for
  initial contact. Labels such as "airborne", "cleared", or "fully visible"
  refer to the achieved state.
  Worker results must put conclusions in `claims`; `evidence` is support only.
  A searched scope with no candidate should be `exhausted` with
  `coverage.complete=true`, not a completed empty-claims result.
- For video-to-text/OCR/transcript tasks, use TeamRun only to divide bounded
  uncertainty: disjoint time spans, uncertain frames, competing OCR readings,
  or alternate parsing of visible commands. Each worker should return
  candidate text lines plus evidence spans; the reducer chooses the final
  transcript and records unresolved ambiguity.
- Do not use hidden expected values or broaden the search after seeing a gate
  failure; keep hypotheses derived from the prompt, visible data, and ordinary
  domain conventions.
- `statem-teamrun-worker-loop` is available for deterministic bounded worker
  commands. Do not assume nested LLM workers are available unless a worker
  command is explicitly configured in the sandbox.
- Do not use hidden benchmark artifacts, public benchmark solutions, verifier
  files, known answer artifacts, or task-name lookups.
- Keep `progress.md` concise with candidate identity, TeamRun coverage, checks,
  and residual risk.

Current statem state summary:
{current_context.strip()}

Benchmark task:
{instruction}
"""


class HybridStatemCodex(TeamRunStatemCodex):
    """Submission-oriented adapter that combines thin and TeamRun runbooks.

    The thin/focused runbook remains the default. The TeamRun runbook is used
    only for visible bounded-search task families where fanout/reduce is the
    intended control surface: video/frame/OCR evidence.
    """

    def __init__(
        self,
        *args: Any,
        statem_source_dir: str | None = None,
        runbook_path: str | None = None,
        teamrun_runbook_path: str | None = None,
        bootstrap_auto_route: bool = False,
        bootstrap_risk_probe: bool = False,
        bootstrap_direct_solve: bool = False,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        thin_runbook = repo_root / "examples" / "terminal-bench-agent-thin-review.yaml"
        self._teamrun_runbook_path = (
            Path(teamrun_runbook_path).resolve()
            if teamrun_runbook_path
            else repo_root / "examples" / "terminal-bench-agent-teamrun-video.yaml"
        )
        StatemCodex.__init__(
            self,
            *args,
            statem_source_dir=statem_source_dir,
            runbook_path=runbook_path or str(thin_runbook),
            bootstrap_auto_route=bootstrap_auto_route,
            bootstrap_risk_probe=bootstrap_risk_probe,
            bootstrap_direct_solve=bootstrap_direct_solve,
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex"

    def _extra_source_manifest_entries(self) -> list[dict[str, Any]]:
        entries = TeamRunStatemCodex._extra_source_manifest_entries(self)
        entries.append(
            self._manifest_entry(
                "additional_runbook",
                self._teamrun_runbook_path,
                self._REMOTE_TEAMRUN_RUNBOOK,
            )
        )
        return entries

    async def _post_install_statem(self, environment: BaseEnvironment) -> None:
        await TeamRunStatemCodex._post_install_statem(self, environment)
        await self.exec_as_root(
            environment,
            command=(
                "statem validate "
                f"{shlex.quote(self._REMOTE_TEAMRUN_RUNBOOK.as_posix())} --json "
                ">/tmp/statem-teamrun-validate.json"
            ),
        )

    def _remote_runbook_for_instruction(self, instruction: str) -> PurePosixPath:
        if _instruction_uses_teamrun_runbook(instruction):
            return self._REMOTE_TEAMRUN_RUNBOOK
        return self._REMOTE_RUNBOOK

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        if _instruction_uses_teamrun_runbook(instruction):
            return TeamRunStatemCodex._augment_instruction(self, instruction, run_id, current_context)
        return StatemCodex._augment_instruction(self, instruction, run_id, current_context)


class ThinStatemCodex(StatemCodex):
    """Statem-Codex variant for negative-transfer sentinel experiments.

    This keeps explicit phase state and recovery artifacts, but removes the
    risk-profile/gate harness so we can test whether failures come from statem
    phase control itself or from overactive verification guidance.
    """

    def __init__(
        self,
        *args: Any,
        statem_source_dir: str | None = None,
        runbook_path: str | None = None,
        bootstrap_auto_route: bool = False,
        bootstrap_risk_probe: bool = False,
        bootstrap_direct_solve: bool = False,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        thin_runbook = repo_root / "examples" / "terminal-bench-agent-thin.yaml"
        super().__init__(
            *args,
            statem_source_dir=statem_source_dir,
            runbook_path=runbook_path or str(thin_runbook),
            bootstrap_auto_route=bootstrap_auto_route,
            bootstrap_risk_probe=bootstrap_risk_probe,
            bootstrap_direct_solve=bootstrap_direct_solve,
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin"

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        state_dir = self._REMOTE_STATE_DIR.as_posix()
        deadline_file = (self._REMOTE_VERIFICATION_CHECKS / "deadline.json").as_posix()
        return f"""You are {self.name()}, a Codex agent using a thin statem runbook for this benchmark task.

Statem is only a phase anchor here. It should help you remember whether you are solving, verifying, or handing off; it should not become the task.

Mission: complete the real task-visible contract using your normal reasoning and the files in the sandbox. Do not optimize for statem, do not invent broad proxy gates, and do not treat a weak sanity check as proof of semantic correctness.

Required thin statem protocol:
- The statem run has already been started for this trial.
- Inspect the current state before substantive work:
  `statem cur --state-dir {state_dir} --run-id {run_id}`
- Move through explicit transitions with:
  `statem goto TARGET --state-dir {state_dir} --run-id {run_id}`
- Keep `progress.md` concise: record task constraints, final artifact identity, commands run, and remaining risk.
- Use the task's own visible tests, examples, compile/import commands, consumer interface, or direct semantic checks. Do not use hidden benchmark artifacts, public benchmark solutions, verifier files, known answer artifacts, or task-name lookups.
- After `verify`, use `self_review` only as one short honest final pass when it can help catch a concrete issue without building a new harness. If verification or review reveals a concrete issue, return to `solve` and repair it. If the candidate is ready, move to `handoff`.
- Deadline status is available with:
  `python3 /tmp/statem-verification-checks/deadline_status.py --deadline {deadline_file}`
  If time is tight, stop optional exploration and hand off the best verified filesystem state.

Current statem state summary:
{current_context.strip()}

Benchmark task:
{instruction}
"""
