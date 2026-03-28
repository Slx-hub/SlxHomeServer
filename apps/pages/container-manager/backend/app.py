"""
Docker Compose Management API.
Discovers compose projects, lists services, and provides
start/stop/restart/logs operations via the Docker socket.
"""

import os
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import docker
from docker.errors import NotFound, APIError

app = FastAPI(title="Container Manager API")

PROJECT_ROOT = os.getenv("PROJECT_ROOT", "/home/slx/SlxHomeServer")

client = docker.from_env()


# ── Helpers ──────────────────────────────────────────────────────────────


def discover_compose_files() -> list[dict]:
    """Walk the project tree and find all docker-compose.yml / compose.yml files."""
    root = Path(PROJECT_ROOT)
    seen: set[Path] = set()
    results = []
    for compose_file in sorted(root.rglob("*compose.yml")):
        # Prefer docker-compose.yml; skip compose.yml if we already have
        # a docker-compose.yml for the same directory.
        if compose_file.parent in seen:
            continue
        seen.add(compose_file.parent)
        rel = compose_file.relative_to(root)
        name = str(rel.parent)
        results.append({
            "name": name,
            "path": str(compose_file),
        })
    return sorted(results, key=lambda x: x["name"])


def _compose_project_label(compose_path: str) -> str | None:
    """Derive the compose project name from the directory.
    Docker Compose uses the directory name as the project name by default.
    """
    return Path(compose_path).parent.name


def _get_containers_for_project(project_name: str) -> list:
    """Get all containers belonging to a compose project."""
    return client.containers.list(
        all=True,
        filters={"label": f"com.docker.compose.project={project_name}"},
    )


def _container_info(c, ports: str = "") -> dict:
    """Extract useful info from a container object."""
    state = c.attrs.get("State", {})
    health = state.get("Health", {})
    health_status = health.get("Status", "none")

    started_at = state.get("StartedAt", "")
    finished_at = state.get("FinishedAt", "")

    # Parse uptime
    running = state.get("Running", False)
    uptime = None
    started_iso = None
    if running and started_at and not started_at.startswith("0001"):
        started_iso = started_at
        try:
            # Docker uses RFC3339Nano; truncate to microseconds
            clean = started_at[:26].rstrip("Z") + "+00:00"
            dt = datetime.fromisoformat(clean)
            delta = datetime.now(timezone.utc) - dt
            uptime = int(delta.total_seconds())
        except (ValueError, TypeError):
            uptime = None

    service_name = c.labels.get("com.docker.compose.service", c.name)

    return {
        "id": c.short_id,
        "name": c.name,
        "service": service_name,
        "image": str(c.image.tags[0]) if c.image.tags else str(c.image.short_id),
        "status": c.status,  # running, exited, paused, etc.
        "health": health_status,  # healthy, unhealthy, starting, none
        "running": running,
        "started_at": started_iso,
        "finished_at": finished_at if not finished_at.startswith("0001") else None,
        "uptime_seconds": uptime,
        "ports": ports,
    }


