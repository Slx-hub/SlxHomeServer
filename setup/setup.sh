#!/bin/bash
# setup.sh – Post-SSH machine setup for SlxHomeServer.
# Run as the "slx" user from /home/slx/SlxHomeServer/setup/
#
# Usage:
#   cd /home/slx/SlxHomeServer/setup
#   chmod +x setup.sh
#   ./setup.sh [OPTIONS]
#
# Options:
#   --all              Run all sections (default if no options specified)
#   --packages         Install packages from pkglist.txt
#   --docker           Install Docker
#   --firewall         Configure firewall (ufw)
#   --fail2ban         Enable fail2ban
#   --updates          Enable automatic security updates
#   --aliases          Deploy shell aliases
#   --backup           Install backup service and timer
#   --help             Show this help message

set -euo pipefail

# Parse command-line arguments
INSTALL_PACKAGES=false
INSTALL_DOCKER=false
CONFIGURE_FIREWALL=false
ENABLE_FAIL2BAN=false
ENABLE_UPDATES=false
DEPLOY_ALIASES=false
INSTALL_BACKUP=false

show_help() {
    grep "^# " "$0" | grep -E "^\# (Usage|Options|  --)" | sed 's/^# //'
}

if [ $# -eq 0 ]; then
    # No arguments: run all sections
    INSTALL_PACKAGES=true
    INSTALL_DOCKER=true
    CONFIGURE_FIREWALL=true
    ENABLE_FAIL2BAN=true
    ENABLE_UPDATES=true
    DEPLOY_ALIASES=true
    INSTALL_BACKUP=true
else
    # Parse provided arguments
    for arg in "$@"; do
        case "$arg" in
            --all)
                INSTALL_PACKAGES=true
                INSTALL_DOCKER=true
                CONFIGURE_FIREWALL=true
                ENABLE_FAIL2BAN=true
                ENABLE_UPDATES=true
                DEPLOY_ALIASES=true
                INSTALL_BACKUP=true
                ;;
            --packages)
                INSTALL_PACKAGES=true
                ;;
            --docker)
                INSTALL_DOCKER=true
                ;;
            --firewall)
                CONFIGURE_FIREWALL=true
                ;;
            --fail2ban)
                ENABLE_FAIL2BAN=true
                ;;
            --updates)
                ENABLE_UPDATES=true
                ;;
            --aliases)
                DEPLOY_ALIASES=true
                ;;
            --backup)
                INSTALL_BACKUP=true
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                echo "ERROR: Unknown option '$arg'" >&2
                show_help >&2
                exit 1
                ;;
        esac
    done
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_ENV="${SCRIPT_DIR}/../.env"
PKGLIST="${SCRIPT_DIR}/pkglist.txt"

# ── Environment file ─────────────────────────────────────────────────────────
# All secrets and machine-specific values live in the repo root .env.
# Warn early if it's missing or unconfigured; individual sections will
# re-check the values they need.
if [ ! -f "$ROOT_ENV" ]; then
    echo "WARNING: ${ROOT_ENV} not found."
    echo "  Copy .env.example to .env in the repo root and fill in your values."
    echo ""
else
    # shellcheck source=/dev/null
    source "$ROOT_ENV"
    echo "==> Loaded environment from ${ROOT_ENV}"
fi

if [ ! -f "${PKGLIST}" ]; then
    echo "ERROR: ${PKGLIST} not found." >&2
    exit 1
fi

echo "==> Updating package lists..."
sudo apt-get update -y

