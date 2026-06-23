# Certbot - Automated Let's Encrypt Certificate Management

Automatically generates and renews SSL/TLS certificates for `slakxs.de` using Let's Encrypt HTTP-01 validation.
**Fully autonomous** — no manual intervention needed. Initial cert is generated on first boot; renewal checks run daily at 4:00 AM.

## Quick Start

```bash
# 1. Create bootstrap (self-signed) certs for Caddy startup
cd /home/slx/SlxHomeServer/platform/reverse-proxy/certs/certbot
bash ../bootstrap-certs.sh

# 2. Ensure CERTBOT_EMAIL is set in /.env
grep CERTBOT_EMAIL /.env

# 3. Start the services (reverse-proxy first, then certbot)
cd /home/slx/SlxHomeServer/platform/reverse-proxy
docker-compose up -d

cd /home/slx/SlxHomeServer/infra/certbot
docker-compose up -d

# 4. Wait 30 seconds for certbot to generate real certs, then verify
sleep 30
docker-compose exec certbot certificates
```

## Initial Setup (Detailed)

### Prerequisites

- The reverse-proxy service must be running and healthy
- `CERTBOT_EMAIL` must be set in `/.env` (example: `CERTBOT_EMAIL=admin@example.com`)
- `main-network` Docker bridge must exist (created by reverse-proxy)

### Step 1: Create Bootstrap Self-Signed Certificates

Caddy needs a certificate to start. Before running certbot, create temporary self-signed certs:

```bash
cd /home/slx/SlxHomeServer/platform/reverse-proxy/certs/certbot
bash ../bootstrap-certs.sh
```

This creates placeholder `fullchain1.pem` and `privkey1.pem` so Caddy can boot.

**Why?** Caddy's Caddyfile references certificate files that don't exist yet. Bootstrap certs allow Caddy to start while certbot generates real Let's Encrypt certs.

### Step 2: Start the Reverse Proxy

```bash
cd /home/slx/SlxHomeServer/platform/reverse-proxy
docker-compose up -d
```

Wait for Caddy to be healthy (check with `docker-compose ps`).

### Step 3: Start Certbot

```bash
cd /home/slx/SlxHomeServer/infra/certbot
docker-compose up -d
```

The service automatically:
- Detects that no real certificates exist
- Generates initial Let's Encrypt certificates for `slakxs.de` and `git.slakxs.de` via HTTP-01 validation
- Copies the real certs to the reverse-proxy directory
- Restarts Caddy to load the real certificates

**This happens in the first 30 seconds—no manual steps needed.**

### Step 4: Verify Installation

```bash
docker-compose exec certbot certificates
```

Expected output:
```
Found the following certs:
  Certificate Name: slakxs.de
    Domains: slakxs.de, git.slakxs.de
    Expiry Date: YYYY-MM-DD HH:MM:SS+00:00 (90 days from now)
    Certificate Path: /etc/letsencrypt/live/slakxs.de/fullchain.pem
    Private Key Path: /etc/letsencrypt/live/slakxs.de/privkey.pem
```

If this shows an error instead, check the logs:
```bash
docker-compose logs --tail 50
```

## How It Works

The certbot container runs continuously and:

1. **Initial generation** (first boot only):
   - Checks if `/etc/letsencrypt/live` exists
   - If missing, runs `certbot certonly --standalone` to generate the initial Let's Encrypt certificate
   - The post-renewal hook copies certs and restarts Caddy
   - Takes ~10-30 seconds

2. **Renewal checks** (daily at 4:00 AM):
   - Runs `certbot renew` once per day at 4:00 AM to check for certificates due for renewal (30+ days before expiry)
   - Certificates are automatically renewed if needed
   - If renewed, the post-renewal hook copies certs and restarts Caddy
   - Then sleeps until the next 4:00 AM window

3. **ACME validation** (HTTP-01):
   - Certbot listens on port 8080 (standalone server)
   - Caddy proxies `/.well-known/acme-challenge/*` to certbot:8080 (no auth required)
   - Let's Encrypt validates domain ownership via HTTP

## Certificate Distribution

After cert generation or renewal:

1. **Source:** `/etc/letsencrypt/live/slakxs.de/` (inside container)
2. **Destination:** `/home/slx/SlxHomeServer/platform/reverse-proxy/certs/certbot/` (host)
3. **Caddy reads:** `/etc/caddy/certs/` (mounted from reverse-proxy directory)

All cert files are copied flat (no subdirectories):
```
/home/slx/SlxHomeServer/platform/reverse-proxy/certs/certbot/
├── fullchain1.pem     ← Caddy uses this (full chain)
├── privkey1.pem       ← Caddy uses this (private key)
├── cert1.pem
├── chain1.pem
├── slakxs.de.conf
└── (other certbot config files)
```

