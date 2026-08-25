#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HARBOR_BIN = Path(
    os.environ.get("STATEM_HARBOR_BIN", REPO_ROOT / ".venv" / "bin" / "harbor")
).expanduser().resolve()
HARBOR_PYTHON = Path(
    os.environ.get("STATEM_HARBOR_PYTHON", HARBOR_BIN.parent / "python")
).expanduser()
DEFAULT_AGENT_TIMEOUT_SECONDS = 750
DEFAULT_HARBOR_AGENT_TIMEOUT_SECONDS = 900
DEFAULT_ENV_FILE = REPO_ROOT / ".statem" / "benchmarks" / "daytona.env"
DEFAULT_JOBS_DIR = REPO_ROOT / ".statem" / "benchmarks" / "jobs"
DEFAULT_AUTH_JSON = Path.home() / ".codex" / "auth.json"
DEFAULT_TASK_LIST_FILE = REPO_ROOT / ".statem" / "benchmarks" / "terminal-bench-2-1-tasks.txt"
DEFAULT_DATASET = "terminal-bench/terminal-bench-2-1"
AUTO_CONCURRENCY_BY_BATCH = {
    "env-retry": 2,
    "reversal": 3,
    "source-build": 2,
    "scientific": 3,
    "targeted-v10": 2,
    "video": 2,
}
AUTO_CONCURRENCY_FULL_DATASET = 2
AUTO_CONCURRENCY_CUSTOM_DEFAULT = 3
AUTO_CONCURRENCY_CUSTOM_HEAVY = 2
HEAVY_TASK_MARKERS = (
    "build",
    "compile",
    "extract-moves-from-video",
    "pov-ray",
    "qemu",
    "source",
    "video",
)
HARBOR_NON_AGENT_TIMEOUT_RETRY_EXCLUDES = (
    "VerifierTimeoutError",
    "RewardFileNotFoundError",
    "RewardFileEmptyError",
    "VerifierOutputParseError",
)