if [ "$INSTALL_PACKAGES" = true ]; then
    echo "==> Installing packages from pkglist.txt..."
    while IFS= read -r pkg || [ -n "${pkg}" ]; do
        pkg="$(echo "${pkg}" | xargs)"  # trim whitespace
        [ -z "${pkg}" ] && continue      # skip empty lines
        [[ "${pkg}" == \#* ]] && continue # skip comments

        echo "  -> Installing ${pkg}..."
        sudo apt-get install -y "${pkg}"
    done < "${PKGLIST}"
else
    echo "~~ Skipping package installation (--packages not specified)"
fi

# ── Docker ──────────────────────────────────────────────────────────────
# Install via the official convenience script (get.docker.com).
# Piped directly to sh — no intermediate file needed.
# Idempotent: the script detects an existing install and upgrades in-place.
if [ "$INSTALL_DOCKER" = true ]; then
    echo "==> Installing Docker via get.docker.com..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo systemctl enable docker
    sudo systemctl start docker
    # Let the current user run docker without sudo
    sudo usermod -aG docker "$(whoami)"
    echo "==> Docker installed. Log out and back in for group membership to take effect."
else
    echo "~~ Skipping Docker installation (--docker not specified)"
fi

# ── Firewall (ufw) ──────────────────────────────────────────────────────
# Default: deny all inbound, allow all outbound.
# Open only SSH (admin), HTTP/HTTPS (Caddy), and port 2222 (Gitea SSH).
if [ "$CONFIGURE_FIREWALL" = true ]; then
    echo "==> Configuring firewall..."
    sudo ufw --force reset
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    sudo ufw allow from 192.168.178.0/24 comment 'Allow all ports from local network'
    sudo ufw allow 22/tcp     comment 'SSH (admin)'
    sudo ufw allow 80/tcp     comment 'HTTP  – Caddy'
    sudo ufw allow 443/tcp    comment 'HTTPS – Caddy'
    sudo ufw allow 2222/tcp   comment 'Git SSH – Gitea'
    sudo ufw --force enable
    echo "==> Firewall active. Status:"
    sudo ufw status verbose
else
    echo "~~ Skipping firewall configuration (--firewall not specified)"
fi

# ── fail2ban ─────────────────────────────────────────────────────────────
# Bans IPs with repeated failed SSH attempts.
# Default jail is enabled automatically upon install.
if [ "$ENABLE_FAIL2BAN" = true ]; then
    echo "==> Enabling fail2ban..."
    sudo systemctl enable --now fail2ban
else
    echo "~~ Skipping fail2ban (--fail2ban not specified)"
fi

# ── Automatic security updates ────────────────────────────────────────────
if [ "$ENABLE_UPDATES" = true ]; then
    echo "==> Enabling unattended security upgrades..."
    sudo dpkg-reconfigure -f noninteractive unattended-upgrades
else
    echo "~~ Skipping automatic security updates (--updates not specified)"
fi

# ── Aliases ─────────────────────────────────────────────────────────────
# Deployed to /etc/profile.d/ for login shells and sourced from ~/.bashrc
# for non-login shells (e.g., VS Code SSH remote). Re-running setup.sh
# simply overwrites the file, which keeps this section fully idempotent.
if [ "$DEPLOY_ALIASES" = true ]; then
    ALIASES_SRC="${SCRIPT_DIR}/aliases.sh"
    ALIASES_DST="/etc/profile.d/slx-aliases.sh"

    if [ -f "${ALIASES_SRC}" ]; then
        echo "==> Deploying aliases to ${ALIASES_DST}..."
        sudo cp "${ALIASES_SRC}" "${ALIASES_DST}"
        sudo chmod 644 "${ALIASES_DST}"
        
        # Also source from ~/.bashrc for non-login shells (VS Code SSH remote, etc.)
        BASHRC_MARKER="# Source system-wide aliases for non-login shells"
        BASHRC_SOURCE="[ -f /etc/profile.d/slx-aliases.sh ] && source /etc/profile.d/slx-aliases.sh"
        
        if grep -q "Source system-wide aliases" ~/.bashrc 2>/dev/null; then
            # Already present, just update it
            sed -i "/$BASHRC_MARKER/!b;n;c\\    $BASHRC_SOURCE" ~/.bashrc
        else
            # Append to ~/.bashrc
            echo "" >> ~/.bashrc
            echo "$BASHRC_MARKER" >> ~/.bashrc
            echo "    $BASHRC_SOURCE" >> ~/.bashrc
        fi
        
        echo "==> Aliases deployed. Open a new shell (or run: source ${ALIASES_DST}) to activate."
    else
        echo "WARNING: ${ALIASES_SRC} not found, skipping alias deployment." >&2
    fi
else
    echo "~~ Skipping alias deployment (--aliases not specified)"
fi

# ── Backup service ──────────────────────────────────────────────────────────
# Builds the Docker image and installs the systemd service + timer.
# Requires BACKUP_DEVICE to be set in the repo root .env.
if [ "$INSTALL_BACKUP" = true ]; then
    BACKUP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)/dev/backup"
    if [ ! -d "$BACKUP_DIR" ]; then
        echo "ERROR: $BACKUP_DIR not found — is this the full repo?" >&2
        exit 1
    fi
    if [ -z "${BACKUP_DEVICE:-}" ] || echo "${BACKUP_DEVICE:-}" | grep -q 'YOUR-UUID-HERE'; then
        echo "WARNING: BACKUP_DEVICE is not configured in ${ROOT_ENV}"
        echo "  Find your drive's UUID with: blkid /dev/sdX"
        echo "  Set BACKUP_DEVICE in ${ROOT_ENV}, then re-run: sudo ./setup.sh --backup"
    else
        echo "==> Installing backup service..."
        sudo bash "${BACKUP_DIR}/install.sh"
    fi
else
    echo "~~ Skipping backup installation (--backup not specified)"
fi

echo ""
echo "==> Setup complete! All packages from pkglist.txt are installed."
