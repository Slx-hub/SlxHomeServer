#!/bin/bash
# Entrypoint for GitHub Actions self-hosted runner container.
# Handles registration (once) and starts the runner daemon.
# Supports both GitHub.com and Gitea instances.

set -euo pipefail

# Required environment variables:
#   GITHUB_REPOSITORY    — repo path (e.g., owner/repo)
#   GITHUB_TOKEN         — registration token
#   GITHUB_SERVER_URL    — base URL (optional; defaults to https://github.com)

if [ -z "${GITHUB_REPOSITORY:-}" ]; then
  echo "ERROR: GITHUB_REPOSITORY is not set." >&2
  exit 1
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "ERROR: GITHUB_TOKEN is not set." >&2
  exit 1
fi

# Default to GitHub.com if not specified
GITHUB_SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"

# Check if already registered
if [ ! -f /data/.registered ]; then
  echo "Configuring GitHub Actions runner for ${GITHUB_REPOSITORY} at ${GITHUB_SERVER_URL} ..."
  
  cd /home/runner
  
  # Configure the runner (once, unattended)
  ./config.sh \
    --url "${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}" \
    --token "${GITHUB_TOKEN}" \
    --name "${RUNNER_NAME:-github-runner}" \
    --labels "${RUNNER_LABELS:-self-hosted,linux}" \
    --work _work \
    --unattended \
    --replace
  
  # Mark as registered
  touch /data/.registered
  echo "Runner configuration complete."
else
  echo "Runner already configured — skipping registration."
fi

# Start the runner as a daemon
echo "Starting GitHub Actions runner ..."
cd /home/runner
exec ./run.sh
