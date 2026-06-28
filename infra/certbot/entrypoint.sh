#!/bin/sh
# Certbot renewal loop - runs forever, checking periodically
# Auto-detects whether to create initial cert or renew existing one
# Uses HTTP validation (--standalone) requiring port 80 access during renewal
# During initial generation, Caddy proxies challenges to this container on port 8080

set -e

RENEWAL_INTERVAL=86400  # 24 hours in seconds
DOMAINS="-d slakxs.de -d www.slakxs.de -d git.slakxs.de -d ntfy.slakxs.de -d monitor.slakxs.de -d stoat.slakxs.de -d jelly.slakxs.de"
EMAIL="${CERTBOT_EMAIL:-admin@slakxs.de}"
LIVE_DIR="/etc/letsencrypt/live"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Certbot service starting..."

# Initial certificate generation if not exists
if [ ! -d "$LIVE_DIR" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No existing certificates found. Generating initial certificate..."
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Caddy will proxy ACME challenges from port 80 to this container on port 8080"
    
    certbot certonly \
        --standalone \
        --agree-tos \
        --email "$EMAIL" \
        --non-interactive \
        --http-01-port 8080 \
        $DOMAINS \
        --post-hook "/bin/sh /etc/letsencrypt/renewal-hooks/post/restart-and-copy.sh"
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Initial certificate generated successfully."
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Certificate renewal service active. Will check daily at 05:00 UTC."

# Renewal loop
while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running renewal check..."
    
    certbot renew \
        --non-interactive \
        --agree-tos \
        --http-01-port 8080 \
        --deploy-hook "/bin/sh /etc/letsencrypt/renewal-hooks/post/restart-and-copy.sh" \
        -q || true
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Renewal check complete."
    
    difference=$(($(date -d "5:00" +%s) - $(date +%s)))
    
    if [ $difference -lt 0 ]
    then
        sleep $((86400 + difference))
    else
        sleep $difference
    fi
done
