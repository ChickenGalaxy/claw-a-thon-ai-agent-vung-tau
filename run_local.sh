#!/usr/bin/env bash
# Local launcher for the Claw-a-thon AI Agent (Vung Tau)
# Runs inside your existing environment "env-ai".
# Usage:  bash run_local.sh
set -euo pipefail

cd "$(dirname "$0")"

ENV_NAME="env-ai"

activate_env() {
  # 1) Conda / Mamba environment named env-ai
  if command -v conda >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    source "$(conda info --base)/etc/profile.d/conda.sh"
    if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
      echo "Activating conda env: $ENV_NAME"
      conda activate "$ENV_NAME"
      return 0
    fi
  fi

  # 2) A venv directory named env-ai (in repo or home)
  for p in "./$ENV_NAME" "$HOME/$ENV_NAME" "$HOME/.virtualenvs/$ENV_NAME"; do
    if [ -f "$p/bin/activate" ]; then
      echo "Activating venv at: $p"
      # shellcheck disable=SC1091
      source "$p/bin/activate"
      return 0
    fi
  done

  echo "ERROR: Could not find environment '$ENV_NAME' (not a conda env, and no venv folder found)."
  echo "       If it's a conda env, run:  conda activate $ENV_NAME  &&  python main.py"
  echo "       If it lives elsewhere, edit ENV_NAME / paths in this script."
  exit 1
}

activate_env

echo "Using: $(python --version 2>&1)  ->  $(which python)"

# Install any missing dependencies into env-ai (skips if already present)
if ! python -c "import greennode_agentbase" >/dev/null 2>&1; then
  echo "Installing dependencies into $ENV_NAME (first run)..."
  pip install -r requirements.txt
else
  echo "Dependencies already present in $ENV_NAME."
fi

# Ensure .env exists
if [ ! -f ".env" ]; then
  echo "WARNING: .env not found. Copying from .env.example — fill in LLM_API_KEY etc."
  cp .env.example .env
fi

echo ""
echo "============================================================"
echo "  Starting agent...  Open:  http://localhost:8080"
echo "  Press Ctrl+C to stop."
echo "============================================================"
echo ""

python main.py
