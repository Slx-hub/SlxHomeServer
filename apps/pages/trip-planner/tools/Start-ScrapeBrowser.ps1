<#
.SYNOPSIS
    Launches a dedicated Chrome/Edge profile with CDP enabled and reverse-forwards
    it to SlxHomeServer, so the headless server can drive a real browser.

.DESCRIPTION
    The trip-planner backend cannot fetch bot-walled pages (booking.com, airbnb.com,
    tripadvisor.com). This script exposes a real, logged-in browser on this PC to the
    server over SSH, so the pin-enrichment batch can render those pages properly.

    Run this, leave it running, then do the batch on the server. Ctrl+C tears down the
    tunnel; the browser stays open for the next run.

    Requires: an SSH host alias with a RemoteForward (see -SshHost). Add to
    C:\Users\<you>\.ssh\config:

        Host SlxHomeServer-cdp
          HostName 192.168.178.69
          User slx
          PubKeyAuthentication yes
          IdentityFile ~/.ssh/id_ed25519
          RemoteForward 9222 127.0.0.1:9222
          ExitOnForwardFailure yes
          RequestTTY no

    Keep this separate from the plain SlxHomeServer alias that VS Code Remote-SSH uses:
    with ExitOnForwardFailure, a stale port on the server would otherwise break the
    connection your editor depends on.

.PARAMETER Port
    CDP port, used on both ends of the tunnel (default: 9222).

.PARAMETER Browser
    'auto' (default), 'chrome', or 'edge'.

.PARAMETER ProfileDir
    Profile directory for the scrape browser. A profile SEPARATE from your daily one is
    mandatory — current Chrome silently ignores --remote-debugging-port on the default
    profile. Log into booking/airbnb here once and it persists across runs.

.PARAMETER SshHost
    SSH host alias carrying the RemoteForward (default: SlxHomeServer-cdp).

.PARAMETER SkipTunnel
    Launch and verify the browser but don't open the tunnel.

.EXAMPLE
    .\Start-ScrapeBrowser.ps1
    .\Start-ScrapeBrowser.ps1 -Browser edge -Port 9333
    .\Start-ScrapeBrowser.ps1 -SkipTunnel
#>

param(
    [int]$Port = 9222,
    [ValidateSet("auto", "chrome", "edge")]
    [string]$Browser = "auto",
    [string]$ProfileDir = "$env:USERPROFILE\chrome-scrape",
    [string]$SshHost = "SlxHomeServer-cdp",
    [switch]$SkipTunnel,
    [switch]$ForceRemote
)

$ErrorActionPreference = "Stop"

$CdpBase = "http://127.0.0.1:$Port"

# ── Helpers ──────────────────────────────────────────────────────────────
function Get-CdpVersion {
    # Returns the /json/version payload, or $null if nothing is answering CDP there.
    try {
        return Invoke-RestMethod -Uri "$CdpBase/json/version" -TimeoutSec 3
    } catch {
        return $null
    }
}

# ── Locate the browser ───────────────────────────────────────────────────
$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$edgePaths = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)

switch ($Browser) {
    "chrome" { $candidates = $chromePaths }
    "edge"   { $candidates = $edgePaths }
    default  { $candidates = $chromePaths + $edgePaths }
}

$BrowserExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $BrowserExe) {
    Write-Error "No browser found. Looked for:`n  $($candidates -join "`n  ")"
    exit 1
}

# Edge defaults to its own profile dir so the two browsers never share one.
if ($BrowserExe -like "*msedge.exe*" -and $ProfileDir -eq "$env:USERPROFILE\chrome-scrape") {
    $ProfileDir = "$env:USERPROFILE\edge-scrape"
}

# ── Preflight: SSH alias actually carries a RemoteForward ────────────────
# Checked before launching anything, so a config typo fails in a second rather
# than after the browser is up.
if (-not $SkipTunnel) {
    if (-not (Get-Command ssh.exe -ErrorAction SilentlyContinue)) {
        Write-Error "ssh.exe not found. Install the Windows OpenSSH client (Settings > Optional features)."
        exit 1
    }
    $effective = & ssh.exe -G $SshHost 2>$null
    $forward   = $effective | Where-Object { $_ -match "^remoteforward\s" }
    if (-not $forward) {
        Write-Warning "Host alias '$SshHost' has no RemoteForward configured."
        Write-Host "Add this to $env:USERPROFILE\.ssh\config (see this script's header):" -ForegroundColor Yellow
        Write-Host "  Host $SshHost"
        Write-Host "    HostName 192.168.178.69"
        Write-Host "    User slx"
        Write-Host "    IdentityFile ~/.ssh/id_ed25519"
        Write-Host "    RemoteForward $Port 127.0.0.1:$Port"
        Write-Host "    ExitOnForwardFailure yes"
        exit 1
    }

    # The server-side port must be free. sshd keeps a forward bound when its client
    # dies without closing cleanly (dropped wifi, sleep, killed terminal) — the
    # listener outlives the connection and the next attempt fails with
    # "remote port forwarding failed for listen port $Port".
    # Filter written without quotes: ss takes the trailing tokens as the expression,
    # which avoids a second layer of shell quoting through ssh.
    $checkCmd   = "ss -ltn sport = :$Port 2>/dev/null | tail -n +2"
    $remoteHeld = & ssh.exe $SshHost $checkCmd 2>$null

    if ($remoteHeld) {
        if ($ForceRemote) {
            Write-Host "Port $Port held on the server — clearing the stale forward..." -ForegroundColor Yellow
            # Single-quoted in PowerShell so $(...) and $pid reach the remote shell
            # intact. Only ever kills the process bound to this exact port.
            $killCmd = 'pid=$(ss -ltnp sport = :PORT 2>/dev/null | grep -o "pid=[0-9]*" | head -1 | cut -d= -f2); if [ -n "$pid" ]; then kill "$pid" && echo "killed $pid"; else echo "no owner found"; fi'
            $killCmd = $killCmd -replace 'PORT', $Port
            & ssh.exe $SshHost $killCmd | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
            Start-Sleep -Seconds 1

            if (& ssh.exe $SshHost $checkCmd 2>$null) {
                Write-Error "Port $Port is still held on the server after the kill. Inspect it there with: ss -ltnp sport = :$Port"
                exit 1
            }
            Write-Host "Server port $Port released." -ForegroundColor Green
        } else {
            Write-Warning "Port $Port is already bound on the server — the tunnel would fail with 'remote port forwarding failed'."
            Write-Host "Usually a forward left behind by an SSH client that died without closing cleanly." -ForegroundColor Yellow
            Write-Host "Re-run with -ForceRemote to clear it, or inspect it by hand:" -ForegroundColor Yellow
            Write-Host "  ssh $SshHost `"ss -ltnp sport = :$Port`"" -ForegroundColor Yellow
            exit 1
        }
    }
}

