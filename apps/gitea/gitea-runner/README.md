# Gitea CI Runner

A clean, lightweight Gitea act_runner for self-hosted CI/CD workflows.

## Prerequisites

- Docker and Docker Compose installed
- A Gitea repository
- A registration token from the repository (Settings → Actions → Runners → Create new runner)

## Setup

### Step 1: Set Environment Variables

Add these to `/.env`:

```bash
# Gitea instance URL (reachable from inside the container)
GITEA_INSTANCE_URL=http://gitea:3000

# Registration token (from Gitea repo Settings → Actions → Runners)
GITEA_RUNNER_REGISTRATION_TOKEN=your-token-here

# Optional: runner identity
GITEA_RUNNER_NAME=gitea-runner
GITEA_RUNNER_LABELS=self-hosted,linux:host
```

### Step 2: Build and Start

```bash
cd apps/gitea/gitea-runner
docker compose build --no-cache
docker compose up -d
docker compose logs -f runner
```

You should see:

```
runner | Registering runner with http://gitea:3000 ...
runner | Registration complete.
runner | Starting act_runner daemon ...
```

### Step 3: Verify Registration

Visit: Gitea → Repository → Settings → Actions → Runners

The runner should appear as **Online**.

## Using in Workflows

Create a `.gitea/workflows/test.yml`:

```yaml
name: Example Workflow

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    name: Test Job
    runs-on: [self-hosted, linux]

    steps:
      - uses: actions/checkout@v3

      - name: Run tests
        run: |
          echo "Running on Gitea runner"
          # Your test commands here
```

## Persistence

The `/data` volume stores the registration file (`.runner`). Deleting the volume forces re-registration on next startup.

To deregister:

```bash
docker compose down
docker volume rm gitea-runner_runner-data
```

Then rebuild and start with a fresh token.

## Docker Access

Workflows can use Docker:

```yaml
steps:
  - name: Run Docker container
    run: docker run ubuntu echo "Hello from Docker"
```

## Troubleshooting

### Runner fails to register

- Check `GITEA_RUNNER_REGISTRATION_TOKEN` is correct
- Verify `GITEA_INSTANCE_URL` is reachable from inside the container
- Review logs: `docker compose logs runner`

### Token format

The token format differs between Gitea and GitHub. Make sure you're using the **Gitea** token from repo Settings → Actions → Runners, not a GitHub token.

### Docker socket permission denied

If workflows can't access Docker:

```bash
docker compose exec -T runner docker ps
```

If this fails, verify the socket is mounted correctly and the runner user has Docker permissions.
