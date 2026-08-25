#!/bin/zsh
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DOCKER_CONFIG="/private/tmp/docker-public-config"
export PYTHONPATH="/private/tmp/statem-tb3-v4p79-prelaunch-route-check"
export STATEM_HARBOR_BIN="/Users/qinziheng/workspace/statem/.venv/bin/harbor"
export STATEM_HARBOR_PYTHON="/Users/qinziheng/workspace/statem/.venv/bin/python"

dataset_path="/private/tmp/tb3-v3.0.0-v4p87/terminal-bench"
task_path="$dataset_path/atrx-vep-crispr"
for required in "$task_path/task.toml" "$task_path/environment/Dockerfile" "$task_path/tests/Dockerfile"; do
  [[ -f "$required" ]] || { printf 'missing frozen task definition: %s\n' "$required" >&2; exit 66; }
done

cd /private/tmp/statem-tb3-v4p79-prelaunch-route-check
job_name="${JOB_NAME:-tb3-sol-native-baseline-v2-atrx-vep-v4p87-k1-local-arm-c}"

exec /Users/qinziheng/workspace/statem/.venv/bin/python \
  .statem/benchmarks/run_harbor_batch.py \
  --dataset terminal-bench/terminal-bench@3.0.0 \
  --dataset-path "$dataset_path" \
  --task terminal-bench/atrx-vep-crispr \
  --job-name "$job_name" \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --agent-name codex-auth-no-session-baseline-v2 \
  --agent-import-path integrations.harbor.codex_auth_no_session_baseline:AuthNoSessionCodex \
  --agent-kwarg version=0.149.1 \
  --environment docker \
  --auth-mode auth-json \
  --codex-auth-json /Users/qinziheng/.codex/auth.json \
  --no-statem-agent-env \
  --concurrency 1 \
  --attempts 1 \
  --max-retries 0 \
  --no-retry-agent-timeouts \
  --environment-build-timeout-multiplier 1.0 \
  --timeout-multiplier 1.0 \
  --wall-timeout-seconds 21600 \
  --prelaunch-task-field-receipt .statem/benchmarks/backups/prelaunch-receipts/v4p87-atrx-live-runtime-fields.json \
  "$@"
