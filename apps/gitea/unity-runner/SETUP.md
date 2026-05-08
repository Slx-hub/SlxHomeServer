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

## Step 2: Set Up the Unity License

The runner uses `game-ci/unity-activate@v2` to handle license activation. This action runs a Docker container that writes the `.ulf` directly to disk, bypassing the machine ID check — so your local `.ulf` works as-is.

### 2a. Get the `.ulf` file from your local machine

Activate Unity Hub on any computer with your account, then locate the license file:

- **Windows:** `C:\ProgramData\Unity\Unity_lic.ulf`
- **macOS:** `/Library/Application Support/Unity/Unity_lic.ulf`
- **Linux:** `~/.local/share/unity3d/Unity/Unity_lic.ulf`

> **Tip:** If the file doesn't exist, open Unity Hub → Preferences → Licenses → Activate a new license → Personal.

### 2b. Add secrets to Gitea

Go to your repository → **Settings → Secrets** and add:

| Secret | Value |
|---|---|
| `UNITY_LICENSE` | Full contents of your `.ulf` file (XML) |
| `UNITY_EMAIL` | Your Unity account email |
| `UNITY_PASSWORD` | Your Unity account password |

### 2c. Add the activation step to your workflow

```yaml
- name: Activate Unity License
  uses: game-ci/unity-activate@v2
  env:
    UNITY_EMAIL: ${{ secrets.UNITY_EMAIL }}
    UNITY_PASSWORD: ${{ secrets.UNITY_PASSWORD }}
    UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
```

> This step spawns a Docker container via the host Docker socket. The runner has `/var/run/docker.sock` mounted for this purpose.

> **Known issue:** `game-ci/unity-activate@v2` has a regex bug that fails to match Unity 6 version strings. If activation fails silently, try pinning to `game-ci/unity-activate@main` instead.

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
        uses: game-ci/unity-test-runner@v4
        id: tests
        env:
          UNITY_EMAIL: ${{ secrets.UNITY_EMAIL }}
          UNITY_PASSWORD: ${{ secrets.UNITY_PASSWORD }}
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
        with:
          testMode: EditMode
          useHostNetwork: true

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-results-pr${{ github.event.pull_request.number }}
          path: ${{ steps.tests.outputs.artifactsPath }}
```

## Troubleshooting

### License activation fails in the workflow

**Error:** `No valid Unity Editor license found`

- Ensure `UNITY_LICENSE`, `UNITY_EMAIL`, and `UNITY_PASSWORD` secrets are set on the repository
- Verify the `.ulf` content was pasted in full (it starts with `<?xml` and ends with `</root>`)
- Unity 6 has a known version-regex bug in `game-ci/unity-activate@v2` — try `game-ci/unity-activate@main` if activation silently fails
- Check Docker socket access: `docker compose exec runner docker ps` should succeed

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
