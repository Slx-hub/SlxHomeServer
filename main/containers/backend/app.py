"""
Docker Compose Management API.
Discovers compose projects, lists services, and provides
start/stop/restart/logs operations via the Docker socket.
"""

import os
import asyncio
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
    """Walk the project tree and find all docker-compose.yml files."""
    root = Path(PROJECT_ROOT)
    results = []
    for compose_file in sorted(root.rglob("docker-compose.yml")):
        rel = compose_file.relative_to(root)
        # Name is the parent folder of the compose file
        name = str(rel.parent)
        results.append({
            "name": name,
            "path": str(compose_file),
        })
    return results


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


def _container_info(c) -> dict:
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
        "ports": _format_ports(c.attrs.get("NetworkSettings", {}).get("Ports", {})),
    }


def _format_ports(ports_dict: dict) -> list[str]:
    """Format port bindings into readable strings."""
    result = []
    if not ports_dict:
        return result
    for container_port, bindings in ports_dict.items():
        if bindings:
            for b in bindings:
                result.append(f"{b.get('HostPort', '?')}:{container_port}")
        else:
            result.append(container_port)
    return result


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
    projects = []

    for cf in compose_files:
        project_name = _compose_project_label(cf["path"])
        containers = _get_containers_for_project(project_name)
        services = [_container_info(c) for c in containers]

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
