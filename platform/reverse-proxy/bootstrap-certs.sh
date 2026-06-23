#!/bin/bash
# Bootstrap self-signed certificates for initial Caddy startup
# These are temporary and will be replaced by certbot with real Let's Encrypt certs

CERT_DIR="/home/slx/SlxHomeServer/platform/reverse-proxy/certs/certbot"

# Create directory if it doesn't exist
mkdir -p "$CERT_DIR"

# Only generate if certs don't already exist
if [ ! -f "$CERT_DIR/fullchain1.pem" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Generating bootstrap self-signed certificates..."
    
    # Generate private key
    openssl genrsa -out "$CERT_DIR/privkey1.pem" 2048 2>/dev/null
    
    # Generate self-signed cert (valid for 90 days)
    openssl req -new -x509 -key "$CERT_DIR/privkey1.pem" \
        -out "$CERT_DIR/cert1.pem" \
        -days 90 \
        -subj "/C=DE/ST=State/L=City/O=SlxHomeServer/CN=slakxs.de" 2>/dev/null
    
    # Create fullchain (concat cert + key for Caddy format)
    cat "$CERT_DIR/cert1.pem" > "$CERT_DIR/fullchain1.pem"
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bootstrap certificates created at $CERT_DIR"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Caddy will use these until certbot replaces them with real Let's Encrypt certificates"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Certificates already exist, skipping bootstrap"
fi

# Ensure proper permissions
chmod 644 "$CERT_DIR"/cert*.pem "$CERT_DIR"/fullchain*.pem 2>/dev/null || true
chmod 600 "$CERT_DIR"/privkey*.pem 2>/dev/null || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Certificate setup complete"
