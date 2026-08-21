# TB3 public artifact gate

## Purpose

Some Terminal-Bench tasks declare multiple public deliverables, but a solver
can produce one plausible primary output while a secondary file, service-owned
state export, or artifact transaction is absent. Treating that situation as an
unconstrained semantic failure wastes a development cycle and makes reviewer
prose carry a check that Harbor can perform mechanically.

`integrations/harbor/experimental/tb3_public_artifact_gate.py` is a host-side
diagnostic gate. It consumes only a normalized list of public artifact
declarations, Harbor's submitted artifact manifest, and the submitted public
artifact root. It reports:

- missing or duplicate declared sources;
- non-`ok` export status;
- unsafe, absent, or empty destinations;
- undeclared extra sources as advisory context; and
- content digests for every successfully observed file or directory.

The receipt contains no machine-specific root path. It is therefore stable
across a checksum-identical remote source and local backup.

## Authority boundary

The gate proves artifact-harvest completeness only. It does not establish
scientific, compliance, numerical, or task-semantic correctness; rewrite raw
reward; inspect verifier output; authorize promotion; or add a retry. A failed
receipt narrows failure ownership and can become one candidate-blind acceptance
obligation in a development cell. It cannot become a task answer.

The control remains outside StateM core and outside the shared runbook. A
family may use it only when public metadata declares artifacts whose presence
is part of the task-visible submission boundary.

## First application

The checksum-verified Intrastat direct calibration declares three artifacts.
The gate matched all three, bound the reconciliation memo and supplied schema
by SHA-256, and classified the runtime-state export as failed. This reproduces
the manual public-artifact observation without importing hidden verifier
evidence. The receipt is preserved at
`.statem/benchmarks/analysis/artifact-gates/intrastat-meldung-direct-a.receipt.json`.

## Validation

- Four focused gate tests cover complete, failed-plus-extra, missing,
  duplicate, empty, unsafe-destination, and CLI fail-closed behavior.
- The combined artifact, admission, and score-gate suite has 14 passing tests.
