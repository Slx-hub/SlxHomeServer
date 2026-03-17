#!/bin/sh
# Post-renewal hook: Sync entire Let's Encrypt directory structure to reverse-proxy
# This script runs after Certbot successfully renews certificates

SOURCE_DIR="/etc/letsencrypt"
DEST_DIR="/mnt/certs"

if [ -d "$SOURCE_DIR" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Syncing Let's Encrypt directory structure from $SOURCE_DIR to $DEST_DIR"
    
    # Copy entire directory structure as-is
    cp -r "$SOURCE_DIR"/* "$DEST_DIR/"
    
    # Adjust permissions: readable files 644, private keys 600
    find "$DEST_DIR" -type f -exec chmod 644 {} \;
    find "$DEST_DIR" -name "privkey*.pem" -exec chmod 600 {} \;
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync complete. Let's Encrypt structure mirrored to: $DEST_DIR"
    ls -la "$DEST_DIR"/live/slakxs.de/
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Source directory not found: $SOURCE_DIR" >&2
    exit 1
fi
