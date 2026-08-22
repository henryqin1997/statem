# TB3 v4p53 MVCC Obligation Baseline

## Result

- Job: `tb3-sol-evidence-v4p53-mvcc-obligation-baseline-k1-local-arm-a`
- Task: `terminal-bench/mvcc-lsm-compaction`
- Cell role: adapted matched negative-transfer baseline for v4p54
- Raw reward: **1.0**
- Reward validity: true
- Protocol validity: true
- Final StateM state: `handoff`
- Errors / retries: 0 / 0
- Model: GPT-5.6 Sol, max reasoning
- Codex: 0.148.0
- Input / cached / output tokens: 23,496,917 / 22,976,000 / 86,921
- API cost: **$16.700215**
- ATIF: v1.5, 274 steps
- Source manifest: 36 files, SHA256
  `368500101a75063cce16d0859883b5141f35aba2dc3e985fba725e18dee6c532`
- Raw-session paths: 0

This is an adapted sentinel result, not a fresh holdout or pass-rate estimate.
It establishes the frozen v4p53 side of the matched v4p54 ablation and shows
that the incumbent control still preserves a raw-positive MVCC outcome.

## Control Trace

The candidate-blind preflight returned `revise_plan` with five plan findings
and seven acceptance obligations. The v4p53 flow did not make resolution of
those plan findings a proposal prerequisite. Both bounded cycles therefore
followed the same high-level route:

1. solve and candidate-bound public replay;
2. independent falsification;
3. non-destructive revision;
4. second falsification;
5. quarantine after review-budget exhaustion;
6. final replay.

The final exported promotion decision was `revise` because acceptance
obligations remained unresolved or falsified and the falsifier was
inconclusive. Identity, provenance, contract preservation, reviewer-profile,
receipt, and protection checks were valid; there were no blocking regressions,
blocking contract violations, or hard contract gaps. The candidate was
quarantined as the exact evaluation target and ultimately passed the standard
verifier.

This is the intended v4p54 discriminator: make a candidate-blind
`revise_plan` mechanically actionable before proposal while preserving this raw
one. It does not prove v4p54 will help, and v4p54 must be rejected if its matched
candidate regresses reward or strands lifecycle state.

## Preservation

- Source / backup regular files: 149 / 149
- Source / backup bytes: 10,573,898 / 10,573,898
- Deterministic relative-path/content tree SHA256, both copies:
  `6bea7e15ab688473587b767767541095d49a3eaea03cb12b0a1308c8c718069d`
- `rsync -nrc --delete`: empty
- Exact launchd label: unloaded
- Experiment container: absent
