# Gitea Actions Runner (act_runner)
# Lightweight container for running Gitea CI/CD jobs

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV ACT_RUNNER_VERSION=0.2.11

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      wget \
      git \
      docker.io \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash runner

WORKDIR /home/runner

# Download and extract act_runner
RUN wget -q https://gitea.com/gitea/act_runner/releases/download/v${ACT_RUNNER_VERSION}/act_runner-${ACT_RUNNER_VERSION}-linux-amd64 \
    -O /usr/local/bin/act_runner && \
    chmod +x /usr/local/bin/act_runner && \
    chown runner:runner /usr/local/bin/act_runner

# Allow runner user to use Docker
RUN usermod -aG docker runner

# Copy entrypoint and config
COPY entrypoint.sh /entrypoint.sh
COPY config.yaml /config.yaml
RUN chmod +x /entrypoint.sh && chown runner:runner /config.yaml

# Create data directory for persistent registration
RUN mkdir -p /data && chown runner:runner /data

VOLUME ["/data"]

USER runner

ENTRYPOINT ["/entrypoint.sh"]
