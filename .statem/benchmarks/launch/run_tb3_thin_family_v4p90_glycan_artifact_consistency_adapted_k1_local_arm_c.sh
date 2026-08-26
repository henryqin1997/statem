#!/bin/zsh
set -euo pipefail

repo="/private/tmp/statem-tb3-v4p90-scoped-three-stage"
base_repo="/Users/qinziheng/workspace/statem"
dataset_path="/private/tmp/tb3-v3.0.0-preflight/terminal-bench"
catalog="$repo/examples/tb3-thin-family-practices-v7.json"
history_index="$repo/.statem/benchmarks/backups/prelaunch-history/tb3-completed-v4p90.json"
receipt_root="$base_repo/.statem/benchmarks/backups/prelaunch-receipts"
job_name="${JOB_NAME:-tb3-sol-thin-family-v4p90-glycan-artifact-consistency-adapted-k1-local-arm-c}"

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DOCKER_CONFIG="/private/tmp/docker-public-config"
export PYTHONPATH="$repo"
export STATEM_HARBOR_BIN="$base_repo/.venv/bin/harbor"
export STATEM_HARBOR_PYTHON="$base_repo/.venv/bin/python"

for required in \
  "$dataset_path/glycan-ms2-elucidation/task.toml" \
  "$dataset_path/glycan-ms2-elucidation/environment/Dockerfile" \
  "$dataset_path/glycan-ms2-elucidation/tests/Dockerfile" \
  "$catalog" \
  "$history_index"; do
  [[ -f "$required" ]] || { printf 'missing frozen input: %s\n' "$required" >&2; exit 66; }
done

cd "$repo"

exec "$base_repo/.venv/bin/python" \
  .statem/benchmarks/run_harbor_batch.py \
  --dataset terminal-bench/terminal-bench@3.0.0 \
  --dataset-path "$dataset_path" \
  --task terminal-bench/glycan-ms2-elucidation \
  --job-name "$job_name" \
  --jobs-dir "$base_repo/.statem/benchmarks/jobs" \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --agent-name ziheng-yaxin-statem-codex-thin-family-v4p90-exp \
  --agent-import-path integrations.harbor.statem_codex_thin_family_v4p90_exp:ThinFamilyV4p90ExperimentalStatemCodex \
  --agent-kwarg activation_mode=active \
  --agent-kwarg development_practice_id=bioanalytical_artifact_consistency \
  --agent-kwarg practice_catalog_path="$catalog" \
  --agent-kwarg version=0.149.1 \
  --environment docker \
  --auth-mode auth-json \
  --codex-auth-json /Users/qinziheng/.codex/auth.json \
  --no-statem-agent-env \
  --agent-env STATEM_STOP_REQUIRE_STATE_HOOKS=true \
  --agent-env STATEM_AGENT_DEADLINE_SECONDS=8400 \
  --agent-env STATEM_HANDOFF_BUFFER_SECONDS=300 \
  --concurrency 1 \
  --attempts 1 \
  --max-retries 0 \
  --no-retry-agent-timeouts \
  --environment-build-timeout-multiplier 1.0 \
  --timeout-multiplier 1.0 \
  --wall-timeout-seconds 21600 \
  --prelaunch-expected-practice bioanalytical_artifact_consistency \
  --prelaunch-practice-catalog "$catalog" \
  --prelaunch-route-receipt "$receipt_root/v4p90-glycan-route.json" \
  --prelaunch-history-index "$history_index" \
  --prelaunch-evidence-class adapted \
  --prelaunch-history-receipt "$receipt_root/v4p90-glycan-history.json" \
  --prelaunch-task-field-check \
  --prelaunch-task-field-receipt "$receipt_root/v4p90-glycan-runtime-fields.json" \
  "$@"
