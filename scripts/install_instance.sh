#!/usr/bin/env bash
set -euo pipefail

INSTANCE_ID="${1:-}"
PRODUCT="${2:-}"
REPO_URL="${3:-}"
RUNTIME_ROOT="${4:-/home/wwwroot/openclaw-hire/runtime}"

if [[ -z "$INSTANCE_ID" || -z "$PRODUCT" || -z "$REPO_URL" ]]; then
  echo "Usage: install_instance.sh <instance_id> <product> <repo_url> [runtime_root]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

case "$PRODUCT" in
  zylos)
    exec "$SCRIPT_DIR/install_zylos_instance.sh" "$INSTANCE_ID" "$PRODUCT" "$REPO_URL" "$RUNTIME_ROOT"
    ;;
  openclaw)
    exec "$SCRIPT_DIR/install_openclaw_instance.sh" "$INSTANCE_ID" "$PRODUCT" "$REPO_URL" "$RUNTIME_ROOT"
    ;;
  hermes)
    exec "$SCRIPT_DIR/install_hermes_instance.sh" "$INSTANCE_ID" "$PRODUCT" "$REPO_URL" "$RUNTIME_ROOT"
    ;;
  *)
    echo "ERROR: unsupported product '$PRODUCT'" >&2
    exit 3
    ;;
esac
