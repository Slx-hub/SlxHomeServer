# GitHub Actions Self-Hosted Runner

A containerized GitHub Actions runner for CI/CD workflows on self-hosted infrastructure.

## Prerequisites

- Docker and Docker Compose installed on the host
- A GitHub repository (Gitea or GitHub.com)
- A registration token (from repository Settings → Actions → Runners → New self-hosted runner)

## Setup

### Step 1: Set Environment Variables

Add these to `/.env` at the repo root:

```bash
# GitHub repository (owner/repo format)
GITHUB_REPOSITORY=your-username/your-repo

# GitHub Actions registration token (get from repo settings)
GITHUB_TOKEN=your-registration-token

# Optional: runner identity
RUNNER_NAME=github-runner
RUNNER_LABELS=self-hosted,linux
```

> **Note:** If using Gitea, you may need to adapt `GITHUB_REPOSITORY` to point to your Gitea instance. The registration token comes from your Gitea repository's Actions settings.

### Step 2: Build and Start the Runner

```bash
cd apps/gitea/github-runner
docker compose build --no-cache
docker compose up -d
```

Check logs:

```bash
docker compose logs -f runner
```

You should see:

```
runner | Configuring GitHub Actions runner for owner/repo ...
runner | Runner configuration complete.
runner | Starting GitHub Actions runner ...
runner | Current runner version: 2.318.0
...
```

### Step 3: Verify Runner Registration

Visit your repository → Settings → Actions → Runners and confirm the new runner appears as **Online**.

## Using the Runner in Workflows

Set `runs-on: self-hosted` in your workflow:

```yaml
jobs:
  test:
    runs-on: [self-hosted, linux]
    steps:
      - uses: actions/checkout@v4
      - run: echo "Running on self-hosted runner"
```

## Docker Access

The runner has access to the host Docker socket (`/var/run/docker.sock`), so workflows can spin up containers:

```yaml
steps:
  - name: Run Docker command
    run: docker ps
```

## Troubleshooting

### Runner fails to register

- Verify `GITHUB_TOKEN` is correct and not expired
- Check `GITHUB_REPOSITORY` format (must be `owner/repo`)
- Review container logs: `docker compose logs runner`

### Token format confusion

If using Gitea, the token is from your Gitea instance's Actions settings, not GitHub.com. Adjust `GITHUB_REPOSITORY` to match your Gitea repository path.

### Docker socket permission denied

If the runner can't access Docker, verify the socket is mounted:

```bash
docker compose exec -T runner docker ps
```

If that fails, the container may need elevated Docker privileges. Check your Docker daemon configuration.

## Persistence

The `/data` volume stores the runner's registration state (`.registered` file). Deleting this volume will force re-registration on next startup.

To deregister the runner:

```bash
docker compose down
docker volume rm github-actions-runner_runner-data
```

Then restart to re-register with a fresh token.

## References

- [GitHub Actions Self-Hosted Runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [GameCI Self-Hosting Guide](https://game.ci/docs/self-hosting/runner-application-installation/github-actions/)
