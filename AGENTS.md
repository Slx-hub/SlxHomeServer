# SlxHomeServer — AI Context & Development Rules

This file provides persistent context for AI assistants working in this repository.
Read this before making any changes.

---

## Project Overview

Home-server infrastructure-as-code. A Debian machine running a stack of self-hosted services
behind a Caddy reverse proxy. All services are containerised with Docker Compose.

**Live domain:** `slakxs.de`
**Server user:** `slx` — home directory `/home/slx/`
**Repo path on server:** `/home/slx/SlxHomeServer`

---

## Repository Structure

```
SlxHomeServer/
├── setup/          OS installation, package list, firewall config
├── platform/       Core services every other service depends on
│   ├── reverse-proxy/  Caddy — TLS termination, routing, auth gating
│   └── auth/           Session cookie service (/cookie endpoint)
├── apps/           User-facing applications
│   ├── pages/      Lightweight custom-built pages & dashboards
│   │   ├── homepage/
│   │   ├── secret-page/
│   │   ├── container-manager/
│   │   └── monitoring/
│   ├── gitea/
│   └── jellyfin/
├── infra/          Background operational services (no direct user access)
│   ├── backup/
│   ├── certbot/
│   ├── ddns/
│   └── ntfy/
└── docs/
```

---

## Rules

### Secrets & Configuration

- **All secrets go in `/.env`** at the repo root. This file is gitignored and never committed.
- **`/.env.example` must stay in sync.** Any time a new variable is added to `.env`, add a
  matching placeholder entry to `.env.example` with a comment explaining what it is and how
  to get the value.
- Services reference secrets with `env_file: - ../../.env` (adjust relative depth as needed).
  Never hardcode secrets in compose files, scripts, or code.

### Networking & Reverse Proxy

- **All HTTP services must be registered in `platform/reverse-proxy/Caddyfile`** and
  reachable through the proxy at a defined path or subdomain.
- **All services that Caddy proxies to must join `main-network`** (the shared Docker bridge
  network defined in `platform/reverse-proxy/docker-compose.yml`). Declare it as external in
  the service's compose file:
  ```yaml
  networks:
    main-network:
      external: true
      name: main-network
  ```
- **Services must also expose a host port** for direct LAN access (useful for debugging and
  during reverse-proxy downtime). Use the `ports:` key in docker-compose — do not use
  `expose:` alone for services that need direct access.
- **Sensitive pages must be gated with `@hasAuth`** in the Caddyfile. The auth cookie is set
  by the `auth` service at the `/cookie` endpoint. Use this pattern:
  ```caddy
  handle /path* {
      handle @hasAuth {
          uri strip_prefix /path
          reverse_proxy service-name:PORT
      }
      handle {
          error 404
      }
  }
  ```
  Never return a login redirect — unauthenticated requests should silently 404 to avoid
  leaking the existence of private pages.

### Docker Compose

- **Every service must have a `docker-compose.yml`** in its own subdirectory. Never run
  containers with bare `docker run` in production.
- Use `restart: unless-stopped` for all persistent services.
- Service names in compose files become the DNS hostnames on `main-network`. Keep them
  short and lowercase (e.g. `beszel`, `gitea`, `container-manager`).
- Prefer official or well-maintained images. Pin to a minor version tag (e.g. `caddy:2-alpine`)
  rather than `latest` for services where breaking changes matter.

### Data & Backups

- **Persistent data that must survive a rebuild goes under `/data/` on the host.**
  Mount it as a bind mount, not a named volume. This makes the backup scope explicit.
  Example: `/data/gitea/data:/data` inside the container.
- **After adding a new data path, add it to both:**
  - `infra/backup/backup-sources.conf` — rsync'd daily
  - `infra/backup/snapshot-sources.conf` — tar'd weekly
- Named Docker volumes are acceptable for ephemeral caches (e.g. Caddy's ACME state,
  transcoding caches). Do not rely on them for data that must be backed up permanently.

### Host System Changes

- **Package installs and permanent host-level changes go in `setup/setup.sh`**, not in ad-hoc
  notes or READMEs. The script must be idempotent (safe to re-run).
- If a change requires a specific step order (e.g. install before configure), add a comment
  explaining why.
- `setup/pkglist.txt` is the canonical list of installed packages. Add any new packages there
  in addition to the install command in `setup.sh`.

### Adding a New Service — Checklist

1. Create `apps/<category>/<name>/docker-compose.yml` (or `infra/<name>/` for background
   services).
2. Join `main-network` as external.
3. Add a `ports:` entry for direct LAN access.
4. Add a `healthcheck:` in `docker-compose.yml` so service state surfaces in tooling.
5. Register in `platform/reverse-proxy/Caddyfile` — apply `@hasAuth` if the service exposes
   anything sensitive.
6. Add any new env vars to `/.env.example` with explanatory comments.
7. If the service writes persistent data, mount it under `/data/<service>/` and add the path
   to both conf files in `infra/backup/`.
8. If host packages are needed, add them to `setup/setup.sh` and `setup/pkglist.txt`.

---

## Conventions

| Concern | Convention |
|---|---|
| Port range | Custom services use 50000–50099; infra uses 49000–49999 |
| Auth cookie name | `auth_session` (checked via `header Cookie *auth_session*`) |
| Shared network | `main-network` |
| Backup drive mount | `/backup` |
| Persistent data root | `/data/` |
| Repo root on server | `/home/slx/SlxHomeServer` |
