---
applyTo: "**"
---

<!-- Full context lives in /AGENTS.md — read that file first. -->
<!-- This file re-states the rules so GitHub Copilot picks them up in VS Code. -->

# SlxHomeServer — Development Rules

## Secrets

- All secrets in `/.env` (gitignored). Always add matching placeholder to `/.env.example`.
- Services load secrets with `env_file: - ../../.env`. No hardcoded secrets anywhere.

## Networking & Reverse Proxy

- Every HTTP service is routed through Caddy (`platform/reverse-proxy/Caddyfile`).
- Every proxied service joins `main-network` (external bridge, declared in reverse-proxy compose).
- Every service also exposes a `ports:` entry for direct LAN access.
- Sensitive pages use the `@hasAuth` cookie guard in the Caddyfile. Unauthenticated requests
  return 404, not a redirect.

## Docker Compose

- Every service has its own `docker-compose.yml`. Use `restart: unless-stopped`.
- Service names in compose = DNS hostnames on `main-network`.

## Data & Backups

- Persistent data lives under `/data/<service>/` as bind mounts.
- New data paths must be added to both:
  - `infra/backup/backup-sources.conf`
  - `infra/backup/snapshot-sources.conf`

## Host Changes

- Package installs and permanent host changes go in `setup/setup.sh` (must be idempotent).
- New packages also added to `setup/pkglist.txt`.

## Adding a New Service — Checklist

1. Create `apps/<name>/docker-compose.yml` (or `infra/<name>/` for background services)
2. Join `main-network` as external + add `ports:` entry
3. Add a `healthcheck:` entry in `docker-compose.yml`
4. Register route in `platform/reverse-proxy/Caddyfile` (add `@hasAuth` if sensitive)
5. Add new env vars to `/.env.example`
6. Add data paths to both backup conf files
7. Add host packages to `setup/setup.sh` and `setup/pkglist.txt`

## Folder Structure

```
platform/   — reverse-proxy, auth (core, never remove)
apps/       — user-facing (pages/ for lightweight custom pages; root for full apps)
infra/      — background daemons (backup, certbot, ddns, ntfy)
setup/      — OS install & configuration scripts
```

See [AGENTS.md](../AGENTS.md) for full detail, conventions table, and port ranges.
