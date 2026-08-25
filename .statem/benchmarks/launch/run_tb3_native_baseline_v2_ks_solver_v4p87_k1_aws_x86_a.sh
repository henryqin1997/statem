#!/bin/bash
set -euo pipefail

export PATH="/home/ubuntu/statem/.venv/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONPATH="/home/ubuntu/statem-tb3-v4p79"
export STATEM_HARBOR_BIN="/home/ubuntu/statem/.venv/bin/harbor"
export STATEM_HARBOR_PYTHON="/home/ubuntu/statem/.venv/bin/python"

dataset_path="/home/ubuntu/tb3-v3.0.0-full/terminal-bench"
task_path="$dataset_path/ks-solver-cpp"
for required in "$task_path/task.toml" "$task_path/environment/Dockerfile" "$task_path/tests/Dockerfile"; do
  [[ -f "$required" ]] || { printf 'missing frozen task definition: %s\n' "$required" >&2; exit 66; }
done

cd /home/ubuntu/statem-tb3-v4p79
job_name="${JOB_NAME:-tb3-sol-native-baseline-v2-ks-solver-v4p87-k1-aws-x86-a}"

exec /home/ubuntu/statem/.venv/bin/python .statem/benchmarks/run_harbor_batch.py \
  --dataset terminal-bench/terminal-bench@3.0.0 \
  --dataset-path "$dataset_path" \
  --task terminal-bench/ks-solver-cpp \
  --job-name "$job_name" \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --agent-name codex-auth-no-session-baseline-v2 \
  --agent-import-path integrations.harbor.codex_auth_no_session_baseline:AuthNoSessionCodex \
  --agent-kwarg version=0.149.1 \
  --environment docker \
  --auth-mode auth-json \
  --codex-auth-json /home/ubuntu/.codex/auth.json \
  --no-statem-agent-env \
  --concurrency 1 \
  --attempts 1 \
  --max-retries 0 \
  --no-retry-agent-timeouts \
  --environment-build-timeout-multiplier 1.0 \
  --timeout-multiplier 1.0 \
  --wall-timeout-seconds 18000 \
  --prelaunch-task-field-receipt .statem/benchmarks/backups/prelaunch-receipts/v4p87-ks-live-runtime-fields.json \
  "$@"
