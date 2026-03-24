#!/bin/bash
# Sets up rclone with a Google Photos remote on a headless server.
# The OAuth flow is handled via a URL you open on any device with a browser.
#
# Usage: sudo bash dev/backup/setup-rclone.sh
#
# What this script does:
#   1. Runs 'rclone config' inside the backup Docker image (no host install needed)
#   2. Guides you through the interactive Google Photos setup
#   3. Writes the config to /etc/rclone/rclone.conf (where the backup container expects it)

set -euo pipefail

CONFIG_DIR="/etc/rclone"
CONFIG_FILE="$CONFIG_DIR/rclone.conf"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: Run as root: sudo bash dev/backup/setup-rclone.sh" >&2
    exit 1
fi

# Ensure the backup image exists
if ! docker image inspect slx-backup &>/dev/null; then
    echo "ERROR: Docker image 'slx-backup' not found."
    echo "  Build it first: sudo bash dev/backup/install.sh"
    exit 1
fi

mkdir -p "$CONFIG_DIR"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  rclone Google Photos setup — headless server"
echo "════════════════════════════════════════════════════════"
echo ""
echo "You will be walked through an interactive rclone config."
echo "Follow these steps when prompted:"
echo ""
echo "  1. Press 'n' for New remote"
echo "  2. Name it exactly:  gphotos"
echo "  3. Type 'google photos' or choose its number from the list"
echo "  4. Client ID and Secret: leave BLANK (press Enter twice)"
echo "  5. Read only access: type 'false' — Google restricted the readonly scope"
echo "     in 2022; it no longer allows listing all media. rclone itself won't"
echo "     upload or delete anything, so 'false' here is safe."
echo "  6. Edit advanced config? → No"
echo "  7. Use auto config? → answer 'No'"
echo ""
echo "  rclone will print a URL."
echo "  Open it on ANY device with a browser, authorize with Google,"
echo "  and paste the resulting token code back into this terminal."
echo ""
echo "  8. Confirm the remote looks correct → Yes"
echo "  9. Quit config (press 'q')"
echo ""
read -rp "Press Enter to launch rclone config..."
echo ""

# Run rclone config inside the backup container.
# Use manual URL auth (answer 'No' to auto config) — no port mapping needed.
docker run --rm -it \
    -v "$CONFIG_DIR:$CONFIG_DIR" \
    --entrypoint rclone \
    slx-backup \
    config --config "$CONFIG_FILE"

echo ""
if [[ -f "$CONFIG_FILE" ]]; then
    if grep -q "\[gphotos\]" "$CONFIG_FILE"; then
        echo "✓ Config written to $CONFIG_FILE"
        echo "✓ Remote 'gphotos' found — setup complete!"
        echo ""
        echo "To test the connection:"
        echo "  sudo docker run --rm -v $CONFIG_DIR:$CONFIG_DIR --entrypoint rclone slx-backup lsd --config $CONFIG_FILE gphotos:"
        echo ""
        echo "The backup service will now sync Google Photos every Tuesday"
        echo "or whenever you run:  sudo bash dev/backup/run-backup.sh --full"
    else
        echo "WARNING: Config file exists but no [gphotos] remote found."
        echo "  Make sure you named the remote exactly 'gphotos' and re-run this script."
        exit 1
    fi
else
    echo "ERROR: Config file was not created at $CONFIG_FILE"
    echo "  Something went wrong during the rclone config flow. Re-run this script."
    exit 1
fi