def _fetch_port_strings() -> dict[str, str]:
    """Run `docker ps -a --format` once and return a full_id -> ports_string map."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=5,
        )
        mapping: dict[str, str] = {}
        for line in result.stdout.splitlines():
            cid, _, ports = line.partition("\t")
            mapping[cid.strip()] = ports.strip()
        return mapping
    except Exception:
        return {}


# ── Compose-level operations (async subprocess) ─────────────────────────


async def _compose_command(compose_path: str, command: list[str]) -> str:
    """Run a docker compose command and return combined output.
    Uses -f with the full path so the Docker daemon resolves
    relative build contexts and volumes correctly.
    """
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", compose_path, *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = stdout.decode() + stderr.decode()
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=output.strip())
    return output.strip()


# ── API Routes ───────────────────────────────────────────────────────────


@app.get("/api/projects")
def list_projects():
    """List all discovered compose projects with their service states."""
    compose_files = discover_compose_files()
    port_strings = _fetch_port_strings()
    projects = []

    for cf in compose_files:
        project_name = _compose_project_label(cf["path"])
        containers = _get_containers_for_project(project_name)
        services = [_container_info(c, port_strings.get(c.id, "")) for c in containers]

        # Determine aggregate status
        if not services:
            aggregate = "stopped"
        elif all(s["running"] for s in services):
            aggregate = "running"
        elif any(s["running"] for s in services):
            aggregate = "partial"
        else:
            aggregate = "stopped"

        # Aggregate health
        healths = [s["health"] for s in services if s["health"] != "none"]
        if any(h == "unhealthy" for h in healths):
            agg_health = "unhealthy"
        elif any(h == "starting" for h in healths):
            agg_health = "starting"
        elif healths and all(h == "healthy" for h in healths):
            agg_health = "healthy"
        else:
            agg_health = "none"

        projects.append({
            "name": cf["name"],
            "project_label": project_name,
            "compose_path": cf["path"],
            "status": aggregate,
            "health": agg_health,
            "services": sorted(services, key=lambda s: s["service"]),
        })

    return {"projects": projects}


@app.get("/api/healthz")
def api_healthz():
    """Lightweight liveness endpoint for Docker HEALTHCHECK."""
    return {"status": "ok"}


@app.post("/api/projects/{project_name:path}/up")
async def project_up(project_name: str):
    """Start a compose project."""
    cf = _find_compose(project_name)
    output = await _compose_command(cf["path"], ["up", "-d"])
    return {"output": output}


@app.post("/api/projects/{project_name:path}/down")
async def project_down(project_name: str):
    """Stop a compose project."""
    cf = _find_compose(project_name)
    output = await _compose_command(cf["path"], ["down"])
    return {"output": output}


@app.post("/api/projects/{project_name:path}/restart")
async def project_restart(project_name: str):
    """Restart a compose project."""
    cf = _find_compose(project_name)
    output = await _compose_command(cf["path"], ["restart"])
    return {"output": output}


@app.post("/api/projects/{project_name:path}/rebuild")
async def project_rebuild(project_name: str):
    """Stop, rebuild images (no cache), and restart a compose project."""
    cf = _find_compose(project_name)
    await _compose_command(cf["path"], ["down"])
    await _compose_command(cf["path"], ["build", "--no-cache"])
    output = await _compose_command(cf["path"], ["up", "-d"])
    return {"output": output}


@app.get("/api/projects/{project_name:path}/logs")
async def project_logs(
    project_name: str,
    lines: int = Query(default=100, ge=1, le=5000),
):
    """Get recent logs for the whole project."""
    cf = _find_compose(project_name)
    output = await _compose_command(cf["path"], ["logs", "--tail", str(lines), "--no-color"])
    return {"logs": output}


# ── Service-level operations ─────────────────────────────────────────────


@app.post("/api/services/{container_id}/start")
def service_start(container_id: str):
    """Start a single service container."""
    c = _find_container(container_id)
    c.start()
    return {"status": "started"}


@app.post("/api/services/{container_id}/stop")
def service_stop(container_id: str):
    """Stop a single service container."""
    c = _find_container(container_id)
    c.stop(timeout=10)
    return {"status": "stopped"}


@app.post("/api/services/{container_id}/restart")
def service_restart(container_id: str):
    """Restart a single service container."""
    c = _find_container(container_id)
    c.restart(timeout=10)
    return {"status": "restarted"}


@app.post("/api/services/{container_id}/rebuild")
async def service_rebuild(container_id: str):
    """Rebuild a single service image and restart it."""
    c = _find_container(container_id)
    service_name = c.labels.get("com.docker.compose.service")
    if not service_name:
        raise HTTPException(status_code=400, detail="Container is not part of a compose project")

    # Prefer the label that records the exact config file path.
    config_files = c.labels.get("com.docker.compose.project.config_files", "")
    compose_path = config_files.split(",")[0].strip() if config_files else ""

    if not compose_path or not Path(compose_path).exists():
        # Fall back: match by project label against our discovered files.
        project_label = c.labels.get("com.docker.compose.project", "")
        found = next(
            (cf for cf in discover_compose_files()
             if _compose_project_label(cf["path"]) == project_label),
            None,
        )
        if not found:
            raise HTTPException(status_code=404, detail=f"Compose file not found for project '{project_label}'")
        compose_path = found["path"]

    await _compose_command(compose_path, ["build", service_name])
    output = await _compose_command(compose_path, ["up", "-d", service_name])
    return {"output": output}


@app.get("/api/services/{container_id}/logs")
def service_logs(
    container_id: str,
    lines: int = Query(default=100, ge=1, le=5000),
):
    """Get recent logs for a single service."""
    c = _find_container(container_id)
    logs = c.logs(tail=lines, timestamps=True).decode("utf-8", errors="replace")
    return {"logs": logs}


# ── Lookup helpers ───────────────────────────────────────────────────────


def _find_compose(project_name: str) -> dict:
    for cf in discover_compose_files():
        if cf["name"] == project_name:
            return cf
    raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")


def _find_container(container_id: str):
    try:
        return client.containers.get(container_id)
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{container_id}' not found")
    except APIError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Serve frontend static files ─────────────────────────────────────────

app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
