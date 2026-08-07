# downloads

Stable public URLs for the newest release asset of a Gitea repo.

```
https://slakxs.de/download/cykle          → streams the newest full-release Cykle*.zip
https://slakxs.de/download/cykle/info     → JSON: tag, filename, size, published_at
https://slakxs.de/download/cykle/versions → JSON: every pinnable tag, newest first
```

## Pinning a version

Append a tag to fall back to an older build when the newest one is broken:

```
https://slakxs.de/download/cykle/0.0.1        → streams that release's asset
https://slakxs.de/download/cykle/0.0.1/info   → JSON for that release
```

A leading `v` is optional in both directions, so `/0.0.1` finds a release tagged
`v0.0.1` and vice versa. Pinning ignores the target's prerelease policy — naming
the tag is explicit enough, so this is also how you reach a prerelease.
`/versions` lists exactly the tags that resolve, i.e. those carrying an asset
that matches the pattern, each flagged with `prerelease`.

Unknown tags 404 rather than silently falling back to latest, so a stale link in
a changelog fails loudly. The lookup walks up to 100 releases back (`/versions`
covers the same range); older ones are unreachable by design.

No cookie required — this is the one slice of `git.slakxs.de` content deliberately
exposed anonymously.

## Why this exists

Gitea has no GitHub-style `/releases/latest/download/<file>` route, and its
`/releases/latest` route ignores drafts *and* prereleases, so it 404s on a repo
whose only release is a prerelease. A moving `latest` tag does not fix this
either: Gitea attaches assets to the release, not the tag, so every build would
have to re-upload the same archive to a second `latest` release.

Instead this service queries `/api/v1/repos/{owner}/{repo}/releases`, picks the
newest non-draft, non-prerelease release that actually carries a matching asset
(or the one whose tag was requested), and streams the bytes through. Range
requests are forwarded, so downloads are resumable.

## Adding a download

Edit `DOWNLOADS` in [backend/app.py](backend/app.py):

```python
DOWNLOADS = {
    "cykle": Target(owner="slakxs", repo="Slothydra", asset="Cykle*.zip"),
}
```

`asset` is an `fnmatch` pattern matched case-insensitively, so versioned
filenames (`Cykle-1.2.3.zip`) keep working. The bare slug resolves to full
releases only; set `allow_prerelease=True` on a target if its prereleases should
count as latest too.

That dict is the security boundary: only the listed repos are reachable, and
only via their asset pattern. **The repo must be public in Gitea** — the API is
called unauthenticated on purpose, so flipping a repo to private breaks the
download instead of quietly leaking it.

Rebuild after editing:

```bash
docker compose up -d --build
```
