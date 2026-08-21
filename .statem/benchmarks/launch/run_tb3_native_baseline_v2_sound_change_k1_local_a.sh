#!/bin/zsh
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DOCKER_CONFIG="/private/tmp/statem-public-docker-config"

cd /Users/qinziheng/workspace/statem

exec .venv/bin/python .statem/benchmarks/run_harbor_batch.py \
  --dataset terminal-bench/terminal-bench@3.0.0 \
  --dataset-path /private/tmp/tb3-v3.0.0-full/terminal-bench \
  --task terminal-bench/sound-change-cascade \
  --job-name tb3-sol-native-baseline-v2-sound-change-cascade-k1-local-arm-a \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --agent-name codex-auth-no-session-baseline-v2 \
  --agent-import-path integrations.harbor.codex_auth_no_session_baseline:AuthNoSessionCodex \
  --agent-kwarg version=0.148.0 \
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
  --wall-timeout-seconds 21600
