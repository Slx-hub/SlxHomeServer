#!/bin/bash
# late-install.sh – Runs inside the freshly installed system (via preseed late_command).
# Sets up SSH key auth, Wi-Fi, and clones the SlxHomeServer repo.

set -e

SLX_USER="slx"
HOME_DIR="/home/${SLX_USER}"

# ── SSH key-only authentication ──────────────────────────────────────────
SSH_DIR="${HOME_DIR}/.ssh"
mkdir -p "${SSH_DIR}"
cp /tmp/authorized_keys "${SSH_DIR}/authorized_keys"
chmod 700 "${SSH_DIR}"
chmod 600 "${SSH_DIR}/authorized_keys"
chown -R "${SLX_USER}:${SLX_USER}" "${SSH_DIR}"

# Harden sshd: disable password auth, disable root login
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/'       /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/'                     /etc/ssh/sshd_config
sed -i 's/^#\?ChallengeResponseAuthentication .*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?KbdInteractiveAuthentication .*/KbdInteractiveAuthentication no/'       /etc/ssh/sshd_config

# ── Grant slx passwordless sudo ─────────────────────────────────────────
echo "${SLX_USER} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/slx
chmod 440 /etc/sudoers.d/slx

# ── Wi-Fi (optional – only if credentials are provided) ─────────────────
if [ -f /tmp/wifi.conf ]; then
    # shellcheck disable=SC1091
    . /tmp/wifi.conf

    if [ -n "${WIFI_SSID}" ] && [ -n "${WIFI_PASSWORD}" ]; then
        # Find a wireless interface
        WLAN_IF=$(find /sys/class/net -maxdepth 2 -name wireless -printf '%h\n' 2>/dev/null \
                  | head -n1 | xargs -r basename)

        if [ -n "${WLAN_IF}" ]; then
            cat > /etc/network/interfaces.d/wlan <<EOF
allow-hotplug ${WLAN_IF}
iface ${WLAN_IF} inet dhcp
    wpa-ssid ${WIFI_SSID}
    wpa-psk  ${WIFI_PASSWORD}
EOF
            chmod 600 /etc/network/interfaces.d/wlan
        fi
    fi

    rm -f /tmp/wifi.conf
fi

# ── Clone the SlxHomeServer repository ───────────────────────────────────
REPO_URL="https://github.com/Slx-hub/SlxHomeServer.git"
REPO_DIR="${HOME_DIR}/SlxHomeServer"

if [ ! -d "${REPO_DIR}" ]; then
    git clone "${REPO_URL}" "${REPO_DIR}"
fi
chown -R "${SLX_USER}:${SLX_USER}" "${REPO_DIR}"

# ── Cleanup ──────────────────────────────────────────────────────────────
rm -f /tmp/authorized_keys /tmp/late-install.sh

echo "SlxHomeServer late-install complete."
