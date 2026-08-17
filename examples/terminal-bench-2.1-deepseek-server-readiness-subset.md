# Terminal-Bench 2.1 DeepSeek server-readiness subset

This public subset extracts one family from the StateM DeepSeek policy-v9
evaluation configuration: `server_readiness`, represented by the production
lens id `service_lifecycle_readiness`.

It contains only:

- the three task-visible trigger groups that must all match;
- the exact selected-state, instruction, limits, and receipt fields;
- the matching receipt validator; and
- the no-match behavior, which leaves the frozen base runbook unchanged.

It intentionally excludes every other DeepSeek route, selector, reviewer
practice, task name, benchmark solution, provider setting, and credential. It
is a policy extract, not a replacement for the generic StateM/Harbor harness.

## Files

- `terminal-bench-2.1-deepseek-server-readiness-subset.yaml` is the auditable
  runbook extract.
- `integrations/harbor/experimental/deepseek_server_readiness_subset.py`
  selects, renders, templates, and validates the extract.
- `tests/test_deepseek_server_readiness_subset.py` checks positive and negative
  boundaries without the full policy. When the private adapter is present, it
  also checks exact equivalence with the corresponding policy-v9 family.

The helper uses StateM's bundled minimal YAML parser and is tested under
`python -S`; installing PyYAML is not required inside the StateM repository.

The runtime paths in the YAML preserve the evaluated deployment contract under
`/tmp/statem-verification-checks`. For standalone use from this repository, use
the module commands below. The public validator binds the policy version,
selection basis, state, limits, instruction, and required receipt fields back
to the runbook before accepting evidence, so a modified selection cannot weaken
the receipt contract.

## Verify

Run the equivalence and boundary tests:

```bash
python3 -m unittest tests.test_deepseek_server_readiness_subset -v
```

Select the family from a task-visible prompt file:

```bash
python3 -m integrations.harbor.experimental.deepseek_server_readiness_subset \
  --runbook examples/terminal-bench-2.1-deepseek-server-readiness-subset.yaml \
  select --task-text task.txt > selection.json
```

Validate a completed selection and receipt:

```bash
python3 -m integrations.harbor.experimental.deepseek_server_readiness_subset \
  --runbook examples/terminal-bench-2.1-deepseek-server-readiness-subset.yaml \
  validate --selection selection.json --receipt receipt.json
```

Selection is conjunctive: a visible task must describe a service/process, a
public client surface, and persistent lifetime. A one-shot server used only
during a public test does not trigger this family.
