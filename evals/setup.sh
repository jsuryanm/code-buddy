#!/usr/bin/env bash
# Builds .venv-evals for the RAGAS runner: the project and its locked versions (uv.lock) plus
# ragas. ragas cannot join the main lock without downgrading openai (docs/evaluation.md).
#   bash evals/setup.sh
#   .venv-evals/bin/python -m codebuddy.eval.ragas_run --index sample --limit 3
set -euo pipefail
cd "$(dirname "$0")/.."
uv venv --allow-existing --python 3.12 .venv-evals
uv export --frozen --all-extras --no-dev --no-hashes --no-emit-project \
  -o .venv-evals/constraints.txt >/dev/null
VIRTUAL_ENV=.venv-evals uv pip install -e ".[trace]" -r evals/requirements.txt \
  -c .venv-evals/constraints.txt --overrides evals/overrides.txt
echo "Ready: .venv-evals/bin/python -m codebuddy.eval.ragas_run --help"