PRESET_TASKS: dict[str, list[str]] = {
    "targeted-v10": [
        "terminal-bench/build-pov-ray",
        "terminal-bench/gpt2-codegolf",
        "terminal-bench/torch-pipeline-parallelism",
        "terminal-bench/qemu-alpine-ssh",
        "terminal-bench/dna-insert",
        "terminal-bench/dna-assembly",
        "terminal-bench/filter-js-from-html",
        "terminal-bench/configure-git-webserver",
        "terminal-bench/raman-fitting",
        "terminal-bench/video-processing",
        "terminal-bench/extract-moves-from-video",
    ],
    "env-retry": [
        "terminal-bench/torch-pipeline-parallelism",
        "terminal-bench/gpt2-codegolf",
        "terminal-bench/filter-js-from-html",
        "terminal-bench/qemu-alpine-ssh",
    ],
    "reversal": [
        "terminal-bench/torch-pipeline-parallelism",
        "terminal-bench/gpt2-codegolf",
        "terminal-bench/filter-js-from-html",
    ],
    "source-build": [
        "terminal-bench/build-pov-ray",
    ],
    "scientific": [
        "terminal-bench/raman-fitting",
    ],
    "video": [
        "terminal-bench/video-processing",
        "terminal-bench/extract-moves-from-video",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a Terminal-Bench Harbor batch with statem-Codex defaults."
    )
    parser.add_argument(
        "--batch",
        choices=sorted(PRESET_TASKS),
        default="targeted-v10",
        help="Named local task batch. These presets are runner-only; gates remain task-agnostic.",
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=(
            "Harbor dataset selector. Pin an explicit version for new studies, "
            "for example terminal-bench/terminal-bench@3.0.0."
        ),
    )
    parser.add_argument(
        "--dataset-path",
        type=Path,
        help=(
            "Use a pinned local task or dataset directory instead of --dataset. "
            "Useful when an older Harbor client cannot resolve git-backed registry tasks."
        ),
    )
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Override preset with one or more task names, e.g. terminal-bench/raman-fitting.",
    )
    parser.add_argument(
        "--all-tasks",
        action="store_true",
        help="Run the full dataset without --include-task-name filters.",
    )
    parser.add_argument(
        "--exclude-task",
        action="append",
        default=[],
        help=(
            "Exclude one or more org/name tasks from an --all-tasks run via "
            "Harbor's --exclude-task-name filter."
        ),
    )
    parser.add_argument(
        "--priority-task",
        action="append",
        default=[],
        help=(
            "When used with --all-tasks, run these tasks first while still "
            "including the remaining full-dataset tasks. Accepts bare task names "
            "or org/name strings."
        ),
    )
    parser.add_argument(
        "--task-list-file",
        type=Path,
        default=DEFAULT_TASK_LIST_FILE,
        help="Full task list used to order --all-tasks when --priority-task is provided.",
    )
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument(
        "--reasoning-effort",
        default="xhigh",
        help="Reasoning effort to pass through to compatible Harbor agents.",
    )
    parser.add_argument("--agent-name", default="ziheng-yaxin-statem-codex")
    parser.add_argument(
        "--agent-import-path",
        default="integrations.harbor.statem_codex:StatemCodex",
        help=(
            "Harbor custom-agent import path. The runner records this alongside "
            "--agent-name in a minimal base config so leaderboard source-filter "
            "matching sees both the public agent name and its implementation."
        ),
    )
    parser.add_argument(
        "--additional-agent",
        action="append",
        default=[],
        metavar="NAME=IMPORT_PATH",
        help=(
            "Add a matched agent arm using the same model and common agent kwargs. "
            "May be repeated; all arms run in one Harbor job."
        ),
    )
    parser.add_argument("--jobs-dir", type=Path, default=DEFAULT_JOBS_DIR)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--environment", choices=["daytona", "docker"], default="daytona")
    parser.add_argument("--codex-auth-json", type=Path, default=DEFAULT_AUTH_JSON)
    parser.add_argument(
        "--auth-mode",
        choices=["api-key", "auth-json", "claude", "deepseek", "gemini", "opencode"],
        default="api-key",
        help=(
            "Agent authentication mode. api-key reads OPENAI_API_KEY from the "
            "process or env file; auth-json uploads a Codex auth.json into the "
            "benchmark environment; claude reads ANTHROPIC_API_KEY or "
            "ANTHROPIC_AUTH_TOKEN, plus optional ANTHROPIC_BASE_URL, for "
            "Claude Code-compatible agents; deepseek stages a pre-generated "
            "official Codex provider config; gemini reads Gemini API, Vertex, "
            "or OAuth configuration from the env file; opencode uses OpenCode Zen and "
            "permits anonymous access to its free models."
        ),
    )
    parser.add_argument(
        "--deepseek-codex-config-home",
        type=Path,
        default=REPO_ROOT / ".statem" / "benchmarks" / "deepseek-codex-home",
        help=(
            "Host directory containing the official DeepSeek Codex config.toml "
            "and models.json. Used only with --auth-mode deepseek."
        ),
    )
    parser.add_argument(
        "--agent-kwarg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional Harbor --agent-kwarg entries to pass through.",
    )
    parser.add_argument(
        "--agent-env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional Harbor --agent-env entries to pass through.",
    )
    parser.add_argument(
        "--no-statem-agent-env",
        action="store_true",
        help=(
            "Do not inject StateM stop-hook or planning-deadline environment "
            "variables. Intended for matched native-agent baseline cells; the "
            "default remains unchanged."
        ),
    )
    parser.add_argument(
        "--concurrency",
        default="auto",
        help=(
            "Harbor -n value. Use an integer to force a value, or 'auto' "
            "to select a conservative concurrency from the batch/task mix."
        ),
    )
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument(
        "--retry-agent-timeouts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Retry AgentTimeoutError up to --max-retries. Harbor excludes agent "
            "timeouts by default, so this runner explicitly replaces that exclusion "
            "set while preserving verifier and reward-file timeout exclusions."
        ),
    )
    parser.add_argument("--environment-build-timeout-multiplier", type=float, default=None)
    parser.add_argument("--timeout-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--wall-timeout-seconds",
        type=int,
        default=0,
        help=(
            "Optional outer timeout for the whole Harbor process. This is for "
            "local iteration hygiene so verifier/environment hangs are not "
            "mistaken for real task failures."
        ),
    )
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--prelaunch-expected-practice",
        help=(
            "Require the visible-instruction selector to choose this exact "
            "practice before Harbor or an environment starts."
        ),
    )
    parser.add_argument(
        "--prelaunch-practice-catalog",
        type=Path,
        help="Catalog used by both the host prelaunch check and thin-family adapter.",
    )
    parser.add_argument(
        "--prelaunch-route-receipt",
        type=Path,
        help="Optional output path for the field-validated prelaunch receipt.",
    )
    parser.add_argument(
        "--prelaunch-only",
        action="store_true",
        help="Run configured prelaunch checks and exit before auth or an environment starts.",
    )
    parser.add_argument(
        "--prelaunch-task-field-check",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "For pinned local tasks, reject artifact declaration fields that the "
            "installed Harbor runtime does not model."
        ),
    )
    parser.add_argument(
        "--prelaunch-task-field-receipt",
        type=Path,
        help="Optional output path for a single-task runtime field receipt.",
    )
    args = parser.parse_args()

    if args.all_tasks and args.task:
        parser.error("--all-tasks cannot be combined with --task")
    if args.dataset_path is not None and not args.dataset_path.expanduser().exists():
        parser.error(f"dataset path does not exist: {args.dataset_path}")
    if args.exclude_task and not args.all_tasks:
        parser.error("--exclude-task is only supported with --all-tasks")
    if args.priority_task and not args.all_tasks:
        parser.error("--priority-task is only supported with --all-tasks")
    tasks = (
        _ordered_full_task_list(args.task_list_file, args.priority_task, parser)
        if args.all_tasks and args.priority_task
        else ([] if args.all_tasks else (args.task or PRESET_TASKS[args.batch]))
    )
    if not args.all_tasks and not tasks:
        parser.error("no tasks selected")
    for task in tasks:
        if "/" not in task:
            parser.error(f"task should be an org/name string, got {task!r}")
    for task in args.exclude_task:
        if "/" not in task:
            parser.error(f"excluded task should be an org/name string, got {task!r}")
    concurrency, concurrency_reason = _resolve_concurrency(
        args.concurrency,
        batch=args.batch,
        tasks=tasks,
        all_tasks=args.all_tasks,
        parser=parser,
    )

    prelaunch_receipt = _run_prelaunch_route_check(args, tasks, parser)
    if prelaunch_receipt is not None:
        print(
            "Prelaunch route: "
            f"{prelaunch_receipt['decision']} "
            f"({prelaunch_receipt['reason']})"
        )
        if prelaunch_receipt["decision"] != "admit":
            parser.error(
                "prelaunch route rejected: "
                f"expected {prelaunch_receipt['expected_practice_id']!r}, "
                f"selected {prelaunch_receipt['selected_practice_id']!r}"
            )

    if args.prelaunch_task_field_check and args.dataset_path is not None:
        if not HARBOR_BIN.exists():
            parser.error(f"missing Harbor executable: {HARBOR_BIN}")
    task_field_receipts = _run_prelaunch_task_field_checks(args, tasks, parser)
    for receipt in task_field_receipts:
        print(
            "Prelaunch task fields: "
            f"{receipt['decision']} ({receipt['reason']}) for {receipt['task']}"
        )
        if receipt["decision"] != "admit":
            parser.error(
                "prelaunch task fields rejected: "
                + ", ".join(receipt["unsupported_artifact_fields"])
            )

    if args.prelaunch_only:
        if prelaunch_receipt is None and not task_field_receipts:
            parser.error("no prelaunch check was applicable")
        return 0

    if not HARBOR_BIN.exists():
        parser.error(f"missing Harbor executable: {HARBOR_BIN}")
    use_env_file = args.environment == "daytona" or args.auth_mode in {
        "api-key",
        "claude",
        "gemini",
    }
    if use_env_file and args.env_file.exists():
        env_file_values = _read_env_file(args.env_file)
    elif use_env_file:
        parser.error(f"missing env file: {args.env_file}")
    else:
        env_file_values = {}
    if args.auth_mode == "auth-json" and not args.codex_auth_json.exists():
        parser.error(f"missing Codex auth json: {args.codex_auth_json}")
    if args.auth_mode == "deepseek":
        missing = [
            name
            for name in ("config.toml", "models.json")
            if not (args.deepseek_codex_config_home / name).is_file()
        ]
        if missing:
            parser.error(
                "deepseek Codex config home is missing: " + ", ".join(missing)
            )
    if (
        args.auth_mode == "api-key"
        and "OPENAI_API_KEY" not in os.environ
        and "OPENAI_API_KEY" not in env_file_values
    ):
        parser.error("auth-mode api-key requires OPENAI_API_KEY in the environment or env file")
    if args.auth_mode == "claude" and not (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or env_file_values.get("ANTHROPIC_API_KEY")
        or env_file_values.get("ANTHROPIC_AUTH_TOKEN")
    ):
        parser.error(
            "auth-mode claude requires ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN "
            "in the environment or env file"
        )
    if args.auth_mode == "gemini" and not _has_gemini_auth(env_file_values):
        parser.error(
            "auth-mode gemini requires GEMINI_API_KEY, GOOGLE_API_KEY, Vertex "
            "credentials, or Gemini OAuth configuration in the environment or env file"
        )
    if args.auth_mode == "gemini" and args.reasoning_effort not in {
        "minimal",
        "low",
        "medium",
        "high",
        "",
    }:
        parser.error(
            "Gemini CLI reasoning effort must be minimal, low, medium, or high"
        )

    additional_agents = _parse_additional_agents(
        args.additional_agent,
        primary_name=args.agent_name,
        parser=parser,
    )
    agent_config_path = _write_agent_base_config(
        jobs_dir=args.jobs_dir,
        job_name=args.job_name,
        agent_name=args.agent_name,
        agent_import_path=args.agent_import_path,
        model=args.model,
        additional_agents=additional_agents,
    )

    dataset_args = (
        ["--path", str(args.dataset_path.expanduser().resolve())]
        if args.dataset_path is not None
        else ["--dataset", args.dataset]
    )
    cmd = [
        str(HARBOR_BIN),
        "run",
        "--config",
        str(agent_config_path),
        *dataset_args,
        "-e",
        args.environment,
        "-k",
        str(args.attempts),
        "-n",
        str(concurrency),
        "--timeout-multiplier",
        str(args.timeout_multiplier),
        "--max-retries",
        str(args.max_retries),
        "--jobs-dir",
        str(args.jobs_dir),
        "--job-name",
        args.job_name,
        "--yes",
    ]
    if args.retry_agent_timeouts:
        for exception_type in HARBOR_NON_AGENT_TIMEOUT_RETRY_EXCLUDES:
            cmd.extend(["--retry-exclude", exception_type])
    if not args.no_statem_agent_env:
        jobs_index = cmd.index("--jobs-dir")
        cmd[jobs_index:jobs_index] = [
            "--agent-env",
            "STATEM_STOP_REQUIRE_STATE_HOOKS=true",
            "--agent-env",
            f"STATEM_AGENT_DEADLINE_SECONDS={_statem_agent_deadline_seconds(args.timeout_multiplier)}",
        ]
    if args.environment_build_timeout_multiplier is not None:
        cmd.extend(
            [
                "--environment-build-timeout-multiplier",
                str(args.environment_build_timeout_multiplier),
            ]
        )
    if _uses_glm_claude_adapter(args.agent_import_path, args.auth_mode) and args.timeout_multiplier > 1:
        glm_deadline_seconds = _glm_agent_deadline_seconds(args.timeout_multiplier)
        glm_handoff_buffer_seconds = _glm_handoff_buffer_seconds(args.timeout_multiplier)
        glm_heavy_work_buffer_seconds = _glm_heavy_work_buffer_seconds(args.timeout_multiplier)
        _append_agent_kwarg_if_missing(
            cmd,
            args.agent_kwarg,
            "agent_deadline_seconds",
            str(glm_deadline_seconds),
        )
        _append_agent_kwarg_if_missing(
            cmd,
            args.agent_kwarg,
            "handoff_buffer_seconds",
            str(glm_handoff_buffer_seconds),
        )
        _append_agent_kwarg_if_missing(
            cmd,
            args.agent_kwarg,
            "heavy_work_buffer_seconds",
            str(glm_heavy_work_buffer_seconds),
        )
        _append_agent_env_if_missing(
            cmd,
            args.agent_env,
            "STATEM_GLM_AGENT_DEADLINE_SECONDS",
            str(glm_deadline_seconds),
        )
        _append_agent_env_if_missing(
            cmd,
            args.agent_env,
            "STATEM_GLM_HANDOFF_BUFFER_SECONDS",
            str(glm_handoff_buffer_seconds),
        )
        _append_agent_env_if_missing(
            cmd,
            args.agent_env,
            "STATEM_GLM_HEAVY_WORK_BUFFER_SECONDS",
            str(glm_heavy_work_buffer_seconds),
        )
    if args.reasoning_effort:
        cmd.extend(["--agent-kwarg", f"reasoning_effort={args.reasoning_effort}"])
    if args.auth_mode == "deepseek":
        _append_agent_kwarg_if_missing(
            cmd,
            args.agent_kwarg,
            "deepseek_config_home",
            str(args.deepseek_codex_config_home.expanduser().resolve()),
        )
    for agent_kwarg in args.agent_kwarg:
        if "=" not in agent_kwarg:
            parser.error(f"--agent-kwarg must be KEY=VALUE, got {agent_kwarg!r}")
        cmd.extend(["--agent-kwarg", agent_kwarg])
    for agent_env in args.agent_env:
        if "=" not in agent_env:
            parser.error(f"--agent-env must be KEY=VALUE, got {agent_env!r}")
        cmd.extend(["--agent-env", agent_env])
    if use_env_file:
        cmd.extend(["--env-file", str(args.env_file)])
    if args.environment == "daytona":
        cmd.extend(
            [
                "--retry-include",
                "EnvironmentStartTimeoutError",
                "--retry-include",
                "DaytonaError",
            ]
        )
        if args.retry_agent_timeouts:
            cmd.extend(["--retry-include", "AgentTimeoutError"])
    for task in tasks:
        cmd.extend(
            [
                "--include-task-name",
                _dataset_filter_name(task, local_path=args.dataset_path is not None),
            ]
        )
    for task in args.exclude_task:
        cmd.extend(
            [
                "--exclude-task-name",
                _dataset_filter_name(task, local_path=args.dataset_path is not None),
            ]
        )
    if args.upload:
        cmd.append("--upload")
        cmd.append("--public" if args.public else "--private")
    if args.auth_mode == "auth-json":
        cmd.extend(
            [
                "--agent-env",
                f"CODEX_AUTH_JSON_PATH={args.codex_auth_json.expanduser()}",
                "--agent-env",
                "CODEX_FORCE_AUTH_JSON=true",
            ]
        )
    elif args.auth_mode == "api-key":
        cmd.extend(["--agent-env", "CODEX_FORCE_AUTH_JSON=false"])
    elif args.auth_mode == "deepseek":
        cmd.extend(["--agent-env", "CODEX_FORCE_AUTH_JSON=false"])

    print("Selected tasks:")
    if args.all_tasks and not tasks:
        print(f"  - all tasks in {args.dataset}")
    else:
        for task in tasks:
            print(f"  - {task}")
    print()
    if args.dataset_path is not None:
        print(f"Dataset path: {args.dataset_path.expanduser().resolve()}")
        print(f"Dataset identity: {args.dataset} (caller-recorded pin)")
    else:
        print(f"Dataset: {args.dataset}")
    print()
    print("Agents:")
    print(f"  - {args.agent_name}: {args.agent_import_path}")
    for name, import_path in additional_agents:
        print(f"  - {name}: {import_path}")
    print()
    print(f"Concurrency: {concurrency} ({concurrency_reason})")
    print()
    print("Command:")
    print(shlex.join(cmd))
    if args.dry_run:
        return 0

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["PYTHONPATH"] = _prepend_pythonpath(REPO_ROOT, env.get("PYTHONPATH"))
    env.update({key: value for key, value in env_file_values.items() if key not in env})
    return _call_with_optional_timeout(cmd, env=env, timeout_seconds=args.wall_timeout_seconds)


