# Beszel — Container Resource Monitor

Lightweight time-series resource monitoring for Docker containers and the host.
Shows CPU, memory, disk, and network graphs with configurable time ranges (1h, 12h, 24h, week, month).

## Quick Start

Make sure the reverse proxy is running, then:

```bash
bash setup.sh
```

The script starts the hub, walks you through adding this server as a monitored system, then starts the agent. Takes about 2 minutes.

## How it works

| Service | Role |
|---|---|
| `beszel` | Hub — web UI + SQLite storage, served at `/monitoring` |
| `beszel-agent` | Agent — host networking, collects all container + host stats |

The hub **connects to** the agent (not the reverse). On this single-host setup the
hub locates the agent via `host.docker.internal:45876`.

## Subpath caveat

Beszel is proxied at `slakxs.de/monitoring` by stripping the path prefix in Caddy.
If the UI loads but CSS/JS assets fail (404s in devtools), Beszel's frontend doesn't
support relative-path subpath mounting. Fix: switch to a dedicated subdomain.

Replace the `/monitoring*` block in `platform/reverse-proxy/Caddyfile` with:

```caddy
monitor.slakxs.de {
    tls /etc/caddy/certs/certbot/fullchain1.pem /etc/caddy/certs/certbot/privkey1.pem

    @hasAuth {
        header Cookie *auth_session*
    }

    handle /cookie* { reverse_proxy auth:49999 }
    handle @hasAuth { reverse_proxy beszel:8090 }
    handle { error 404 }
}
```

No changes to `docker-compose.yml` needed.
