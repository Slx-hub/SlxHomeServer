#!/bin/bash
# Entrypoint for the Unity act_runner container.
# 1. Registers the runner with Gitea on first start (skipped if already registered).
# 2. Starts the act_runner daemon.
#
# Required environment variables (supply via .env / docker-compose):
#   GITEA_INSTANCE_URL               — URL of your Gitea instance
#   GITEA_RUNNER_REGISTRATION_TOKEN  — registration token from Gitea Settings → Actions → Runners

set -euo pipefail

# ── Discover and export UNITY_PATH ──────────────────────────────────────────
# Workflows expect UNITY_PATH to point to the Unity installation directory.
# GameCI images install Unity at an unpredictable version-specific location.
if [ -z "${UNITY_PATH:-}" ]; then
  UNITY_BIN=$(which unity-editor || true)
  if [ -n "$UNITY_BIN" ]; then
    export UNITY_PATH=$(dirname $(dirname "$UNITY_BIN"))
    echo "Discovered UNITY_PATH: ${UNITY_PATH}"
  else
    echo "WARNING: unity-editor not found in PATH" >&2
  fi
fi

# ── Validate required variables ──────────────────────────────────────────────
if [ -z "${GITEA_INSTANCE_URL:-}" ]; then
  echo "ERROR: GITEA_INSTANCE_URL is not set." >&2
  exit 1
fi
if [ -z "${GITEA_RUNNER_REGISTRATION_TOKEN:-}" ]; then
  echo "ERROR: GITEA_RUNNER_REGISTRATION_TOKEN is not set." >&2
  exit 1
fi

# ── Register (once) ──────────────────────────────────────────────────────────
# The .runner file is stored in the /data volume; it persists across container restarts.
if [ ! -f /data/.runner ]; then
  echo "Registering runner with ${GITEA_INSTANCE_URL} ..."

  act_runner register \
    --config   /config.yaml \
    --instance "${GITEA_INSTANCE_URL}" \
    --token    "${GITEA_RUNNER_REGISTRATION_TOKEN}" \
    --name     "${GITEA_RUNNER_NAME:-unity-runner}" \
    --labels   "${GITEA_RUNNER_LABELS:-self-hosted,unity-linux:host}" \
    --no-interactive

  echo "Registration complete."
else
  echo "Runner already registered — skipping registration."
fi

# ── Start daemon ─────────────────────────────────────────────────────────────
echo "Starting act_runner daemon ..."
exec act_runner daemon --config /config.yaml
