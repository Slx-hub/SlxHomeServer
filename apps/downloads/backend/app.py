"""Public release downloads.

Maps a stable public URL (slakxs.de/download/<slug>) onto the newest matching
full-release asset in Gitea, or onto a specific tag — prerelease or not — with
slakxs.de/download/<slug>/<version> when the newest one is broken.

Why a service instead of a Caddy rewrite: Gitea has no GitHub-style
/releases/latest/download/<file> route, and its /releases/latest route skips
prereleases and drafts entirely. Resolving through the API here means no moving
"latest" tag to maintain and no re-uploading the same asset to a second release
on every build.

The asset is streamed rather than redirected to, because git.slakxs.de itself
sits behind the dev-role cookie gate — an anonymous client could not follow a
redirect there.
"""

import fnmatch
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

GITEA_URL = os.environ.get("GITEA_URL", "http://gitea:3000")
# How long a resolved release is reused before we ask Gitea again.
CACHE_TTL = int(os.environ.get("CACHE_TTL", "60"))
# Releases per API page, and how many pages we are willing to walk. Resolving
# "latest" on a target that accepts prereleases only ever needs the first page;
# skipping prereleases, or finding a pinned version, may have to page further
# back through the history.
PAGE_SIZE = 20
LATEST_PAGES = 1
VERSION_PAGES = 5


@dataclass(frozen=True)
class Target:
    owner: str
    repo: str
    asset: str  # fnmatch pattern, matched case-insensitively
    # Whether a prerelease may answer /download/<slug>. Off by default: the
    # bare URL is the one handed to end users, so it points at the newest full
    # release. Prereleases stay reachable by pinning their tag.
    allow_prerelease: bool = False


# Public download slugs. This dict is the security boundary: only the repos
# listed here are reachable, and only through their asset pattern. The repos
# must be public in Gitea — we talk to the API unauthenticated on purpose, so
# a repo flipped to private stops resolving instead of silently leaking.
DOWNLOADS = {
    "cykle": Target(owner="slakxs", repo="Slothydra", asset="Cykle*.zip"),
}

# Upstream headers worth forwarding to the client. Everything else (cookies,
# CSRF tokens, Gitea's cache directives) is dropped.
PASSTHROUGH = {
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "etag",
    "last-modified",
}

# Keyed by (slug, requested version). Only successful resolutions are stored
# and a version only resolves if Gitea actually has that tag, so the key space
# stays bounded by the real release history rather than by client input.
_cache: dict[tuple[str, str | None], tuple[float, dict]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(
        base_url=GITEA_URL,
        timeout=httpx.Timeout(10.0, read=300.0),
    ) as client:
        app.state.gitea = client
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def normalize_tag(tag: str) -> str:
    """Loosen tag comparison so /download/cykle/0.1.0 finds a `v0.1.0` release."""
    return tag.strip().lower().removeprefix("v")


async def fetch_releases(
    target: Target, client: httpx.AsyncClient, pages: int
) -> list[dict]:
    """Non-draft releases, newest first, over at most `pages` API pages."""
    releases: list[dict] = []
    for page in range(1, pages + 1):
        resp = await client.get(
            f"/api/v1/repos/{target.owner}/{target.repo}/releases",
            params={"limit": PAGE_SIZE, "page": page},
        )
        if resp.status_code == 404:
            raise HTTPException(404, "repository not found")
        resp.raise_for_status()
        batch = resp.json()
        releases.extend(r for r in batch if not r.get("draft"))
        if len(batch) < PAGE_SIZE:
            break
    # Same ISO-8601 shape for every entry, so lexical sort is chronological.
    releases.sort(
        key=lambda r: r.get("published_at") or r.get("created_at") or "",
        reverse=True,
    )
    return releases


def match_asset(release: dict, pattern: str) -> dict | None:
    assets = [
        a for a in release.get("assets", [])
        if fnmatch.fnmatch(a.get("name", "").lower(), pattern)
    ]
    if not assets:
        return None
    assets.sort(key=lambda a: a.get("created_at") or "", reverse=True)
    return assets[0]


def describe(slug: str, release: dict, asset: dict) -> dict:
    return {
        "slug": slug,
        "tag": release["tag_name"],
        "release": release.get("name") or release["tag_name"],
        "prerelease": bool(release.get("prerelease")),
        "published_at": release.get("published_at"),
        "filename": asset["name"],
        "size": asset.get("size"),
    }


async def resolve(
    slug: str,
    target: Target,
    client: httpx.AsyncClient,
    version: str | None = None,
) -> dict:
    """Release of `target` carrying a matching asset.

    Without `version` that is the newest full release — a prerelease only
    answers the bare slug on a target that opts into it. With `version`, the
    release whose tag matches, so a client can pin an older build when the
    newest is broken; that ignores the prerelease policy entirely, since asking
    for the tag by name is explicit enough.
    """
    cached = _cache.get((slug, version))
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    # One page is enough only when any release will do; otherwise the newest
    # full release can sit behind a run of prereleases.
    stable_only = version is None and not target.allow_prerelease
    pages = LATEST_PAGES if (version is None and not stable_only) else VERSION_PAGES
    releases = await fetch_releases(target, client, pages)

    if version is None:
        if stable_only:
            releases = [r for r in releases if not r.get("prerelease")]
    else:
        wanted = normalize_tag(version)
        releases = [r for r in releases if normalize_tag(r.get("tag_name", "")) == wanted]
        if not releases:
            raise HTTPException(404, f"no release tagged {version!r}")

    pattern = target.asset.lower()
    for release in releases:
        asset = match_asset(release, pattern)
        if asset is None:
            continue
        info = describe(slug, release, asset)
        _cache[(slug, version)] = (now, info)
        return info

    if version is not None:
        raise HTTPException(404, f"release {version!r} carries no matching asset")
    if stable_only:
        # Likely a repo that has only ever shipped prereleases; say so rather
        # than quietly serving one, since those are still pinnable by tag.
        raise HTTPException(
            404, "no full release carries a matching asset — see /versions"
        )
    raise HTTPException(404, "no release asset matches this download")


def target_for(slug: str) -> Target:
    target = DOWNLOADS.get(slug)
    if target is None:
        raise HTTPException(404, "unknown download")
    return target


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "downloads": sorted(DOWNLOADS)}


