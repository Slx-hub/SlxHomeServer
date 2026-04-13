# Unity Runner Setup Guide

This guide walks you through setting up the Gitea Act Runner with Unity support for CI/CD testing.

## Prerequisites

- A Gitea instance running on the same Docker network
- Docker and Docker Compose installed on the host
- A Unity license (Personal, Pro, or Team)

## Step 1: Configure Environment Variables

Copy the template and fill in your values:

```bash
cp ../../.env.example ../../.env
```

Edit `/.env` and set:

```bash
# Gitea runner configuration
RUNNER_TOKEN=<your-runner-token>          # From: Gitea → Settings → Actions → Runners
GITEA_INSTANCE_URL=http://gitea:3000      # Or your Gitea service name

# Unity version
UNITY_VERSION=6000.3.10f1                  # Match desired version
GAMECI_SCHEMA=3

# Runner identity
RUNNER_NAME=unity-runner
RUNNER_LABELS=self-hosted,unity-linux:host
```

## Step 2: Set Up the Unity License (Gitea Secret)

Unity Personal licenses are machine-specific. You **cannot** use CLI activation (`-username`/`-password`)
for Personal licenses — that requires a paid plan. Instead, you must generate a license request file
**from within the container** (so it contains the container's machine ID), activate it via Unity's website,
and store the resulting license as a Gitea secret.

### 2a. Generate the license request file (`.alf`) from the container

```bash
# Create required directories
docker compose exec runner mkdir -p ~/.config/unity3d ~/.local/share/unity3d ~/.cache/unity3d

# Generate the activation request file — Unity writes it to /data/
docker compose exec runner xvfb-run -a /opt/unity/Editor/Unity \
  -batchmode -nographics \
  -createManualActivationFile \
  -logFile /tmp/alf.log

# Find the generated file
docker compose exec runner ls /data/
```

### 2b. Copy the `.alf` to your local machine

```bash
docker compose cp runner:/data/<filename>.alf ./unity.alf
```

### 2c. Activate on Unity's website

1. Go to **https://license.unity3d.com/manual**
2. Log in with your Unity account
3. Upload `unity.alf`
4. Select **Unity Personal Edition**
5. Download the resulting `.ulf` file

### 2d. Copy the `.ulf` into the volume

The license is stored on the `/data` volume alongside the runner registration file.
This way it survives container rebuilds and **no workflow step is needed**.

```bash
docker compose cp unity.ulf runner:/data/Unity_lic.ulf
```

The entrypoint will copy it to `~/.config/unity3d/` on every container start.

> **Note:** The license must be re-generated if you delete the `runner-data` Docker volume,
> since a new volume means a new machine ID. Repeat from Step 2a to get a fresh `.alf`.

## Step 3: Build and Start the Runner

```bash
docker compose build --no-cache
docker compose up -d
```

Check logs:
```bash
docker compose logs -f runner
```

You should see:
```
runner | Registering runner with http://gitea:3000 ...
runner | Registration complete.
runner | Starting act_runner daemon ...
```

## Step 4: Create a Test Workflow

Example `.gitea/workflows/test.yml`:

```yaml
name: Unity EditMode Tests

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]

concurrency:
  group: unity-tests-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  test:
    name: EditMode Tests
    runs-on: [self-hosted, unity-linux]

    if: ${{ !github.event.pull_request.draft }}

    steps:
      - name: Checkout
        uses: actions/checkout@v3

      - name: Cache Unity Library
        uses: actions/cache@v3
        with:
          path: Library
          key: Library-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}
          restore-keys: Library-

      - name: Run EditMode Tests
        run: |
          RESULTS="$GITHUB_WORKSPACE/test-results.xml"
          LOG="$GITHUB_WORKSPACE/unity.log"

          xvfb-run -a "$UNITY_PATH/Editor/Unity" \
            -runTests \
            -batchmode \
            -nographics \
            -projectPath "$GITHUB_WORKSPACE" \
            -testResults "$RESULTS" \
            -testPlatform EditMode \
            -logFile "$LOG"

          EXIT_CODE=$?
          tail -60 "$LOG" 2>/dev/null || true
          exit $EXIT_CODE

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-results-pr${{ github.event.pull_request.number }}
          path: |
            test-results.xml
            unity.log
```

## Troubleshooting

### License activation fails in the workflow

**Error:** `No valid Unity Editor license found`

- Ensure `UNITY_LICENSE` secret is set with the full `.ulf` file contents
- Verify the license is valid on your local machine first
- Check that the secret is readable in the repository

### Runner doesn't connect to Gitea

**Error:** `Failed to register runner`

- Verify `RUNNER_TOKEN` is correct and not expired
- Check `GITEA_INSTANCE_URL` is reachable from inside the container (`http://gitea:3000`)
- Verify the runner is on the same Docker network as Gitea:
  ```bash
  docker network ls
  docker network inspect main-network  # should show both gitea and runner
  ```

### `UNITY_PATH` not found in workflow

The `entrypoint.sh` auto-discovers and exports `UNITY_PATH` when the container starts. It should be inherited by all workflow steps. If it's not set:

```bash
docker compose exec -T runner echo $UNITY_PATH
```

If empty, check the entrypoint logs.

### Tests run but produce no output

- Add `-verbose` flag to the Unity command for debugging
- Check `/tmp/test.log` on the container for detailed logs
- Ensure enough disk space and memory are available
