# SlxHomeServer

Infrastructure-as-code repository for my home server. Everything needed to go from bare metal to a fully configured machine — automated, versioned, reproducible.

## Quick Start

See the **[Setup Guide](docs/setup-guide.md)** for step-by-step instructions.

## Repository Structure

```
SlxHomeServer/
├── .env.example        # Template for secrets (copy to .env)
├── setup/              # OS installation & initial machine setup
│   ├── Prepare-FlashDrive.ps1  # Create bootable USB from Windows
│   ├── preseed.cfg     # Debian unattended install answers
│   ├── late-install.sh # Runs at end of OS install
│   ├── setup.sh        # Post-SSH package installation & firewall
│   ├── pkglist.txt     # Packages to install
│   └── aliases.sh      # Shell aliases deployed to /etc/profile.d/
├── main/               # Service configurations (Docker Compose)
│   ├── reverse-proxy/  # Caddy — TLS termination & routing
│   ├── auth/           # Session-based auth service (/cookie)
│   ├── page/           # Public landing page
│   ├── secret-page/    # Private page (requires auth)
│   ├── containers/     # Docker container manager UI
│   ├── gitea/          # Gitea — self-hosted Git (git.slakxs.de)
│   └── jellyfin/       # Jellyfin — media server (LAN only)
├── dev/                # Development / infrastructure tooling
│   ├── backup/         # Automated backup service (rsync + tar)
│   ├── certbot/        # TLS certificate renewal
│   └── porkbun/        # Dynamic DNS updater
└── docs/               # Documentation
    ├── setup-guide.md  # Full setup walkthrough
    └── notes-for-someday.md
```

## Overview

1. **Prepare a USB stick** on your Windows PC (`setup/Prepare-FlashDrive.ps1`).
2. **Boot** the target machine from USB — Debian installs itself with zero user input.
3. **SSH in** and run `setup/setup.sh` to install Docker, configure firewall, and deploy aliases.
4. **Deploy services** from `main/` — each has its own `docker-compose.yml`.

## Services

| Service | Domain / Access | Auth | Dir |
|---|---|---|---|
| **Reverse Proxy** | `slakxs.de` (ports 80/443) | — | `main/reverse-proxy/` |
| **Auth** | `/cookie` endpoint | — | `main/auth/` |
| **Landing Page** | `/page` | Public | `main/page/` |
| **Secret Page** | `/secret/page` | Cookie | `main/secret-page/` |
| **Container Manager** | `/secret/containers` | Cookie | `main/containers/` |
| **Gitea** | `git.slakxs.de` | Cookie | `main/gitea/` |
| **Jellyfin** | `http://<server-ip>:8096` | LAN only | `main/jellyfin/` |

## Configuration

All secrets and machine-specific values live in a single `.env` file at the repo root (gitignored). Copy `.env.example` and fill in your values:

```bash
cp .env.example .env
```

Key variables: `AUTH_TOKEN`, `GITEA_DOMAIN`, `PORKBUN_API_KEY`, `BACKUP_DEVICE`, etc.

## Backups

The backup system (`dev/backup/`) mirrors and snapshots critical data directories:

- `/data/jellyfin/config`
- `/data/gitea/data`, `/data/gitea/config`
- `/data/media`

See `dev/backup/backup-sources.conf` for the full list.
