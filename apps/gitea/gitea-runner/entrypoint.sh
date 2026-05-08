#!/bin/bash
# Entrypoint for Gitea act_runner container.
# Registers the runner once, then starts the daemon.

set -euo pipefail

# Required environment variables:
#   GITEA_INSTANCE_URL               — URL of Gitea instance
#   GITEA_RUNNER_REGISTRATION_TOKEN  — registration token

if [ -z "${GITEA_INSTANCE_URL:-}" ]; then
  echo "ERROR: GITEA_INSTANCE_URL is not set." >&2
  exit 1
fi

if [ -z "${GITEA_RUNNER_REGISTRATION_TOKEN:-}" ]; then
  echo "ERROR: GITEA_RUNNER_REGISTRATION_TOKEN is not set." >&2
  exit 1
fi

# Register (once)
if [ ! -f /data/.runner ]; then
  echo "Registering runner with ${GITEA_INSTANCE_URL} ..."

  act_runner register \
    --config   /config.yaml \
    --instance "${GITEA_INSTANCE_URL}" \
    --token    "${GITEA_RUNNER_REGISTRATION_TOKEN}" \
    --name     "${GITEA_RUNNER_NAME:-gitea-runner}" \
    --labels   "${GITEA_RUNNER_LABELS:-self-hosted,linux:host}" \
    --no-interactive

  echo "Registration complete."
else
  echo "Runner already registered — skipping registration."
fi

# Start daemon
echo "Starting act_runner daemon ..."
exec act_runner daemon --config /config.yaml