# ── Start the browser (or reuse one already listening) ───────────────────
$version = Get-CdpVersion
if ($version) {
    Write-Host "CDP already live on port $Port — reusing it." -ForegroundColor Green
    Write-Host "  $($version.Browser)" -ForegroundColor DarkGray
} else {
    # Something on the port that isn't CDP means a port clash, not a stale browser.
    $inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($inUse) {
        Write-Error "Port $Port is in use but not answering CDP. Free it or pass -Port <other>."
        exit 1
    }

    Write-Host "Launching $(Split-Path $BrowserExe -Leaf) with CDP on port $Port..." -ForegroundColor Cyan
    Write-Host "  profile: $ProfileDir" -ForegroundColor DarkGray

    # --user-data-dir is load-bearing, not hygiene: without it the debug port is
    # silently ignored on the default profile.
    # Deliberately NOT passing --remote-allow-origins=*: that would let any page
    # open in this browser drive CDP itself. Add it only if a client fails the
    # websocket origin check.
    # The profile path is quoted explicitly — -ArgumentList joins the array on
    # spaces without quoting, so an unquoted path under e.g. "C:\Users\Jan S\"
    # would be split into two arguments.
    $chromeArgs = @(
        "--remote-debugging-port=$Port",
        "--user-data-dir=`"$ProfileDir`"",
        "--no-first-run",
        "--no-default-browser-check"
    )
    Start-Process -FilePath $BrowserExe -ArgumentList $chromeArgs | Out-Null

    Write-Host "Waiting for CDP to come up..." -ForegroundColor Cyan
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        $version = Get-CdpVersion
        if ($version) { break }
    }
    if (-not $version) {
        Write-Error "CDP did not come up on port $Port after 20s. If a browser window opened anyway, the profile dir is likely being shared with a running instance — close all windows of that browser and retry."
        exit 1
    }
    Write-Host "CDP live: $($version.Browser)" -ForegroundColor Green
}

# ── Tunnel ───────────────────────────────────────────────────────────────
if ($SkipTunnel) {
    Write-Host ""
    Write-Host "Browser ready; tunnel skipped (-SkipTunnel)." -ForegroundColor Yellow
    Write-Host "Open it yourself with: ssh -N $SshHost" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Opening reverse tunnel to $SshHost (server 127.0.0.1:$Port -> this PC)..." -ForegroundColor Cyan
Write-Host "Verify from the server with:  curl -s 127.0.0.1:$Port/json/version" -ForegroundColor DarkGray
Write-Host "Ctrl+C closes the tunnel. The browser stays open." -ForegroundColor DarkGray
Write-Host ""

# Foreground on purpose: the tunnel's lifetime is this window, so there's no
# orphaned forward left holding the port on the server for the next run.
$startedAt = Get-Date
& ssh.exe -N $SshHost
$code    = $LASTEXITCODE
$elapsed = ((Get-Date) - $startedAt).TotalSeconds

Write-Host ""
# Ctrl+C and a rejected forward both exit 255, so the code alone can't tell them
# apart. Duration can: ExitOnForwardFailure aborts within a second, whereas a
# tunnel you actually used was up for a while.
if ($elapsed -lt 5) {
    Write-Warning "ssh exited after $([math]::Round($elapsed, 1))s (code $code) — the tunnel never came up."
    Write-Host "If it said 'remote port forwarding failed', port $Port is held on the server." -ForegroundColor Yellow
    Write-Host "Re-run with -ForceRemote to clear it." -ForegroundColor Yellow
} elseif ($code -eq 0 -or $code -eq 255) {
    Write-Host "Tunnel closed after $([math]::Round($elapsed / 60, 1)) min." -ForegroundColor Green
} else {
    Write-Warning "ssh exited with code $code after $([math]::Round($elapsed, 1))s."
}
