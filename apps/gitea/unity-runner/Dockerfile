# syntax=docker/dockerfile:1
#
# Gitea act_runner with Unity pre-installed.
# Based on GameCI's unityci/editor image, which ships Unity as the `unity-editor`
# command on PATH. act_runner is installed on top and configured to run jobs
# directly inside this container (host executor, no Docker-in-Docker).
#
# Build args (override via docker-compose build.args or --build-arg):
#   UNITY_VERSION      Unity version — must match a tag on hub.docker.com/r/unityci/editor
#   GAMECI_SCHEMA      GameCI image schema version (major)
#   ACT_RUNNER_VERSION Gitea act_runner release version

ARG UNITY_VERSION=6000.3.10f1
ARG GAMECI_SCHEMA=3

# Verify the exact tag at: https://hub.docker.com/r/unityci/editor/tags
# and adjust GAMECI_SCHEMA if needed (e.g. 3 → 3.1.0).
FROM unityci/editor:ubuntu-${UNITY_VERSION}-base-${GAMECI_SCHEMA}

# Redeclare ARGs that are needed in RUN steps (Docker clears them after FROM)
ARG UNITY_VERSION=6000.3.10f1
ARG ACT_RUNNER_VERSION=0.2.11

# ── act_runner ──────────────────────────────────────────────────────────────
RUN curl -fsSL \
      "https://gitea.com/gitea/act_runner/releases/download/v${ACT_RUNNER_VERSION}/act_runner-${ACT_RUNNER_VERSION}-linux-amd64" \
      -o /usr/local/bin/act_runner \
    && chmod +x /usr/local/bin/act_runner

# ── Upgrade Node.js + install Docker CLI ────────────────────────────────────
# Node.js: GameCI base image may ship an old version; upgrade to LTS so that
#   ioUtil.rm and crypto.randomUUID work in GitHub Actions runners.
# Docker CLI: required by game-ci/unity-activate@v2 to spin up the activation
#   container. The host socket is mounted at runtime; only the CLI is needed here.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl gnupg ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
         -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
         https://download.docker.com/linux/ubuntu \
         $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
         > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# ── Runtime setup ────────────────────────────────────────────────────────────
WORKDIR /data

COPY config.yaml    /config.yaml
COPY entrypoint.sh  /entrypoint.sh
RUN chmod +x /entrypoint.sh

# /data holds the .runner registration file — mount as a volume to persist across restarts
VOLUME ["/data"]

ENTRYPOINT ["/entrypoint.sh"]
