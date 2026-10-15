#!/usr/bin/env bash
# install.sh — One-command bootstrap installer for ai-orchestration & MCP bindings.
#
# Can be run:
#   1. From a local checkout: ./install.sh [--assistants kilo claude codex] [--with-mcp]
#   2. From scratch via curl: curl -fsSL https://raw.githubusercontent.com/primax79/ai-orchestration/main/install.sh | bash
set -euo pipefail

ASSISTANTS=("all")
SCOPE="global"
WITH_MCP=0
LINK_MODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --assistants)
      shift
      ASSISTANTS=()
      while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
        ASSISTANTS+=("$1")
        shift
      done
      ;;
    --scope)
      SCOPE="$2"
      shift 2
      ;;
    --with-mcp)
      WITH_MCP=1
      shift
      ;;
    --link)
      LINK_MODE="--link"
      shift
      ;;
    -h|--help)
      echo "Usage: ./install.sh [--assistants kilo claude codex | all] [--scope global|project] [--with-mcp] [--link]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/scripts/orchestration_env.py" ]]; then
  ORCH_ROOT="${SCRIPT_DIR}"
else
  ORCH_ROOT="${HOME}/.ai-orchestration/repos/ai-orchestration"
  mkdir -p "${HOME}/.ai-orchestration/repos"
  if [[ -d "${ORCH_ROOT}/.git" ]]; then
    git -C "${ORCH_ROOT}" pull --ff-only
  else
    git clone https://github.com/primax79/ai-orchestration.git "${ORCH_ROOT}"
  fi
fi

echo "==> [1/3] Initializing global ~/.config/ai-orchestration/orchestration.toml (if not present)..."
python3 "${ORCH_ROOT}/bin/ai-orch" config init-global

echo "==> [2/3] Installing ai-orchestration skills (${SCOPE}) for: ${ASSISTANTS[*]}..."
python3 "${ORCH_ROOT}/bin/ai-orch" env install-skills \
  --assistants "${ASSISTANTS[@]}" \
  --scope "${SCOPE}" \
  ${LINK_MODE}

if [[ "${WITH_MCP}" -eq 1 ]]; then
  echo "==> [3/3] Fetching and registering MCP servers (kilo-mcp, codex-mcp)..."
  python3 "${ORCH_ROOT}/bin/ai-orch" env fetch-repos --repos ai-orchestration kilo-mcp
  python3 "${ORCH_ROOT}/bin/ai-orch" env register-mcp kilo-mcp --assistants claude codex --scope "${SCOPE}" --provision-venv
  if command -v codex >/dev/null 2>&1; then
    python3 "${ORCH_ROOT}/bin/ai-orch" env register-mcp codex-mcp --assistants claude kilo --scope "${SCOPE}"
  fi
else
  echo "==> [3/3] Skipping MCP server registration (pass --with-mcp to also provision & register kilo-mcp / codex-mcp)."
fi

echo ""
echo "==> Environment Status Summary:"
python3 "${ORCH_ROOT}/bin/ai-orch" env status
