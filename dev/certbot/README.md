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

Run this once to generate the initial wildcard certificate:

```bash
cd /home/slx/SlxHomeServer/dev/certbot

# Build the image
docker build -t certbot-porkbun .

# Generate wildcard certificate
docker run --rm \
  -v certbot_data:/etc/letsencrypt \
  certbot-porkbun certonly \
    --authenticator dns-porkbun \
    --dns-porkbun-key $(grep PORKBUN_API_KEY .env | cut -d= -f2) \
    --dns-porkbun-secret $(grep PORKBUN_API_SECRET .env | cut -d= -f2) \
    -d "*.slakxs.de" \
    -d slakxs.de \
    --agree-tos \
    --email $(grep CERTBOT_EMAIL .env | cut -d= -f2) \
    --non-interactive
```

This generates a wildcard certificate covering:
- `*.slakxs.de` – All subdomains
- `slakxs.de` – Base domain

### 4. Copy Initial Certs to Reverse Proxy

Copy all cert files flat (no folder structure):

```bash
docker run --rm \
  -v certbot_data:/etc/letsencrypt:ro \
  -v /home/slx/SlxHomeServer/main/reverse-proxy/certs/certbot:/mnt/certs \
  alpine sh -c "find /etc/letsencrypt -type f ! -name 'README' -exec cp {} /mnt/certs/ \; && chmod 644 /mnt/certs/* && chmod 600 /mnt/certs/privkey*.pem 2>/dev/null"
```

All cert files are copied flat to `/home/slx/SlxHomeServer/main/reverse-proxy/certs/certbot/`:
- `fullchain1.pem` (or `fullchain2.pem` on renewal) – Full chain (used by Caddy)
- `privkey1.pem` (or `privkey2.pem` on renewal) – Private key (used by Caddy)
- Plus all other cert files and configs

**Note:** File names increment on renewal (cert2.pem, privkey2.pem, etc). Caddy automatically picks up the latest.

### 5. Update Reverse Proxy Configuration

The Caddyfile uses the flat cert paths:

```caddyfile
slakxs.de {
    tls /etc/caddy/certs/fullchain1.pem /etc/caddy/certs/privkey1.pem
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
2. The post-renewal hook copies all cert files flat to `/home/slx/SlxHomeServer/main/reverse-proxy/certs/certbot/`
3. Caddy reads from the flat cert files

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
- `post-renewal.sh` – Hook to sync cert files flat to reverse-proxy

**Local cert directory (flat structure):**
```
/home/slx/SlxHomeServer/main/reverse-proxy/certs/certbot/
├── fullchain1.pem  ← Caddy reads from here (full chain)
├── privkey1.pem    ← Caddy reads from here (private key)
├── cert1.pem       (leaf certificate)
├── chain1.pem      (intermediates)
├── private_key.json
├── meta.json
├── slakxs.de.conf
└── porkbun_credentials.ini
```

## References

- [Certbot Documentation](https://certbot.eff.org/)
- [certbot-dns-porkbun](https://github.com/infinityofspace/certbot_dns_porkbun)
- [Let's Encrypt](https://letsencrypt.org/)
