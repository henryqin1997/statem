#!/bin/zsh
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DOCKER_CONFIG="/private/tmp/statem-public-docker-config"

cd /Users/qinziheng/workspace/statem

exec .venv/bin/python .statem/benchmarks/run_harbor_batch.py \
  --dataset terminal-bench/terminal-bench@3.0.0 \
  --dataset-path /private/tmp/tb3-v3.0.0-full/terminal-bench \
  --task terminal-bench/html-js-filter \
  --job-name tb3-sol-evidence-v4p36-html-js-lifecycle-k1-local-b \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --agent-name ziheng-yaxin-statem-codex-evidence-develop-v4p36-exp \
  --agent-import-path integrations.harbor.statem_codex_multirole_develop_exp:EvidenceDevelopV4p36ExperimentalStatemCodex \
  --environment docker \
  --auth-mode auth-json \
  --codex-auth-json /private/tmp/codex-harbor-auth-20260818/auth.json \
  --concurrency 1 \
  --attempts 1 \
  --max-retries 0 \
  --no-retry-agent-timeouts \
  --environment-build-timeout-multiplier 1.0 \
  --timeout-multiplier 2.0 \
  --wall-timeout-seconds 28800 \
  --agent-env STATEM_STOP_REQUIRE_STATE_HOOKS=true \
  --agent-env STATEM_STOP_MAX_CONTINUATIONS_PER_ENTRY=2 \
  --agent-env STATEM_DEVELOP_MAX_CYCLES=2 \
  --agent-env STATEM_DEVELOP_MAX_REVIEWS=2 \
  "$@"