def _prepend_pythonpath(path: Path, existing: str | None) -> str:
    path_text = str(path)
    if not existing:
        return path_text
    parts = existing.split(os.pathsep)
    if path_text in parts:
        return existing
    return path_text + os.pathsep + existing


def _run_prelaunch_route_check(
    args: argparse.Namespace,
    tasks: list[str],
    parser: argparse.ArgumentParser,
) -> dict[str, object] | None:
    configured = any(
        (
            args.prelaunch_expected_practice,
            args.prelaunch_practice_catalog,
            args.prelaunch_route_receipt,
        )
    )
    if not configured:
        return None
    if not args.prelaunch_expected_practice or not args.prelaunch_practice_catalog:
        parser.error(
            "--prelaunch-expected-practice and --prelaunch-practice-catalog "
            "must be provided together"
        )
    if args.all_tasks or len(tasks) != 1:
        parser.error("prelaunch route checks require exactly one selected task")
    if args.dataset_path is None:
        parser.error("prelaunch route checks require a pinned --dataset-path")
    if args.additional_agent:
        parser.error("prelaunch route checks do not support additional agents")

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from integrations.harbor.experimental.tb3_prelaunch_route_check import (
        build_prelaunch_route_receipt,
        write_prelaunch_route_receipt,
    )

    receipt_path = args.prelaunch_route_receipt or (
        args.jobs_dir
        / ".prelaunch-receipts"
        / f"{args.job_name}.route.json"
    )
    try:
        receipt = build_prelaunch_route_receipt(
            dataset_path=args.dataset_path,
            task=tasks[0],
            job_name=args.job_name,
            agent_name=args.agent_name,
            agent_import_path=args.agent_import_path,
            agent_kwargs=args.agent_kwarg,
            expected_practice_id=args.prelaunch_expected_practice,
            catalog_path=args.prelaunch_practice_catalog,
        )
        write_prelaunch_route_receipt(receipt, receipt_path)
    except ValueError as exc:
        parser.error(f"invalid prelaunch route configuration: {exc}")
    return receipt


