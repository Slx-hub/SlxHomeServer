#!/bin/bash
# Registers the backup service and timer on this machine.
# Usage: sudo ./install.sh
# Safe to re-run — it will overwrite previously installed unit files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PATH="$(cd "$SCRIPT_DIR/../.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo ./install.sh)" >&2
    exit 1
fi

echo "=== Backup install ==="
echo "Repo path : $REPO_PATH"
echo "Script dir: $SCRIPT_DIR"
echo ""

# ── 1. Ensure /backup mount point exists ────────────────────────────────────
mkdir -p /backup
echo "Mount point /backup: OK"

# ── 2. Build Docker image ────────────────────────────────────────────────────
echo "Building Docker image slx-backup..."
docker build -t slx-backup "$SCRIPT_DIR"
echo "Image built: OK"

# ── 3. Make wrapper scripts executable ──────────────────────────────────────
chmod +x "$SCRIPT_DIR/run-backup.sh"

# ── 4. Install systemd service (substitute repo path into template) ──────────
sed "s|@@REPO_PATH@@|$REPO_PATH|g" \
    "$SCRIPT_DIR/backup.service.template" \
    > "$SYSTEMD_DIR/backup.service"
echo "Installed: $SYSTEMD_DIR/backup.service"

# ── 5. Install systemd timer ─────────────────────────────────────────────────
cp "$SCRIPT_DIR/backup.timer" "$SYSTEMD_DIR/backup.timer"
echo "Installed: $SYSTEMD_DIR/backup.timer"

# ── 6. Ensure Docker starts on boot ──────────────────────────────────────────
systemctl enable docker
echo "Enabled: docker.service"

# ── 7. Enable and start the timer ────────────────────────────────────────────
systemctl daemon-reload
systemctl enable backup.timer
systemctl start backup.timer
echo "Enabled and started: backup.timer"

echo ""
echo "=== Install complete ==="
echo ""
systemctl list-timers backup.timer --no-pager
echo ""
echo "Next steps:"
echo "  • Verify BACKUP_DEVICE is set correctly in the repo root .env"
echo "  • Manual test run: sudo systemctl start backup.service"
echo "  • Follow logs:     journalctl -fu backup.service"
