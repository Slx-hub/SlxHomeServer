# SlxHomeServer – Setup Guide

This document walks you through setting up your home server from scratch using the tools in the `setup/` folder.

## Prerequisites

| Item | Details |
|---|---|
| **PC** | Windows machine with PowerShell 5+ |
| **USB stick** | between 2 and 32 GB, will be **erased** |
| **Target machine** | x86-64 server/PC that can boot from USB |
| **Network** | Ethernet cable recommended; Wi-Fi supported as fallback |
| **SSH key pair** | Generate one if you don't have it: `ssh-keygen -t ed25519` |
| **Secure Boot** | Must be **disabled** in BIOS/UEFI — Windows 11 has it on by default |

## Step 1 — Prepare the Environment File

1. Open a terminal in the `setup/` folder.
2. Copy the example file:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Edit `.env` and fill in your real values:
   - **WIFI_SSID** / **WIFI_PASSWORD** – your Wi-Fi network credentials (only needed if the server won't be on Ethernet).
   - **SSH_PUBLIC_KEY_PATH** – absolute path to your SSH **public** key (e.g. `C:\Users\you\.ssh\id_ed25519.pub`).

> `.env` is gitignored and will never be committed.

## Step 2 — Prepare the USB Flash Drive

1. Insert the USB stick into your Windows PC.
2. Open **PowerShell as Administrator**.
3. Run:

   ```powershell
   cd path\to\SlxHomeServer\setup
   .\Prepare-FlashDrive.ps1              # defaults to drive D:
   # or specify the drive letter:
   .\Prepare-FlashDrive.ps1 -DriveLetter E
   ```

4. The script will:
   - Ask for confirmation before formatting.
   - Format the drive as FAT32.
   - Download the latest Debian netinst ISO (or use a cached copy).
   - Extract the ISO contents onto the drive.
   - Copy the preseed configuration, SSH key, and Wi-Fi credentials.
   - Patch the bootloader for a fully unattended install.

## Step 3 — Install Debian on the Server

> **Important:** The installer will **completely wipe** the main drive — Windows 11 and all existing data will be erased. This is intentional.

1. Before booting, enter BIOS/UEFI and:
   - **Disable Secure Boot** (required — the Debian installer will not boot with Secure Boot on).
   - Set USB as the first boot device.
2. Plug the prepared USB stick into your target server and power it on.
3. **Walk away.** The installation is fully automatic:
   - Debian is installed to the server's main disk.
   - A user **`slx`** is created.
   - SSH is configured for **key-only** authentication (password login disabled).
   - If Ethernet is connected, the network is ready immediately. If not, Wi-Fi is configured from your `.env` credentials.
   - The `SlxHomeServer` repository is cloned to `/home/slx/SlxHomeServer`.
4. When the server reboots and the login prompt appears, the OS installation is complete. **Remove the USB stick.**

## Step 4 — Connect via SSH

From your Windows PC, connect to the server:

```bash
ssh slx@<server-ip>
```

> **Tip:** Check your router's DHCP client list to find the server's IP, or use `arp -a` / `nmap` to scan your local network.

No password is needed — your SSH key is already authorized.

## Step 5 — Run the Setup Script

Once connected via SSH:

```bash
cd /home/slx/SlxHomeServer/setup
chmod +x setup.sh
./setup.sh
```

This installs the packages listed in `pkglist.txt`:

- git, docker, docker-compose, sudo, systemd, python3

After completion, log out and back in so the `docker` group membership takes effect:

```bash
exit
ssh slx@<server-ip>
docker run hello-world   # verify Docker works
```

## Step 6 — Deploy Services

With Docker ready, deploy the services from `main/`. Start with the reverse proxy and auth, then bring up everything else.

### 6a. Configure `.env`

```bash
cd /home/slx/SlxHomeServer
cp .env.example .env
nano .env   # fill in AUTH_TOKEN, GITEA_DOMAIN, PORKBUN keys, BACKUP_DEVICE, etc.
```

### 6b. Start the Reverse Proxy & Auth

```bash
cd main/reverse-proxy
docker compose up -d
```

### 6c. Start Services

Each service is independent — start whichever you need:

```bash
# Landing page and secret page
cd ../page && docker compose up -d
cd ../secret-page && docker compose up -d

# Container manager
cd ../containers && docker compose up -d

# Gitea (first time — creates /data/gitea directories)
cd ../gitea
chmod +x setup-gitea.sh
./setup-gitea.sh

# Jellyfin
cd ../jellyfin && docker compose up -d
```

### 6d. Gitea First-Run

1. Authenticate at `https://slakxs.de/cookie` with your `AUTH_TOKEN`.
2. Visit `https://git.slakxs.de` — Gitea shows its initial configuration page.
3. Set your admin account and finish setup.
4. SSH clone URLs use port 2222: `ssh://git@git.slakxs.de:2222/user/repo.git`

## Step 7 — You're Done

Your home server is now up and running with:

- Debian minimal install
- Key-only SSH access, `fail2ban` blocking brute-force attempts
- `ufw` firewall (only ports 22, 80, 443, 2222 open)
- Automatic security updates via `unattended-upgrades`
- Docker & Docker Compose ready
- Caddy reverse proxy with TLS for `slakxs.de` and `git.slakxs.de`
- Session-based auth protecting private pages and Gitea
- Gitea for self-hosted Git
- Jellyfin for media (LAN access)
- Automated backups for `/data/` directories

---

## File Overview

| File | Purpose |
|---|---|
| `.env.example` | Template for sensitive configuration |
| `.env` | Your actual secrets (gitignored) |
| `Prepare-FlashDrive.ps1` | PowerShell script to create the bootable USB |
| `preseed.cfg` | Debian installer answers for unattended install |
| `late-install.sh` | Runs at end of OS install (SSH keys, Wi-Fi, repo clone) |
| `setup.sh` | Post-SSH script to install packages and configure firewall |
| `pkglist.txt` | List of packages to install |
