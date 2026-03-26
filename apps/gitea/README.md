# Gitea

Lightweight self-hosted Git service, replacing GitLab CE.

## Setup

### 2. Run First-Time Setup

```bash
cd /home/slx/SlxHomeServer/apps/gitea
chmod +x setup-gitea.sh
./setup-gitea.sh
```

This creates `/data/gitea/data` and `/data/gitea/config`, then starts the container.

### 3. Complete Web Setup

1. Visit `https://git.slakxs.de` (requires auth cookie — visit `/cookie` on the main domain first).
2. Gitea shows a first-run configuration page. The defaults are fine; just set your admin account.

### 4. Git over SSH

SSH clone URLs use port 2222 (host port 22 is reserved for server admin):

```bash
git clone ssh://git@git.slakxs.de:2222/user/repo.git
```

## Data & Backups

All persistent data lives under `/data/gitea/`:

| Path | Contents |
|---|---|
| `/data/gitea/data` | Repositories, LFS, avatars, attachments |
| `/data/gitea/config` | `app.ini` and other configuration |

Both paths should be included in `infra/backup/backup-sources.conf` and `infra/backup/snapshot-sources.conf`.

## Architecture

- **Reverse proxy**: Caddy at `git.slakxs.de` — requires `@hasAuth` cookie, otherwise returns 404.
- **Network**: Joins `main-network` (shared with other services and the reverse proxy).
- **SSH**: Host port 2222 → container port 22 for git-over-SSH access.
