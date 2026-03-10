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

    # docker-compose is provided by docker-compose-plugin in modern repos
    if [ "${pkg}" = "docker-compose" ]; then
        pkg="docker-compose-plugin"
    fi

    echo "  -> Installing ${pkg}..."
    sudo apt-get install -y "${pkg}"
done < "${PKGLIST}"

# ── Enable and start Docker ─────────────────────────────────────────────
if command -v docker &>/dev/null; then
    sudo systemctl enable docker
    sudo systemctl start docker
    # Let slx run docker without sudo
    sudo usermod -aG docker "$(whoami)"
    echo "==> Docker enabled. Log out and back in for group changes to take effect."
fi

echo ""
echo "==> Setup complete! All packages from pkglist.txt are installed."
