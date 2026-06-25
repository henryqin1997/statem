# statem Stop Hook Auto Loop

These snippets register an opt-in host `Stop` hook that keeps an unfinished
statem run moving after the agent would otherwise hand control back to the user.

## Register

Use one of the JSON snippets in this directory and adjust the command path if
the hook is registered outside the statem repository:

```json
"command": "python3 /Users/qinziheng/workspace/statem/integrations/hooks/statem_stop_hook.py"
```

For Codex, merge `codex-stop-autoloop.hooks.json` into a Codex `hooks.json`
file such as `<repo>/.codex/hooks.json` or `~/.codex/hooks.json`.

For Claude Code, merge `claude-stop-autoloop.settings.json` into a Claude Code
settings file such as `.claude/settings.json`, `.claude/settings.local.json`, or
`~/.claude/settings.json`.

## Behavior

The hook reads the active `.statem` run. If the current node has outgoing
transitions and is not a terminal node, it returns:

```json
{"decision": "block", "reason": "Continue the active statem-managed run..."}
```

Hosts interpret that as a continuation prompt. The hook does not advance state,
does not run `/clear`, and does not run `/compact`.

It allows the stop when:

- there is no active statem run
- the host says `stop_hook_active` is true
- the current node has no outgoing transitions
- the current node is one of `handoff`, `done`, `complete`, `completed`, or
  `finished`

Configure terminal names with `STATEM_AUTOLOOP_STOP_STATES`, the statem command
with `STATEM_COMMAND`, and the state directory with `STATEM_STATE_DIR`.