def _run_prelaunch_task_field_checks(
    args: argparse.Namespace,
    tasks: list[str],
    parser: argparse.ArgumentParser,
) -> list[dict[str, object]]:
    if not args.prelaunch_task_field_check or args.dataset_path is None:
        if args.prelaunch_task_field_receipt is not None:
            parser.error(
                "--prelaunch-task-field-receipt requires a pinned --dataset-path "
                "and task field checks"
            )
        return []

    selected_tasks = tasks or _discover_local_tasks(args.dataset_path)
    if not selected_tasks:
        parser.error("task field checks found no local tasks")
    if args.prelaunch_task_field_receipt is not None and len(selected_tasks) != 1:
        parser.error("an explicit task field receipt requires exactly one task")

    runtime = _load_harbor_artifact_schema(parser)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from integrations.harbor.experimental.tb3_task_runtime_compat import (
        build_task_runtime_compat_receipt,
        write_task_runtime_compat_receipt,
    )

    receipts: list[dict[str, object]] = []
    for task in selected_tasks:
        try:
            receipt = build_task_runtime_compat_receipt(
                dataset_path=args.dataset_path,
                task=task,
                job_name=args.job_name,
                runtime_name=runtime["runtime_name"],
                runtime_version=runtime["runtime_version"],
                supported_artifact_fields=runtime["artifact_fields"],
            )
            receipt_path = args.prelaunch_task_field_receipt or (
                args.jobs_dir
                / ".prelaunch-receipts"
                / f"{args.job_name}.{task.rsplit('/', 1)[-1]}.task-fields.json"
            )
            write_task_runtime_compat_receipt(receipt, receipt_path)
        except ValueError as exc:
            parser.error(f"invalid prelaunch task field configuration: {exc}")
        receipts.append(receipt)
    return receipts