## Monitoring

**Check service status:**
```bash
cd /home/slx/SlxHomeServer/infra/certbot
docker-compose ps
```

Should show `Up X minutes (healthy)`.

**Follow logs in real-time:**
```bash
docker-compose logs -f
```

**Check registered certificates:**
```bash
docker-compose exec certbot certificates
```

**Check certificate expiry date:**
```bash
docker-compose exec certbot certbot certificates | grep "Expiry Date"
```

## Manual Renewal

To force an immediate renewal check (skips the 4 AM schedule):

```bash
cd /home/slx/SlxHomeServer/infra/certbot
docker-compose exec certbot certbot renew --force-renewal
```

To check if a renewal is due without actually renewing:

```bash
docker-compose exec certbot certbot renew --dry-run
```

## Troubleshooting

**Container is restarting repeatedly?**
- Check logs: `docker-compose logs --tail 100`
- Common causes:
  - Bootstrap certs missing: Ensure `platform/reverse-proxy/certs/certbot/fullchain1.pem` exists
  - Invalid `CERTBOT_EMAIL` in `/.env`: Set a valid email address
  - Port 8080 in use: `docker ps | grep 8080`
  - `main-network` doesn't exist: Ensure reverse-proxy was started first

**Certificate not generating on first boot?**
- Wait 30 seconds after `docker-compose up -d` (cert generation takes time)
- Check logs for errors: `docker-compose logs --tail 50 | grep -i error`
- Verify Caddy is running and healthy: `cd ../reverse-proxy && docker-compose ps`
- Check that port 80 is accessible from the internet (Let's Encrypt needs to reach your server)

**Certificate not renewing automatically?**
- The renewal check happens daily at 4:00 AM
- If cert is not due yet (more than 30 days remaining), `certbot renew` will skip it
- To test renewal, run: `docker-compose exec certbot certbot renew --dry-run`
- Check logs around 4:00 AM: `docker-compose logs --since "4 hours ago"`

**Certificate file not being copied to reverse-proxy?**
- The post-renewal hook copies certs automatically after renewal
- Check the hook ran: `docker-compose logs | grep -i "hook\|copy\|restart"`
- Verify the destination directory: `ls -la /home/slx/SlxHomeServer/platform/reverse-proxy/certs/certbot/`
- Check file permissions: `stat /home/slx/SlxHomeServer/platform/reverse-proxy/certs/certbot/privkey1.pem`

**Caddy not using new certificate?**
- The post-renewal hook restarts Caddy automatically
- Verify restart happened: `docker ps | grep reverse-proxy` (check creation time)
- Or manually restart Caddy: `cd ../reverse-proxy && docker-compose restart`
- Verify Caddy loaded the new cert: `curl -v https://git.slakxs.de 2>&1 | grep "subject="`

**ACME validation failing (HTTP-01)?**
- Ensure port 80 is open to the internet (firewall, VPN, etc.)
- Test from outside the server: `curl http://slakxs.de/.well-known/acme-challenge/test`
- Check DNS resolves correctly: `nslookup slakxs.de`
- Verify Caddy is forwarding challenges to certbot: `docker-compose logs | grep "acme-challenge"`

## File Structure

- **`entrypoint.sh`** – Lifecycle script
  - Detects if initial cert generation is needed
  - Runs renewal check daily at 4:00 AM
  - Sleeps until next 4:00 AM window
  
- **`Dockerfile`** – Builds certbot image from official certbot image
  - Installs entrypoint script
  - Creates renewal hook directory
  
- **`docker-compose.yml`** – Service orchestration
  - Joins `main-network` (external bridge)
  - Mounts cert volume for persistence
  - Mounts Docker socket for restarting Caddy
  - Loads `CERTBOT_EMAIL` from `/.env`
  - Includes healthcheck that runs every 6 hours
  
- **`post-renewal.sh`** – Post-renewal hook
  - Runs automatically after successful cert generation or renewal
  - Copies certs from `/etc/letsencrypt/live/` to reverse-proxy directory
  - Sets correct file permissions
  - Restarts Caddy container

## Certificate Paths

**Inside container:**
```
/etc/letsencrypt/live/slakxs.de/
├── fullchain.pem   (full certificate chain)
└── privkey.pem     (private key)
```

**On host (after copy):**
```
/home/slx/SlxHomeServer/platform/reverse-proxy/certs/certbot/
├── fullchain1.pem  (copied from container, Caddy uses this)
├── privkey1.pem    (copied from container, Caddy uses this)
└── (other certbot config files)
```

**Caddy reads:**
```
/etc/caddy/certs/certbot/  (mounted at startup)
