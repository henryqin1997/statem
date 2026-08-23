from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .core import DYNAMIC_CHECKS_SCHEMA_HINT, RunOptions, StatemError, StatemRuntime, validate_spec


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 1

    options = RunOptions(
        state_dir=Path(args.state_dir),
        yes=bool(args.yes),
        json_mode=bool(args.json),
        run_id=args.run_id,
        agent_id=args.agent_id,
        agent_role=args.agent_role,
    )
    try:
        payload = args.handler(args, options)
    except StatemError as exc:
        if getattr(args, "json", False):
            error_payload: dict[str, Any] = {"ok": False, "error": str(exc)}
            if exc.details:
                error_payload["details"] = exc.details
            print(json.dumps(error_payload, indent=2, sort_keys=True))
        else:
            print(f"statem: {exc}", file=sys.stderr)
            _print_error_details(exc.details)
        return getattr(exc, "exit_code", 1)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_payload(args.command, payload)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="statem",
        description="Command line state machine for agent long runs.",
        epilog=(
            "Loop hygiene: for cyclic runbooks, model compaction as an explicit node "
            "and use 'statem compact-prompt' to generate a safe /compact instruction."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--state-dir",
        default=os.environ.get("STATEM_STATE_DIR", ".statem"),
        help="runtime state directory (default: $STATEM_STATE_DIR or .statem)",
    )
    common.add_argument("--run-id", help="run id to use instead of the active run")
    common.add_argument("--agent-id", default=os.environ.get("STATEM_AGENT_ID"), help="agent instance id for dynamic checks")
    common.add_argument("--agent-role", default=os.environ.get("STATEM_AGENT_ROLE"), help="agent role metadata for dynamic checks")
    common.add_argument("--yes", action="store_true", help="auto-confirm manual checks and checklists")
    common.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    start = subparsers.add_parser("start", parents=[common], help="create or resume a run from a spec")
    start.add_argument("spec", help="spec file")
    start.add_argument("--fresh", action="store_true", help="force a new run even if an active run exists")
    start.set_defaults(handler=_cmd_start)

    cur = subparsers.add_parser("cur", parents=[common], help="show current state")
    cur.set_defaults(handler=_cmd_cur)

    state = subparsers.add_parser("state", parents=[common], help="list states and edges")
    state.set_defaults(handler=_cmd_state)

    show = subparsers.add_parser("ls", parents=[common], help="show node details")
    show.add_argument("node")
    show.set_defaults(handler=_cmd_ls)

    next_cmd = subparsers.add_parser("next", parents=[common], help="show next states")
    next_cmd.set_defaults(handler=_cmd_next)

    goto = subparsers.add_parser("goto", parents=[common], help="move to a next state")
    goto.add_argument("target")
    goto.set_defaults(handler=_cmd_goto)

    transfer = subparsers.add_parser("transfer", parents=[common], help="alias for goto")
    transfer.add_argument("target")
    transfer.set_defaults(handler=_cmd_goto)

    save = subparsers.add_parser("save", parents=[common], help="persist state and run current out_hook")
    save.add_argument("--skip-hooks", action="store_true", help="persist runtime state without running out_hook")
    save.set_defaults(handler=_cmd_save)

    return_cmd = subparsers.add_parser(
        "return",
        parents=[common],
        help="return from a nested runbook after reaching an allowed return state",
    )
    return_cmd.set_defaults(handler=_cmd_return)

    history = subparsers.add_parser("history", parents=[common], help="show run history")
    history.add_argument("--limit", "--tail", dest="limit", type=int, help="show only the last N events")
    history.set_defaults(handler=_cmd_history)

    prompt = subparsers.add_parser("prompt", parents=[common], help="print a post-clear resume prompt")
    prompt.add_argument(
        "--command",
        dest="statem_command",
        default="statem",
        help="statem command to embed in the prompt",
    )
    prompt.set_defaults(handler=_cmd_prompt)

    compact_prompt = subparsers.add_parser(
        "compact-prompt",
        parents=[common],
        help="print a safe /compact prompt for loop hygiene",
    )
    compact_prompt.add_argument(
        "--command",
        dest="statem_command",
        default="statem",
        help="statem command to embed in the prompt",
    )
    compact_prompt.set_defaults(handler=_cmd_compact_prompt)

    validate = subparsers.add_parser("validate", parents=[common], help="validate a spec")
    validate.add_argument("spec")
    validate.add_argument(
        "--strict",
        action="store_true",
        help="reject unknown runbook keywords at every supported schema level",
    )
    validate.set_defaults(handler=_cmd_validate)

    dynamic = subparsers.add_parser("dynamic", parents=[common], help="manage current-entry dynamic checks")
    dynamic_subparsers = dynamic.add_subparsers(dest="dynamic_command")

    dynamic_path = dynamic_subparsers.add_parser("path", parents=[common], help="show dynamic check directory")
    dynamic_path.set_defaults(handler=_cmd_dynamic_path)

    dynamic_write = dynamic_subparsers.add_parser(
        "write",
        parents=[common],
        help="write checks for this agent",
        epilog=(
            DYNAMIC_CHECKS_SCHEMA_HINT
            + " Example JSON: "
            + '{"basis":{"implementation_summary":"changed parser path"},'
            + '"checks":[{"type":"predicate","path":"/app/output.json","exists":true,'
            + '"reason":"final artifact must exist"}]}'
        ),
    )
    dynamic_write.add_argument("checks_file", help="JSON or mini-YAML dynamic checks file")
    dynamic_write.add_argument("--role", help="producer role metadata")
    dynamic_write.set_defaults(handler=_cmd_dynamic_write)

    dynamic_list = dynamic_subparsers.add_parser("list", parents=[common], help="list current dynamic check producers")
    dynamic_list.set_defaults(handler=_cmd_dynamic_list)

    dynamic_show = dynamic_subparsers.add_parser("show", parents=[common], help="alias for dynamic list")
    dynamic_show.set_defaults(handler=_cmd_dynamic_list)

    team = subparsers.add_parser("team", parents=[common], help="manage current-entry multi-agent TeamRun state")
    team_subparsers = team.add_subparsers(dest="team_command")

    team_entry = argparse.ArgumentParser(add_help=False)
    team_entry.add_argument(
        "--entry-id",
        default=os.environ.get("STATEM_ENTRY_ID"),
        help="current node entry id guard for TeamRun commands",
    )

    team_init = team_subparsers.add_parser("init", parents=[common, team_entry], help="initialize a TeamRun from tasks")
    team_init.add_argument("tasks_file", help="JSON or mini-YAML file with a tasks list")
    team_init.set_defaults(handler=_cmd_team_init)

    team_status = team_subparsers.add_parser("status", parents=[common, team_entry], help="show TeamRun status")
    team_status.set_defaults(handler=_cmd_team_status)

    team_cur = team_subparsers.add_parser("cur", parents=[common, team_entry], help="alias for TeamRun status")
    team_cur.set_defaults(handler=_cmd_team_status)

    team_prompt = team_subparsers.add_parser("prompt", parents=[common, team_entry], help="print a worker task prompt")
    team_prompt.add_argument("task_id")
    team_prompt.add_argument("--command", dest="statem_command", default="statem", help="statem command to embed")
    team_prompt.set_defaults(handler=_cmd_team_prompt)

    team_claim = team_subparsers.add_parser("claim", parents=[common, team_entry], help="claim an open TeamRun task")
    team_claim.add_argument("task_id", nargs="?", help="specific task id to claim; defaults to highest-priority open task")
    team_claim.add_argument("--lease-seconds", type=int, default=3600, help="lease duration before reclaim")
    team_claim.add_argument("--worker-index", type=int, help="zero-based shard index for ordered task distribution")
    team_claim.add_argument("--worker-count", type=int, help="number of worker shards for ordered task distribution")
    team_claim.set_defaults(handler=_cmd_team_claim)

    team_submit = team_subparsers.add_parser("submit", parents=[common, team_entry], help="submit a result for a leased task")
    team_submit.add_argument("task_id")
    team_submit.add_argument("result_file", help="JSON or mini-YAML result file")
    team_submit.set_defaults(handler=_cmd_team_submit)

    team_report = team_subparsers.add_parser("report", parents=[common, team_entry], help="append a partial report for a leased task")
    team_report.add_argument("task_id")
    team_report.add_argument("report_file", help="JSON or mini-YAML report file")
    team_report.set_defaults(handler=_cmd_team_report)

    team_release = team_subparsers.add_parser("release", parents=[common, team_entry], help="release leased TeamRun task(s) back to open")
    team_release.add_argument("task_id", nargs="?", help="specific task id to release")
    team_release.add_argument("--all-leased", action="store_true", help="release every currently leased task in this entry")
    team_release.add_argument("--reason", default="", help="short audit reason for releasing the lease")
    team_release.set_defaults(handler=_cmd_team_release)

    team_collect = team_subparsers.add_parser("collect", parents=[common, team_entry], help="show TeamRun result digest")
    team_collect.set_defaults(handler=_cmd_team_collect)

    team_advance = team_subparsers.add_parser("advance", parents=[common, team_entry], help="advance the TeamRun phase")
    team_advance.add_argument("phase", choices=["divided", "exploring", "reducing", "decided", "blocked"])
    team_advance.set_defaults(handler=_cmd_team_advance)

    team_reduce_input = team_subparsers.add_parser("reduce-input", parents=[common, team_entry], help="write reducer input JSON")
    team_reduce_input.add_argument("--output", help="output file; defaults to reduce/reducer-input.json")
    team_reduce_input.set_defaults(handler=_cmd_team_reduce_input)

    team_reduce = team_subparsers.add_parser("reduce", parents=[common, team_entry], help="run the configured TeamRun reducer")
    team_reduce.add_argument("--strategy", help="override configured reducer strategy")
    team_reduce.set_defaults(handler=_cmd_team_reduce)

    team_decide = team_subparsers.add_parser("decide", parents=[common, team_entry], help="record the final TeamRun decision")
    team_decide.add_argument("decision_file", help="JSON or mini-YAML decision file")
    team_decide.set_defaults(handler=_cmd_team_decide)

    hooks = subparsers.add_parser("hooks", parents=[common], help="inspect or run active state hooks")
    hooks_subparsers = hooks.add_subparsers(dest="hooks_command")

    hooks_active = hooks_subparsers.add_parser("active", parents=[common], help="show active state hooks")
    hooks_active.add_argument("--event", help="filter by hook event, such as stop")
    hooks_active.add_argument("--host", help="filter by host, such as codex or claude")
    hooks_active.set_defaults(handler=_cmd_hooks_active)

    hooks_run = hooks_subparsers.add_parser("run", parents=[common], help="run active hooks for an event")
    hooks_run.add_argument("event", help="hook event to run, such as stop")
    hooks_run.add_argument("--host", help="filter by host, such as codex or claude")
    hooks_run.add_argument("--command", dest="statem_command", default="statem", help="statem command to embed in prompts")
    hooks_run.set_defaults(handler=_cmd_hooks_run)

    return parser


