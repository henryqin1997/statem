# Terminal-Bench 2.1 `git_webserver_deploy` family

This is an executable, single-family StateM/Harbor package for external
reproduction. It is the family used by tasks whose visible contract joins all
four surfaces below:

1. clone a named bare repository over SSH;
2. create and commit exact file content;
3. push a named branch; and
4. observe that pushed content through an HTTP URL.

The canonical positive contract is `configure-git-webserver`. A normal HTTP
server, a bare Git server without HTTP deployment, QEMU over SSH, repository
sanitization, or a local Git-to-web copy does not select this family.

This is deliberately narrower than `server_readiness` /
`service_lifecycle_readiness`. The latter checks durable service lifetime and
a fresh public client. This family checks the Git-over-SSH -> push/deploy ->
HTTP consumer chain and therefore uses a different route and fixed gate.

## Package boundary

- `terminal-bench-2.1-git-webserver-deploy-family.yaml` is the executable
  StateM graph.
- `integrations/harbor/experimental/git_webserver_deploy_family.py` owns the
  task-visible selector, reviewer practice, contract/review schemas, immutable
  selection validation, fixed end-to-end gate, stateful gate receipt,
  lightweight freshness validation, and deadline predicates. It uses only the
  Python standard library.
- `integrations/harbor/statem_codex_git_webserver_deploy.py` supplies generic
  and DeepSeek Harbor adapters. It subclasses Harbor's public `Codex` adapter
  directly. It does not import the unpublished repository-local `StatemCodex`.
- The complete runtime source manifest contains nine files: the five StateM
  Python files already present on published `main`, this graph, the
  self-contained family helper, the published stop hook, and this adapter.
  The gate and deadline implementation live in the helper rather than in
  unpublished `git_webserver_deploy_check.py` or `deadline_status.py` modules.
- `tests/test_git_webserver_deploy_family.py` contains the public prompt,
  near-match controls, tamper tests, receipt tests, graph validation, and
  a clean-published-`main` isolation test.

The broad selector, gate catalog, other family practices, benchmark answers,
task IDs, provider credentials, and private policy overlays are absent. The
DeepSeek adapter stages provider configuration into the trial but does not add
it to the StateM source manifest or collected StateM artifacts.

## Workflow

The graph preserves the configurable thin-runbook structure:

```text
direct_solve -> task_contract_check -> self_review
                                      | clean/needs evidence + exact match
                                      v
                              family_evidence_check -> handoff
                                      |
                                      v
                                    repair -> task_contract_check
```

Family practice is not shown during the initial solve or visible-contract
check. It enters only at `self_review`. A selected task cannot normally hand
off without a passed, fresh fixed-gate receipt. The gate executes once on entry
to `family_evidence_check`; final handoff checks repository-ref and HTTP-body
freshness without rerunning the stateful push sequence. A separate
`deadline_handoff` preserves the best runnable candidate only when the official
deadline reserve is actually due.

The generic adapter remains configurable through `runbook_path`; this family
graph is its default so independent runs use the same control surface. It does
not depend on another repository-local Harbor adapter or unpublished StateM
fields.

## Validate locally

No provider access or benchmark run is needed for route validation:

```bash
python3 -m statem validate \
  examples/terminal-bench-2.1-git-webserver-deploy-family.yaml --json

python3 -m unittest tests.test_git_webserver_deploy_family -v
```

The helper is also exercised under `python -S`, so routing does not depend on
PyYAML or another site package. The isolation test builds `git archive HEAD`,
adds only the three new family package files, and verifies graph validation,
routing, and adapter import from that clean tree.

Expected route matrix:

| Visible contract | Selected route |
|---|---|
| SSH clone + exact file + Git push + HTTP fetch | `git_webserver_deploy` |
| Long-lived HTTP server only | no family route |
| SSH-accessible bare repository only | no family route |
| Local Git deployment without SSH remote | no family route |
| QEMU/SSH readiness | no family route |
| Git history sanitization | no family route |

## Reproduce with DeepSeek

Install Harbor with this checkout available to its tool environment:

```bash
uv tool install harbor --with-editable .
```

Generate a DeepSeek Codex provider directory containing `config.toml` and
`models.json`. Keep the bearer token outside version control. Then run one
local, no-upload trial:

```bash
harbor run \
  --dataset terminal-bench/terminal-bench@2.1 \
  --include-task-name configure-git-webserver \
  --job-name reproduce-git-webserver-deploy-family-k1 \
  --model deepseek-v4-flash \
  --agent-import-path integrations.harbor.statem_codex_git_webserver_deploy:DeepSeekGitWebserverDeployFamilyStatemCodex \
  --agent-kwarg deepseek_config_home=/absolute/path/to/deepseek-codex-config \
  --agent-kwarg reasoning_effort=max \
  --env docker \
  --n-concurrent 1 \
  --n-attempts 1 \
  --max-retries 0 \
  --timeout-multiplier 1.0 \
  --environment-build-timeout-multiplier 1.0 \
  --yes
```

The adapter pins Codex CLI `0.146.0` and defaults its internal agent deadline
to 900 seconds. Override that only with a disclosed
`--agent-kwarg agent_deadline_seconds=...`. The command intentionally omits
`--upload`. Record the dataset version, model, reasoning effort, timeout policy,
source-manifest hash, route selection, final StateM state, raw reward, tokens,
and cost when comparing an independent result.

For a non-DeepSeek Codex-compatible model or ChatGPT auth, use
`GitWebserverDeployFamilyStatemCodex` as the import class and the corresponding
runner auth mode. The family logic and source allowlist remain identical.
