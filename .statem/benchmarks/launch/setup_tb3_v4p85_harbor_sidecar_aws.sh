#!/bin/bash
set -euo pipefail

harbor_commit="6ecebe4ae9910ee0b28a2e6e8fa30934c0b41dfa"
runtime_root="/home/ubuntu/harbor-v4p85-${harbor_commit:0:12}"
venv="$runtime_root/.venv"

mkdir -p "$runtime_root"
if [[ ! -x "$venv/bin/python" ]]; then
  python3 -m venv "$venv"
fi

"$venv/bin/python" -m pip install --disable-pip-version-check --upgrade pip
"$venv/bin/python" -m pip install --disable-pip-version-check \
  "git+https://github.com/harbor-framework/harbor.git@${harbor_commit}"

"$venv/bin/python" - <<'PY'
import importlib.metadata as metadata
import json
from harbor.models.task.config import ArtifactConfig

fields = sorted(ArtifactConfig.model_fields)
if "service" not in fields:
    raise SystemExit("isolated Harbor runtime does not model service artifacts")
print(json.dumps({
    "runtime": "harbor",
    "version": metadata.version("harbor"),
    "artifact_fields": fields,
    "service_supported": True,
}, separators=(",", ":")))
PY