# Declaration order matters: /info and /versions must be registered before the
# catch-all /{slug}/{version} or they would be read as version numbers.
@app.api_route("/{slug}/info", methods=["GET", "HEAD"])
async def info(slug: str, request: Request):
    target = target_for(slug)
    return await resolve(slug, target, request.app.state.gitea)


@app.api_route("/{slug}/versions", methods=["GET", "HEAD"])
async def versions(slug: str, request: Request):
    """Tags a client can pin, newest first — only those with a usable asset."""
    target = target_for(slug)
    releases = await fetch_releases(target, request.app.state.gitea, VERSION_PAGES)
    pattern = target.asset.lower()
    return {
        "slug": slug,
        "versions": [
            {
                "tag": r["tag_name"],
                "prerelease": bool(r.get("prerelease")),
                "published_at": r.get("published_at"),
                "filename": asset["name"],
                "size": asset.get("size"),
            }
            for r in releases
            if (asset := match_asset(r, pattern)) is not None
        ],
    }


@app.api_route("/{slug}/{version}/info", methods=["GET", "HEAD"])
async def version_info(slug: str, version: str, request: Request):
    target = target_for(slug)
    return await resolve(slug, target, request.app.state.gitea, version)


@app.api_route("/{slug}", methods=["GET", "HEAD"])
async def download(slug: str, request: Request):
    return await stream(slug, None, request)


@app.api_route("/{slug}/{version}", methods=["GET", "HEAD"])
async def download_version(slug: str, version: str, request: Request):
    return await stream(slug, version, request)


async def stream(slug: str, version: str | None, request: Request):
    target = target_for(slug)
    client: httpx.AsyncClient = request.app.state.gitea
    meta = await resolve(slug, target, client, version)

    path = (
        f"/{target.owner}/{target.repo}/releases/download/"
        f"{quote(meta['tag'], safe='')}/{quote(meta['filename'], safe='')}"
    )
    # identity encoding keeps aiter_raw() a straight byte copy, so the
    # upstream Content-Length stays truthful.
    headers = {"Accept-Encoding": "identity"}
    if rng := request.headers.get("range"):
        headers["Range"] = rng

    upstream = await client.send(
        client.build_request(request.method, path, headers=headers),
        stream=True,
        follow_redirects=True,
    )
    if upstream.status_code >= 400:
        await upstream.aclose()
        # The release existed a moment ago; treat a miss as an upstream fault.
        raise HTTPException(502, f"gitea returned {upstream.status_code}")

    out = {k: v for k, v in upstream.headers.items() if k.lower() in PASSTHROUGH}
    out["content-disposition"] = f'attachment; filename="{meta["filename"]}"'
    out["x-release-tag"] = meta["tag"]

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(body(), status_code=upstream.status_code, headers=out)
