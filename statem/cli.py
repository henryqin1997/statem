from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .core import RunOptions, StatemError, StatemRuntime, validate_spec


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
    validate.set_defaults(handler=_cmd_validate)

    dynamic = subparsers.add_parser("dynamic", parents=[common], help="manage current-entry dynamic checks")
    dynamic_subparsers = dynamic.add_subparsers(dest="dynamic_command")

    dynamic_path = dynamic_subparsers.add_parser("path", parents=[common], help="show dynamic check directory")
    dynamic_path.set_defaults(handler=_cmd_dynamic_path)

    dynamic_write = dynamic_subparsers.add_parser("write", parents=[common], help="write checks for this agent")
    dynamic_write.add_argument("checks_file", help="JSON or mini-YAML dynamic checks file")
    dynamic_write.add_argument("--role", help="producer role metadata")
    dynamic_write.set_defaults(handler=_cmd_dynamic_write)

    dynamic_list = dynamic_subparsers.add_parser("list", parents=[common], help="list current dynamic check producers")
    dynamic_list.set_defaults(handler=_cmd_dynamic_list)

    dynamic_show = dynamic_subparsers.add_parser("show", parents=[common], help="alias for dynamic list")
    dynamic_show.set_defaults(handler=_cmd_dynamic_list)

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


def _cmd_history(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).history(limit=args.limit)


def _cmd_prompt(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).prompt(command=args.statem_command)


def _cmd_compact_prompt(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).compact_prompt(command=args.statem_command)


def _cmd_validate(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return validate_spec(args.spec)


def _cmd_dynamic_path(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).dynamic_path()


def _cmd_dynamic_write(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).dynamic_write(args.checks_file, agent_id=args.agent_id, role=args.role)


def _cmd_dynamic_list(args: argparse.Namespace, options: RunOptions) -> dict[str, Any]:
    return StatemRuntime(options).dynamic_list()


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
    elif command == "history":
        _print_history(payload)
    elif command in {"prompt", "compact-prompt"}:
        print(payload["prompt"], end="")
    elif command == "validate":
        _print_validate(payload)
    elif command == "dynamic":
        _print_dynamic(payload)
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
        print(f"- {edge['to']}{condition}")


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
    return f"{item_type}: {item.get('text')}"


if __name__ == "__main__":
    raise SystemExit(main())
