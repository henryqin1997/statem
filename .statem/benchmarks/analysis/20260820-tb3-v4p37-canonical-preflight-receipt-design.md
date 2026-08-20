# TB3 v4p37 canonical preflight receipt repair

## Failure owner

Two independent v4p36 cells reached `falsify` with a bound candidate and public
acceptance replay, then failed before TeamRun initialization. The canonical
producer emitted a version-1 `plan_preflight_evidence` receipt. Proposal binding
and preflight validation accepted that kind, but falsifier-task,
acceptance-obligation adjudication, and promotion still required the obsolete
kind `preflight_evidence`.

This is a mechanical receipt-consumer mismatch. It is not reviewer semantic
counterevidence, a task-agent capability ceiling, or a reason to loosen the
promotion gate.

## Minimal repair

- Keep `plan_preflight_evidence` as the sole canonical kind.
- Require that exact kind in all three downstream consumers.
- Give the repaired adapter the independent identity
  `ziheng-yaxin-statem-codex-evidence-develop-v4p37-exp`.
- Inherit the v4p36 runbook and all contract, review, promotion, deadline, and
  recovery semantics unchanged.

## Validation

- Focused review/recovery suite: 94 tests passed.
- Strict v4p35 runbook validation: passed; v4p37 inherits that runbook.
- Full suite: 720 tests run, 11 skipped, one known unrelated failure in the
  isolated git-webserver-family test because its temporary subprocess cannot
  import the local `statem` package.
- Canonical source manifest: 35 files,
  `d86bd75ed48702ff8313d1fdde2aba583e9970556fdcbb4360a93f6279190897`.

## Promotion rule

v4p37 remains unpromoted. It must first complete a protocol-valid k1 risk
sentinel with raw reward 1.0. Only then may the pending matched
data-anonymization StateM half be admitted. Fresh family evidence and matched k5
risk evidence remain necessary for score claims.
