# Certbot - Automated Let's Encrypt Certificate Management

Automatically generates and renews SSL/TLS certificates for `slakxs.de` using Let's Encrypt and Porkbun DNS validation.

## Setup

### 1. Get Porkbun API Credentials

1. Log in to [Porkbun](https://porkbun.com)
2. Go to **Account** → **API** → **API Keys**
3. Create an API key (or use existing one)
4. Copy the **API Key** and **API Secret**

### 2. Configure Credentials

Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
# Edit .env with your API credentials
nano .env
```

### 3. Initial Certificate Generation

Run this once to generate the initial certificate:

```bash
cd /home/slx/SlxHomeServer/dev/certbot

# Build the image
docker build -t certbot-porkbun .

# Generate initial certificate
docker run --rm \
  -v certbot_data:/etc/letsencrypt \
  certbot-porkbun certonly \
    --authenticator dns-porkbun \
    --dns-porkbun-key $(grep PORKBUN_API_KEY .env | cut -d= -f2) \
    --dns-porkbun-secret $(grep PORKBUN_API_SECRET .env | cut -d= -f2) \
    -d slakxs.de \
    -d www.slakxs.de \
    --agree-tos \
    --email $(grep CERTBOT_EMAIL .env | cut -d= -f2) \
    --non-interactive
```

### 4. Copy Initial Certs to Reverse Proxy

Copy the entire Let's Encrypt directory structure (no renaming, using canonical paths as-is):

```bash
# Copy entire Let's Encrypt directory structure
docker run --rm \
  -v certbot_data:/etc/letsencrypt:ro \
  -v /home/slx/SlxHomeServer/main/reverse-proxy/certs/certbot:/mnt/certs \
  alpine sh -c "cp -r /etc/letsencrypt/* /mnt/certs/ && find /mnt/certs -type f -exec chmod 644 {} \; && find /mnt/certs -name 'privkey*.pem' -exec chmod 600 {} \;"
```

This creates the structure at `/home/slx/SlxHomeServer/main/reverse-proxy/certs/certbot/`:
- `live/slakxs.de/fullchain.pem` – Full certificate chain (Caddy uses this)
- `live/slakxs.de/privkey.pem` – Private key (Caddy uses this)
- `live/slakxs.de/cert.pem` – Certificate only
- `live/slakxs.de/chain.pem` – Chain only
- `archive/slakxs.de/` – All historical versions

### 5. Update Reverse Proxy Configuration

The Caddyfile uses the canonical Let's Encrypt paths:

```caddyfile
slakxs.de {
    tls /etc/caddy/certs/live/slakxs.de/fullchain.pem /etc/caddy/certs/live/slakxs.de/privkey.pem
    # ... rest of config
}
```

The reverse-proxy `docker-compose.yml` mounts the local directory:

```yaml
volumes:
  - ./certs/certbot:/etc/caddy/certs:ro
```

Certs are stored locally at: `/home/slx/SlxHomeServer/main/reverse-proxy/certs/certbot/`

### 6. Start Renewal Service

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f certbot
```

## Automatic Renewal

The container runs Certbot's renewal check every 12 hours. When a certificate needs renewal (usually 30 days before expiry):

1. Certbot renews the certificate
2. The post-renewal hook syncs the entire Let's Encrypt directory structure to `/home/slx/SlxHomeServer/main/reverse-proxy/certs/certbot/`
3. Caddy reads updated certificates directly from the canonical Let's Encrypt paths

## Manual Renewal

```bash
docker-compose exec certbot renew --force-renewal
```

## Troubleshooting

**Check certificate status:**
```bash
docker-compose exec certbot certificates
```

**Manual renewal test:**
```bash
docker-compose exec certbot renew --authenticator dns-porkbun --dry-run
```

**View certificate details:**
```bash
docker-compose exec certbot show slakxs.de
```

**Check renewal logs:**
```bash
docker-compose logs certbot | grep -i "renewing\|success\|error"
```

## File Structure

- `Dockerfile` – Custom image with Porkbun DNS plugin
- `docker-compose.yml` – Service orchestration
- `.env` – API credentials (copy from `.env.example`)
- `post-renewal.sh` – Hook to sync entire Let's Encrypt directory to reverse-proxy

**Local cert directory structure:**
```
/home/slx/SlxHomeServer/main/reverse-proxy/certs/certbot/
├── live/
│   └── slakxs.de/
│       ├── fullchain.pem ← Caddy reads from here (full chain)
│       ├── privkey.pem   ← Caddy reads from here (private key)
│       ├── cert.pem      (leaf certificate)
│       └── chain.pem     (intermediates)
├── archive/
│   └── slakxs.de/
│       ├── cert1.pem, cert2.pem, ...       (historical)
│       └── privkey1.pem, privkey2.pem, ... (historical)
└── renewal/
    └── slakxs.de.conf (Certbot renewal config)
```

## References

- [Certbot Documentation](https://certbot.eff.org/)
- [certbot-dns-porkbun](https://github.com/infinityofspace/certbot_dns_porkbun)
- [Let's Encrypt](https://letsencrypt.org/)
