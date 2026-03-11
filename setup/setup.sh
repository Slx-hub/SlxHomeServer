#!/bin/bash
# setup.sh – Post-SSH machine setup for SlxHomeServer.
# Run as the "slx" user from /home/slx/SlxHomeServer/setup/
#
# Usage:
#   cd /home/slx/SlxHomeServer/setup
#   chmod +x setup.sh
#   ./setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKGLIST="${SCRIPT_DIR}/pkglist.txt"

if [ ! -f "${PKGLIST}" ]; then
    echo "ERROR: ${PKGLIST} not found." >&2
    exit 1
fi

echo "==> Updating package lists..."
sudo apt-get update -y

echo "==> Installing packages from pkglist.txt..."
while IFS= read -r pkg || [ -n "${pkg}" ]; do
    pkg="$(echo "${pkg}" | xargs)"  # trim whitespace
    [ -z "${pkg}" ] && continue      # skip empty lines
    [[ "${pkg}" == \#* ]] && continue # skip comments

    echo "  -> Installing ${pkg}..."
    sudo apt-get install -y "${pkg}"
done < "${PKGLIST}"

# ── Docker ──────────────────────────────────────────────────────────────
# Install via the official convenience script (get.docker.com).
# Piped directly to sh — no intermediate file needed.
# Idempotent: the script detects an existing install and upgrades in-place.
echo "==> Installing Docker via get.docker.com..."
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable docker
sudo systemctl start docker
# Let the current user run docker without sudo
sudo usermod -aG docker "$(whoami)"
echo "==> Docker installed. Log out and back in for group membership to take effect."

# ── Firewall (ufw) ──────────────────────────────────────────────────────
# Default: deny all inbound, allow all outbound.
# Open only SSH (admin), HTTP/HTTPS (Caddy), and port 2222 (GitLab SSH).
echo "==> Configuring firewall..."
sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp     comment 'SSH (admin)'
sudo ufw allow 80/tcp     comment 'HTTP  – Caddy'
sudo ufw allow 443/tcp    comment 'HTTPS – Caddy'
sudo ufw allow 2222/tcp   comment 'Git SSH – GitLab'
sudo ufw --force enable
echo "==> Firewall active. Status:"
sudo ufw status verbose

# ── fail2ban ─────────────────────────────────────────────────────────────
# Bans IPs with repeated failed SSH attempts.
# Default jail is enabled automatically upon install.
echo "==> Enabling fail2ban..."
sudo systemctl enable --now fail2ban

# ── Automatic security updates ────────────────────────────────────────────
echo "==> Enabling unattended security upgrades..."
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

# ── Aliases ─────────────────────────────────────────────────────────────
# Deployed to /etc/profile.d/ so they are available system-wide to all
# users and login shells. Re-running setup.sh simply overwrites the file,
# which keeps this section fully idempotent.
ALIASES_SRC="${SCRIPT_DIR}/aliases.sh"
ALIASES_DST="/etc/profile.d/slx-aliases.sh"

if [ -f "${ALIASES_SRC}" ]; then
    echo "==> Deploying aliases to ${ALIASES_DST}..."
    sudo cp "${ALIASES_SRC}" "${ALIASES_DST}"
    sudo chmod 644 "${ALIASES_DST}"
    echo "==> Aliases deployed. Open a new shell (or run: source ${ALIASES_DST}) to activate."
else
    echo "WARNING: ${ALIASES_SRC} not found, skipping alias deployment." >&2
fi

echo ""
echo "==> Setup complete! All packages from pkglist.txt are installed."