def _load_harbor_artifact_schema(
    parser: argparse.ArgumentParser,
) -> dict[str, object]:
    if not HARBOR_PYTHON.exists():
        parser.error(f"missing Harbor Python executable: {HARBOR_PYTHON}")
    script = (
        "import json; from importlib.metadata import version; "
        "from harbor.models.trial.config import ArtifactConfig; "
        "print(json.dumps({'runtime_name':'harbor',"
        "'runtime_version':version('harbor'),"
        "'artifact_fields':sorted(ArtifactConfig.model_fields)}))"
    )
    completed = subprocess.run(
        [str(HARBOR_PYTHON), "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        parser.error("failed to inspect Harbor artifact schema")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        parser.error("Harbor artifact schema inspection returned invalid JSON")
    if not isinstance(payload, dict):
        parser.error("Harbor artifact schema inspection must return an object")
    fields = payload.get("artifact_fields")
    if (
        not isinstance(fields, list)
        or not fields
        or any(not isinstance(field, str) or not field for field in fields)
    ):
        parser.error("Harbor artifact schema inspection returned invalid fields")
    for key in ("runtime_name", "runtime_version"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            parser.error(f"Harbor artifact schema inspection omitted {key}")
    return payload


def _discover_local_tasks(dataset_path: Path) -> list[str]:
    root = dataset_path.expanduser().resolve()
    candidates = [path for path in root.glob("*/task.toml")]
    candidates.extend(path for path in (root / "tasks").glob("*/task.toml"))
    names = sorted({path.parent.name for path in candidates})
    return [f"terminal-bench/{name}" for name in names]


def _dataset_filter_name(task: str, *, local_path: bool) -> str:
    if local_path:
        return task.rsplit("/", 1)[-1]
    return task


def _write_agent_base_config(
    *,
    jobs_dir: Path,
    job_name: str,
    agent_name: str,
    agent_import_path: str,
    model: str,
    additional_agents: list[tuple[str, str]] | None = None,
) -> Path:
    """Write the stable agent identity that Harbor's CLI cannot express alone."""
    config_dir = jobs_dir.expanduser().resolve() / ".generated-configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"{job_name}.json"
    agents = [(agent_name, agent_import_path), *(additional_agents or [])]
    config = {
        "agents": [
            {
                "name": name,
                "import_path": import_path,
                "model_name": model,
            }
            for name, import_path in agents
        ]
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path


def _parse_additional_agents(
    values: list[str],
    *,
    primary_name: str,
    parser: argparse.ArgumentParser,
) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    names = {primary_name}
    for value in values:
        if "=" not in value:
            parser.error(
                f"--additional-agent must be NAME=IMPORT_PATH, got {value!r}"
            )
        name, import_path = (part.strip() for part in value.split("=", 1))
        if not name or not import_path or ":" not in import_path:
            parser.error(
                f"--additional-agent must be NAME=MODULE:CLASS, got {value!r}"
            )
        if name in names:
            parser.error(f"agent name is duplicated: {name}")
        names.add(name)
        parsed.append((name, import_path))
    return parsed


def _statem_agent_deadline_seconds(timeout_multiplier: float) -> int:
    try:
        multiplier = float(timeout_multiplier)
    except (TypeError, ValueError):
        multiplier = 1.0
    if multiplier <= 0:
        multiplier = 1.0
    return max(1, int(DEFAULT_AGENT_TIMEOUT_SECONDS * multiplier))


def _glm_agent_deadline_seconds(timeout_multiplier: float) -> int:
    try:
        multiplier = float(timeout_multiplier)
    except (TypeError, ValueError):
        multiplier = 1.0
    if multiplier <= 0:
        multiplier = 1.0
    return max(1, int(DEFAULT_HARBOR_AGENT_TIMEOUT_SECONDS * multiplier))


def _glm_handoff_buffer_seconds(timeout_multiplier: float) -> int:
    deadline = _glm_agent_deadline_seconds(timeout_multiplier)
    return min(900, max(240, int(deadline * 0.08)))


def _glm_heavy_work_buffer_seconds(timeout_multiplier: float) -> int:
    deadline = _glm_agent_deadline_seconds(timeout_multiplier)
    return min(2400, max(480, int(deadline * 0.15)))


def _uses_glm_claude_adapter(agent_import_path: str, auth_mode: str) -> bool:
    lowered = agent_import_path.lower()
    return auth_mode == "claude" or "statem_claude_code" in lowered or "claudecode" in lowered


def _append_agent_env_if_missing(
    cmd: list[str],
    raw_agent_env: list[str],
    key: str,
    value: str,
) -> None:
    prefix = f"{key}="
    if any(item.startswith(prefix) for item in raw_agent_env):
        return
    cmd.extend(["--agent-env", f"{key}={value}"])


def _append_agent_kwarg_if_missing(
    cmd: list[str],
    raw_agent_kwargs: list[str],
    key: str,
    value: str,
) -> None:
    prefix = f"{key}="
    if any(item.startswith(prefix) for item in raw_agent_kwargs):
        return
    cmd.extend(["--agent-kwarg", f"{key}={value}"])


def _call_with_optional_timeout(
    cmd: list[str], *, env: dict[str, str], timeout_seconds: int
) -> int:
    if timeout_seconds <= 0:
        return subprocess.call(cmd, cwd=REPO_ROOT, env=env)

    process = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout_seconds)
    except KeyboardInterrupt:
        print("Interrupted; terminating the Harbor process group.", file=sys.stderr)
        _terminate_process_group(process)
        raise
    except subprocess.TimeoutExpired:
        print(
            (
                f"Harbor batch exceeded outer wall timeout of {timeout_seconds}s; "
                "terminating the process group. Treat this as verifier/environment "
                "hang evidence unless the job result completed with a real score."
            ),
            file=sys.stderr,
        )
        _terminate_process_group(process)
        return 124


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip("\"'")
    return values


def _has_gemini_auth(env_file_values: dict[str, str]) -> bool:
    names = {
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GEMINI_OAUTH_CREDS_PATH",
        "GEMINI_FORCE_OAUTH",
    }
    return any(os.environ.get(name) or env_file_values.get(name) for name in names)


def _resolve_concurrency(
    raw_value: str,
    *,
    batch: str,
    tasks: list[str],
    all_tasks: bool,
    parser: argparse.ArgumentParser,
) -> tuple[int, str]:
    value = raw_value.strip().lower()
    if value != "auto":
        try:
            concurrency = int(value)
        except ValueError:
            parser.error("--concurrency must be a positive integer or 'auto'")
        if concurrency < 1:
            parser.error("--concurrency must be >= 1")
        return concurrency, "explicit override"

    if all_tasks:
        return AUTO_CONCURRENCY_FULL_DATASET, "auto full-dataset policy"

    if tasks == PRESET_TASKS.get(batch):
        concurrency = AUTO_CONCURRENCY_BY_BATCH.get(batch, AUTO_CONCURRENCY_CUSTOM_DEFAULT)
        return concurrency, f"auto preset policy for batch '{batch}'"

    heavy_tasks = [task for task in tasks if _looks_heavy_task(task)]
    if heavy_tasks:
        labels = ", ".join(_task_label(task) for task in heavy_tasks[:3])
        if len(heavy_tasks) > 3:
            labels += ", ..."
        return (
            AUTO_CONCURRENCY_CUSTOM_HEAVY,
            f"auto custom-task policy with heavy task(s): {labels}",
        )
    return AUTO_CONCURRENCY_CUSTOM_DEFAULT, "auto custom-task policy"


def _looks_heavy_task(task: str) -> bool:
    label = _task_label(task).lower()
    return any(marker in label for marker in HEAVY_TASK_MARKERS)


def _task_label(task: str) -> str:
    return task.rsplit("/", 1)[-1]


def _ordered_full_task_list(
    task_list_file: Path,
    priority_tasks: list[str],
    parser: argparse.ArgumentParser,
) -> list[str]:
    if not task_list_file.exists():
        parser.error(f"missing full task list file for --priority-task: {task_list_file}")
    full_tasks: list[str] = []
    seen: set[str] = set()
    for raw_line in task_list_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        task = _normalize_task_name(line)
        label = _task_label(task)
        if label in seen:
            parser.error(f"duplicate task in task list file: {label}")
        seen.add(label)
        full_tasks.append(task)
    if not full_tasks:
        parser.error(f"empty full task list file: {task_list_file}")

    priority: list[str] = []
    for raw_task in priority_tasks:
        task = _normalize_task_name(raw_task)
        label = _task_label(task)
        if label not in seen:
            parser.error(f"--priority-task not found in task list: {raw_task!r}")
        if task not in priority:
            priority.append(task)

    priority_labels = {_task_label(task) for task in priority}
    return priority + [task for task in full_tasks if _task_label(task) not in priority_labels]


def _normalize_task_name(task: str) -> str:
    task = task.strip()
    if "/" in task:
        return task
    return f"terminal-bench/{task}"


if __name__ == "__main__":
    sys.exit(main())
