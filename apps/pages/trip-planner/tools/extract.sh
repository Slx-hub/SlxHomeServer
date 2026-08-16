#!/usr/bin/env bash
# Run extract_page.py in its own container. Builds the image on first use.
#
# --network host is required, not incidental: the CDP fallback talks to the
# tunnel on the host's 127.0.0.1:9222, which a bridge-networked container
# cannot reach.
#
# Usage: ./extract.sh <url> [--no-cdp|--cdp-only] [--port 9222]
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE="slx-page-extract:1"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "==> building $IMAGE (first run only)..." >&2
    docker build -q -t "$IMAGE" "$DIR" >&2
fi

exec docker run --rm --network host -v "$DIR:/tools:ro" "$IMAGE" \
    python /tools/extract_page.py "$@"
