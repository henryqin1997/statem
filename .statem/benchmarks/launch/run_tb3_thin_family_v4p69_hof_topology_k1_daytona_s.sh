#!/bin/zsh
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONPATH="/private/tmp/statem-tb3-v4p69-hof-daytona"
export STATEM_HARBOR_BIN="/Users/qinziheng/workspace/statem/.venv/bin/harbor"

dataset_path="/Users/qinziheng/workspace/statem/.statem/benchmarks/datasets/tb3-v3.0.0-persistent/terminal-bench"
task_path="$dataset_path/hof-topology-interpenetration"
for required in \
  "$task_path/task.toml" \
  "$task_path/environment/Dockerfile" \
  "$task_path/tests/Dockerfile"; do
  if [[ ! -f "$required" ]]; then
    print -u2 "missing frozen task definition: $required"
    exit 66
  fi
done

cd /private/tmp/statem-tb3-v4p69-hof-daytona

exec /Users/qinziheng/workspace/statem/.venv/bin/python \
  .statem/benchmarks/run_harbor_batch.py \
  --dataset terminal-bench/terminal-bench@3.0.0 \
  --dataset-path "$dataset_path" \
  --task terminal-bench/hof-topology-interpenetration \
  --job-name tb3-sol-thin-family-v4p69-hof-topology-k1-daytona-s \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --agent-name ziheng-yaxin-statem-codex-thin-family-v4p69-exp \
  --agent-import-path integrations.harbor.statem_codex_thin_family_v4p69_exp:ThinFamilyV4p69ExperimentalStatemCodex \
  --agent-kwarg activation_mode=active \
  --environment daytona \
  --env-file /Users/qinziheng/workspace/statem/.statem/benchmarks/daytona.env \
  --auth-mode auth-json \
  --codex-auth-json /Users/qinziheng/.codex/auth.json \
  --concurrency 1 \
  --attempts 1 \
  --max-retries 0 \
  --no-retry-agent-timeouts \
  --no-statem-agent-env \
  --environment-build-timeout-multiplier 1.0 \
  --timeout-multiplier 1.0 \
  --wall-timeout-seconds 14000 \
  --agent-env STATEM_STOP_REQUIRE_STATE_HOOKS=true \
  --agent-env STATEM_AGENT_DEADLINE_SECONDS=8400 \
  "$@"
