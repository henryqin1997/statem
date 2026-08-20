# TB3 HTML/JS v4p31 extended diagnostic

## Cell identity

- Job: `tb3-sol-evidence-v4p31-html-js-failure-closure-k1-local-a`
- Task: `terminal-bench/html-js-filter`
- Role: adapted extended-time development diagnostic; excluded from fresh score
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p31-exp`
- Model: GPT-5.6 Sol, max reasoning
- Codex: `0.148.0`
- Source manifest: 35 files,
  `fec076d27f28e2699cff76240073dc682615549c30136bb94a9e284704de413b`
- Route: `structured-transformation` / `parsing-transformation`

## Raw and protocol result

- Raw reward: unavailable; verifier did not run.
- Protocol validity: invalid. Collection found final StateM state `solve`
  instead of required `handoff`.
- Wall time: about 80 minutes.
- Session resumes: 2.
- Tokens: 847,323 input, 831,744 cached input, 2,475 output.
- API cost: $0.568017.
- Trajectory: ATIF-v1.5, 262 steps.
- Raw Codex session directories retained: 0.

Reward validity and protocol validity are therefore both false. This cell must
not be treated as a zero reward or included in a pass-rate denominator.

## Attribution

The first complete candidate cycle produced a valid `revise` decision. The
reviewer bound one executable-content bypass and two selective-preservation
failures to the submitted candidate. The failure-closure gate attributed these
to an implementation defect owned by the lead solver and authorized one
append-only validation delta that preserved all prior obligations.

The second cycle opened and carried the prior failure ownership and proposed
validation delta into its retry brief. It did not reach a new sealed preflight
or candidate. The v4p31 adapter then consumed both session-resume allowances
because the StateM node and entry remained `solve`, even though implementation
or milestone progress inside that entry was the intended next operation.

This provides two separate pieces of useful evidence:

1. **Implementation owner:** the task has a concrete, publicly reproducible
   repair hypothesis and a candidate-blind regression delta. It is not yet
   evidence of a solved task.
2. **Lifecycle owner:** node/entry identity alone is too coarse for long solve
   stages. The v4p32 metadata-and-receipt progress witness is the owning generic
   repair.

The diagnostic therefore made substantive development progress under the
phase-1 queue rule, but another v4p31 attempt would be redundant. Any later
HTML/JS revisit must use v4p32 or newer and remains adapted for this control.

## Preservation

- Source and local backup: 106 regular files, 5,718,731 bytes.
- Deterministic relative-path tree SHA256:
  `d661ad65b60f983b771c9c299d5a2ad33899b0c956eae86b1c15299acc7c37b6`
- Backup:
  `.statem/benchmarks/backups/tb3-sol-evidence-v4p31-html-js-failure-closure-k1-local-a`
- Exact launchd label unloaded; experiment container absent.
