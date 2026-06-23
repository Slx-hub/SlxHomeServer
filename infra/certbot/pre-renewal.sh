#!/bin/sh
# Pre-renewal hook: Stop reverse-proxy to free up port 80 for ACME challenge

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pre-renewal: Stopping reverse-proxy to free port 80..."

if command -v docker &> /dev/null; then
    docker stop reverse-proxy 2>/dev/null || echo "Reverse-proxy not running or already stopped"
    sleep 2
else
    echo "WARNING: docker not found in PATH, cannot stop reverse-proxy"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Port 80 is now available for ACME validation"