def _cmd_start(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).start(args.spec, fresh=args.fresh)


def _cmd_cur(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).cur()


def _cmd_state(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).graph_state()


def _cmd_ls(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).node_details(args.node)


def _cmd_next(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).next_states()


def _cmd_goto(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).goto(args.target)


def _cmd_save(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).save(skip_hooks=args.skip_hooks)


def _cmd_return(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).return_runbook()


def _cmd_history(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).history(limit=args.limit)


def _cmd_prompt(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).prompt(command=args.statem_command)


def _cmd_compact_prompt(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).compact_prompt(command=args.statem_command)


def _cmd_validate(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return validate_spec(args.spec, strict=args.strict)


def _cmd_dynamic_path(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).dynamic_path()


def _cmd_dynamic_write(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).dynamic_write(args.checks_file, agent_id=args.agent_id, role=args.role)


def _cmd_dynamic_list(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).dynamic_list()


def _cmd_team_init(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_init(args.tasks_file, entry_id=args.entry_id)


def _cmd_team_status(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_status(entry_id=args.entry_id)


def _cmd_team_prompt(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_prompt(args.task_id, entry_id=args.entry_id, command=args.statem_command)


def _cmd_team_claim(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_claim(
        args.task_id,
        entry_id=args.entry_id,
        lease_seconds=args.lease_seconds,
        worker_index=args.worker_index,
        worker_count=args.worker_count,
    )


def _cmd_team_submit(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_submit(args.task_id, args.result_file, entry_id=args.entry_id)


def _cmd_team_report(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_report(args.task_id, args.report_file, entry_id=args.entry_id)


def _cmd_team_release(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_release(
        args.task_id,
        entry_id=args.entry_id,
        all_leased=args.all_leased,
        agent_id=args.agent_id,
        reason=args.reason,
    )


def _cmd_team_collect(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_status(entry_id=args.entry_id, include_results=True)


def _cmd_team_advance(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_advance(args.phase, entry_id=args.entry_id)


def _cmd_team_reduce_input(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_reduce_input(entry_id=args.entry_id, output_file=args.output)


def _cmd_team_reduce(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_reduce(entry_id=args.entry_id, strategy=args.strategy)


def _cmd_team_decide(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).team_decide(args.decision_file, entry_id=args.entry_id)


def _cmd_hooks_active(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).active_state_hooks(event=args.event, host=args.host)


def _cmd_hooks_run(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).run_state_hooks(args.event, host=args.host, command=args.statem_command)


def _print_error_details(details: dict[str, Any]) -> None:
    if not details:
        return
    summary = details.get("summary")
    if summary:
        print(f"hint: {summary}", file=sys.stderr)
    pending = details.get("pending_confirmation") or []
    if pending:
        print("pending confirmation:", file=sys.stderr)
        for item in pending:
            print(f"- {item.get('purpose')} {item.get('type')}: {item.get('output')}", file=sys.stderr)


def _print_payload(command: str, payload: dict[str, Any]) -> None:
    if command in {"start", "cur"}:
        _print_cur(payload)
    elif command == "state":
        _print_state(payload)
    elif command == "ls":
        _print_node(payload)
    elif command == "next":
        _print_next(payload)
    elif command in {"goto", "transfer"}:
        _print_goto(payload)
    elif command == "save":
        _print_save(payload)
    elif command == "return":
        if "from" in payload and "to" in payload:
            _print_goto(payload)
        elif "spec_name" in payload:
            _print_cur(payload)
        else:
            _print_save(payload)
    elif command == "history":
        _print_history(payload)
    elif command in {"prompt", "compact-prompt"}:
        print(payload["prompt"], end="")
    elif command == "validate":
        _print_validate(payload)
    elif command == "dynamic":
        _print_dynamic(payload)
    elif command == "team":
        _print_team(payload)
    elif command == "hooks":
        _print_hooks(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def _print_cur(payload: dict[str, Any]) -> None:
    print(f"Run: {payload['run_id']}")
    print(f"Spec: {payload['spec_name']} ({payload['spec']})")
    print(f"Current: {payload['current']}")
    if payload.get("current_entry_id"):
        print(f"Entry: {payload['current_entry_id']}")
    if payload.get("dynamic_before_transfer"):
        dynamic = payload["dynamic_before_transfer"]
        print(f"Dynamic checks: {dynamic.get('resolved_path') or dynamic.get('path')}")
    if payload.get("multi_agent"):
        team = payload["multi_agent"]
        print(f"TeamRun: {team.get('mode')} required={team.get('required')}")
    if payload.get("state_hooks"):
        print("State hooks: " + ", ".join(str(hook.get("name")) for hook in payload["state_hooks"]))
    if payload.get("runbook_return"):
        nested = payload["runbook_return"]
        allowed = ", ".join(str(value) for value in nested.get("return_states", []))
        print(
            "Nested return: "
            f"can_return={bool(nested.get('can_return'))} allowed=[{allowed}] "
            f"parent={nested.get('parent_node')}"
        )
    if payload.get("prompt"):
        print("\nPrompt:")
        print(payload["prompt"])
    if payload.get("before_transfer"):
        print("\nBefore transfer:")
        for item in payload["before_transfer"]:
            print(f"- {_summary_text(item)}")
    _print_next({"next": payload.get("next", [])})


def _print_state(payload: dict[str, Any]) -> None:
    print(f"Run: {payload['run_id']}")
    print(f"Current: {payload['current']}")
    print("\nStates:")
    for node in payload["nodes"]:
        marker = "*" if node["name"] == payload["current"] else "-"
        print(f"{marker} {node['name']}")
    print("\nEdges:")
    for edge in payload["edges"]:
        print(f"- {edge['from']} -> {edge['to']}")


def _print_node(payload: dict[str, Any]) -> None:
    current_marker = " (current)" if payload["node"] == payload["current"] else ""
    print(f"Node: {payload['node']}{current_marker}")
    if payload.get("prompt"):
        print("\nPrompt:")
        print(payload["prompt"])
    for key, title in [("in_hook", "In hook"), ("before_transfer", "Before transfer"), ("out_hook", "Out hook")]:
        if payload.get(key):
            print(f"\n{title}:")
            for item in payload[key]:
                print(f"- {_summary_text(item)}")
    if payload.get("dynamic_before_transfer"):
        dynamic = payload["dynamic_before_transfer"]
        print("\nDynamic before transfer:")
        print(f"- path: {dynamic.get('resolved_path') or dynamic.get('path')}")
        print(f"- allow_types: {', '.join(dynamic.get('allow_types', []))}")
    if payload.get("multi_agent"):
        team = payload["multi_agent"]
        print("\nTeamRun:")
        print(f"- mode: {team.get('mode')}")
        print(f"- required: {team.get('required')}")
        if team.get("resolved_path"):
            print(f"- path: {team.get('resolved_path')}")
    if payload.get("state_hooks"):
        print("\nState hooks:")
        for hook in payload["state_hooks"]:
            print(f"- {hook.get('event')}:{hook.get('name')} ({hook.get('template')})")
    _print_next({"next": payload.get("next", [])})


def _print_next(payload: dict[str, Any]) -> None:
    print("\nNext:")
    if not payload.get("next"):
        print("- (none)")
        return
    for edge in payload["next"]:
        condition = ""
        if edge.get("condition"):
            condition = " | condition: " + "; ".join(_summary_text(item) for item in edge["condition"])
        attempts = f" | max_attempts: {edge['max_attempts']}" if "max_attempts" in edge else ""
        print(f"- {edge['to']}{attempts}{condition}")


def _print_goto(payload: dict[str, Any]) -> None:
    print(f"Moved: {payload['from']} -> {payload['to']}")
    _print_results(payload.get("results", []))


def _print_save(payload: dict[str, Any]) -> None:
    print(f"Saved run {payload['run_id']} at {payload['current']}")
    _print_results(payload.get("results", []))


def _print_history(payload: dict[str, Any]) -> None:
    print(f"Run: {payload['run_id']}")
    print(f"Current: {payload['current']}")
    for event in payload.get("history", []):
        if event["event"] == "goto":
            detail = f"{event.get('from')} -> {event.get('to')}"
        elif event["event"] in {"goto_blocked", "save", "save_blocked"}:
            detail = event.get("stage") or event.get("node") or ""
        else:
            detail = event.get("current") or event.get("node") or ""
        print(f"- {event['ts']} {event['event']} {detail}".rstrip())


def _print_validate(payload: dict[str, Any]) -> None:
    print(f"Valid spec: {payload['name']}")
    if payload.get("strict"):
        print("Strict keywords: yes")
    print(f"Initial: {payload['initial']}")
    print(f"Nodes: {', '.join(payload['nodes'])}")
    print(f"Edges: {len(payload['edges'])}")


def _print_dynamic(payload: dict[str, Any]) -> None:
    print(f"Run: {payload['run_id']}")
    print(f"Current: {payload['current']}")
    print(f"Entry: {payload.get('current_entry_id')}")
    if payload.get("agent_id"):
        print(f"Agent: {payload['agent_id']}")
    if payload.get("path"):
        print(f"Path: {payload['path']}")
    if "checks" in payload:
        print(f"Checks: {payload['checks']}")
    for producer in payload.get("producers", []):
        details = producer.get("producer", {})
        label = details.get("agent_id") or producer.get("path")
        print(f"- {label}: {producer.get('checks', 0)} check(s)")


def _print_team(payload: dict[str, Any]) -> None:
    if "prompt" in payload:
        print(payload["prompt"], end="")
        return
    print(f"Run: {payload.get('run_id')}")
    print(f"Current: {payload.get('current')}")
    if payload.get("current_entry_id"):
        print(f"Entry: {payload.get('current_entry_id')}")
    if payload.get("phase"):
        print(f"TeamRun: {payload.get('phase')} ({payload.get('path') or payload.get('decision_path') or ''})")
    counts = payload.get("counts") or {}
    if counts:
        print(
            "Counts: "
            + ", ".join(f"{key}={value}" for key, value in counts.items() if value and key != "closed")
        )
    frontier = payload.get("frontier") or {}
    recommended = frontier.get("recommended_actions") or []
    if recommended:
        print("Recommended: " + ", ".join(str(item) for item in recommended))
    if payload.get("claimed_task"):
        task = payload["claimed_task"]
        print(f"Claimed: {task.get('task_id')} -> {task.get('assignment_path')}")
    if payload.get("submitted_task"):
        task = payload["submitted_task"]
        print(f"Submitted: {task.get('task_id')} status={task.get('status')} -> {task.get('result_path')}")
    if payload.get("reported_task"):
        task = payload["reported_task"]
        print(f"Reported: {task.get('task_id')} claims={task.get('claims')} -> {task.get('report_path')}")
    if payload.get("decision"):
        print("Decision:")
        print(json.dumps(payload["decision"], indent=2, sort_keys=True))


def _print_hooks(payload: dict[str, Any]) -> None:
    print(f"Run: {payload['run_id']}")
    print(f"Current: {payload['current']}")
    if payload.get("current_entry_id"):
        print(f"Entry: {payload['current_entry_id']}")
    if payload.get("event"):
        print(f"Event: {payload['event']}")
    if "decision" in payload:
        print(f"Decision: {payload['decision']}")
        if payload.get("reason"):
            print("\nReason:")
            print(payload["reason"])
    hooks = payload.get("hooks", [])
    if not hooks:
        print("Hooks: (none)")
        return
    print("Hooks:")
    for hook in hooks:
        hosts = ", ".join(str(host) for host in hook.get("hosts", []))
        print(f"- {hook.get('event')}:{hook.get('name')} template={hook.get('template')} hosts={hosts}")


def _print_results(results: list[dict[str, Any]]) -> None:
    interesting = [result for result in results if not result["passed"] or result.get("continued")]
    if not interesting:
        return
    print("\nChecks:")
    for result in interesting:
        status = "continued" if result.get("continued") else "failed"
        print(f"- {result['purpose']} {result['type']} {status}: {result.get('output', '')}")


def _summary_text(item: dict[str, Any]) -> str:
    item_type = item.get("type")
    if item_type == "command":
        return f"command: {item.get('run')}"
    if item_type == "llm_review":
        command = item.get("run") or "$STATEM_LLM_REVIEW_CMD"
        return f"llm_review: {item.get('prompt')} via {command}"
    if item_type == "predicate":
        bits = [f"predicate: {item.get('path')}"]
        for key in ("exists", "non_empty", "contains", "matches", "json_path", "equals"):
            if key in item:
                bits.append(f"{key}={item[key]!r}")
        return ", ".join(bits)
    if item_type == "checklist":
        return "checklist: " + ", ".join(str(value) for value in item.get("items", []))
    if item_type == "runbook":
        target = item.get("runbook") or item.get("selector")
        return f"runbook: {target!r} return_states={item.get('return_states', [])!r}"
    return f"{item_type}: {item.get('text')}"


if __name__ == "__main__":
    raise SystemExit(main())
