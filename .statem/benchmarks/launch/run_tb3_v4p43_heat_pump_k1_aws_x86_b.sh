#!/bin/bash
set -euo pipefail

export PATH="/home/ubuntu/statem/.venv/bin:/usr/local/bin:/usr/bin:/bin"
export STATEM_AGENT_DEADLINE_SECONDS=750
cd /home/ubuntu/statem

exec .venv/bin/python .statem/benchmarks/run_harbor_batch.py \
  --dataset terminal-bench/terminal-bench@3.0.0 \
  --dataset-path /home/ubuntu/tb3-v3.0.0-full/terminal-bench \
  --task terminal-bench/heat-pump-warranty \
  --job-name tb3-sol-evidence-v4p43-heat-pump-bounded-failure-k1-aws-x86-b \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --agent-name ziheng-yaxin-statem-codex-evidence-develop-v4p43-exp \
  --agent-import-path integrations.harbor.statem_codex_multirole_develop_exp:EvidenceDevelopV4p43ExperimentalStatemCodex \
  --environment docker \
  --auth-mode auth-json \
  --codex-auth-json /home/ubuntu/.codex/auth.json \
  --concurrency 1 \
  --attempts 1 \
  --max-retries 0 \
  --no-retry-agent-timeouts \
  --environment-build-timeout-multiplier 1.0 \
  --timeout-multiplier 1.0 \
  --wall-timeout-seconds 10800
