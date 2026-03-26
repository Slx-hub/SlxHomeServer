#!/bin/bash
# Bootstrap Beszel monitoring — run once to link the hub and agent.
#
# The hub must be running and reachable before the agent can be started,
# because Beszel generates a KEY in the UI that the agent needs to accept
# connections from the hub.
#
# Usage: bash setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_ENV="$(cd "$SCRIPT_DIR/../../.." && pwd)/.env"

if [[ ! -f "$ROOT_ENV" ]]; then
    echo "ERROR: .env not found at $ROOT_ENV" >&2
    echo "  Copy .env.example to .env and fill in values first." >&2
    exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Beszel monitoring setup"
echo "════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Start the hub ─────────────────────────────────────────────────────
echo "Step 1 — Starting Beszel hub..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d beszel
echo ""
echo "Hub is up. Now do the following in a browser:"
echo ""
echo "  1. Authenticate at  https://slakxs.de/cookie"
echo "  2. Visit            https://slakxs.de/monitoring"
echo "  3. Create your admin account (first-run wizard — appears once)"
echo "  4. Click 'Add System' and fill in:"
echo "       Host : host.docker.internal"
echo "       Port : 45876"
echo "  5. Copy the KEY shown in the dialog"
echo ""

# ── Step 2: Accept key and write to .env ─────────────────────────────────────
read -rp "Paste the KEY here and press Enter: " AGENT_KEY

if [[ -z "$AGENT_KEY" ]]; then
    echo "ERROR: No key entered. Aborting." >&2
    exit 1
fi

if grep -q "^BESZEL_AGENT_KEY=" "$ROOT_ENV"; then
    sed -i "s|^BESZEL_AGENT_KEY=.*|BESZEL_AGENT_KEY=$AGENT_KEY|" "$ROOT_ENV"
    echo "Updated BESZEL_AGENT_KEY in .env"
else
    printf '\n# ── Beszel monitoring ────────────────────────────────────────────────────────\nBESZEL_AGENT_KEY=%s\n' "$AGENT_KEY" >> "$ROOT_ENV"
    echo "Added BESZEL_AGENT_KEY to .env"
fi

# ── Step 3: Start the agent ───────────────────────────────────────────────────
echo ""
echo "Step 2 — Starting Beszel agent..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d beszel-agent
echo ""
echo "Done! The hub will connect to the agent automatically."
echo "Refresh the Beszel UI — your system should appear within 30 seconds."
echo ""
