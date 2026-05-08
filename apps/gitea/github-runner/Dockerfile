# GitHub Actions self-hosted runner
# Based on ubuntu:22.04 with GitHub Actions runner preinstalled

FROM ubuntu:22.04

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive
ENV RUNNER_VERSION=2.318.0

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      wget \
      git \
      jq \
      docker.io \
      sudo \
      ca-certificates \
      libicu70 \
      libssl3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash runner

# Download and extract GitHub Actions runner
WORKDIR /home/runner

RUN wget -q https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz && \
    tar xzf actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz && \
    rm actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz && \
    chown -R runner:runner /home/runner

# Allow runner user to use Docker
RUN usermod -aG docker runner

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create data directory for persistent registration
RUN mkdir -p /data && chown runner:runner /data

VOLUME ["/data"]

USER runner

ENTRYPOINT ["/entrypoint.sh"]
