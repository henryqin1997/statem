#!/bin/zsh
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DOCKER_CONFIG="/private/tmp/docker-public-config"
export PYTHONPATH="/private/tmp/statem-tb3-v4p88-atrx-artifact-consistency"
export STATEM_HARBOR_BIN="/Users/qinziheng/workspace/statem/.venv/bin/harbor"
export STATEM_HARBOR_PYTHON="/Users/qinziheng/workspace/statem/.venv/bin/python"

repo="/private/tmp/statem-tb3-v4p88-atrx-artifact-consistency"
dataset_path="/private/tmp/tb3-v3.0.0-v4p87/terminal-bench"
task_path="$dataset_path/atrx-vep-crispr"
catalog="$repo/examples/tb3-thin-family-practices-v6.json"
job_name="${JOB_NAME:-tb3-sol-thin-family-v4p88-atrx-artifact-consistency-adapted-k1-local-arm-c}"
task_receipt="$repo/.statem/benchmarks/backups/prelaunch-receipts/v4p88-atrx-live-runtime-fields.json"
route_receipt="$repo/.statem/benchmarks/backups/prelaunch-receipts/v4p88-atrx-route.json"

for required in "$task_path/task.toml" "$task_path/environment/Dockerfile" "$task_path/tests/Dockerfile" "$catalog"; do
  [[ -f "$required" ]] || { printf 'missing frozen input: %s\n' "$required" >&2; exit 66; }
done

cd "$repo"

exec /Users/qinziheng/workspace/statem/.venv/bin/python \
  .statem/benchmarks/run_harbor_batch.py \
  --dataset terminal-bench/terminal-bench@3.0.0 \
  --dataset-path "$dataset_path" \
  --task terminal-bench/atrx-vep-crispr \
  --job-name "$job_name" \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --agent-name ziheng-yaxin-statem-codex-thin-family-v4p88-exp \
  --agent-import-path integrations.harbor.statem_codex_thin_family_v4p88_exp:ThinFamilyV4p88ExperimentalStatemCodex \
  --agent-kwarg activation_mode=active \
  --agent-kwarg development_practice_id=bio_variant_design_consistency \
  --agent-kwarg practice_catalog_path="$catalog" \
  --agent-kwarg version=0.149.1 \
  --environment docker \
  --auth-mode auth-json \
  --codex-auth-json /Users/qinziheng/.codex/auth.json \
  --no-statem-agent-env \
  --agent-env STATEM_STOP_REQUIRE_STATE_HOOKS=true \
  --agent-env STATEM_AGENT_DEADLINE_SECONDS=17400 \
  --agent-env STATEM_HANDOFF_BUFFER_SECONDS=300 \
  --concurrency 1 \
  --attempts 1 \
  --max-retries 0 \
  --no-retry-agent-timeouts \
  --environment-build-timeout-multiplier 1.0 \
  --timeout-multiplier 1.0 \
  --wall-timeout-seconds 21600 \
  --prelaunch-expected-practice bio_variant_design_consistency \
  --prelaunch-practice-catalog "$catalog" \
  --prelaunch-route-receipt "$route_receipt" \
  --prelaunch-task-field-receipt "$task_receipt" \
  "$@"
