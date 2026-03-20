#!/bin/sh
# Post-renewal hook: Copy all cert files flat to reverse-proxy
# This script runs after Certbot successfully renews certificates

SOURCE_DIR="/etc/letsencrypt"
DEST_DIR="/mnt/certs"

if [ -d "$SOURCE_DIR" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Copying all cert files flat to $DEST_DIR"
    
    # Remove old files
    rm -f "$DEST_DIR"/*
    
    # Copy all files (flat, no directory structure), excluding README
    find "$SOURCE_DIR" -type f ! -name 'README' -exec cp {} "$DEST_DIR"/ \;
    
    # Set permissions: readable by default, private keys 600
    chmod 644 "$DEST_DIR"/* 2>/dev/null
    chmod 600 "$DEST_DIR"/privkey*.pem 2>/dev/null
    
    # Find the latest cert files (due to renewals, files may be cert2.pem, cert3.pem, etc)
    LATEST_CERT=$(ls -1t "$DEST_DIR"/cert*.pem 2>/dev/null | head -1)
    LATEST_KEY=$(ls -1t "$DEST_DIR"/privkey*.pem 2>/dev/null | head -1)
    LATEST_CHAIN=$(ls -1t "$DEST_DIR"/fullchain*.pem 2>/dev/null | head -1)
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync complete. Latest cert files:"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   Cert: $(basename $LATEST_CERT)"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   Key:  $(basename $LATEST_KEY)"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   Chain: $(basename $LATEST_CHAIN)"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Source directory not found: $SOURCE_DIR" >&2
    exit 1
fi
