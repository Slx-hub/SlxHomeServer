<#
.SYNOPSIS
    Prepares a bootable USB flash drive with Debian minimal (netinst) installer
    and unattended preseed configuration for SlxHomeServer.

.PARAMETER DriveLetter
    Drive letter of the USB stick (default: D).

.EXAMPLE
    .\Prepare-FlashDrive.ps1
    .\Prepare-FlashDrive.ps1 -DriveLetter E
#>

param(
    [string]$DriveLetter = "D"
)

$ErrorActionPreference = "Stop"

# ── Paths ────────────────────────────────────────────────────────────────
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$EnvFile     = Join-Path $ScriptDir ".env"
$PreseedFile = Join-Path $ScriptDir "preseed.cfg"
$LateScript  = Join-Path $ScriptDir "late-install.sh"
$DriveRoot   = "${DriveLetter}:"

# ── Validate prerequisites ───────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) {
    Write-Error "Missing .env file at $EnvFile. Copy .env.example to .env and fill in your values."
    exit 1
}
if (-not (Test-Path $PreseedFile)) {
    Write-Error "Missing preseed.cfg at $PreseedFile."
    exit 1
}
if (-not (Test-Path $LateScript)) {
    Write-Error "Missing late-install.sh at $LateScript."
    exit 1
}

# ── Load .env ────────────────────────────────────────────────────────────
$envVars = @{}
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $key, $value = $line -split '=', 2
        $envVars[$key.Trim()] = $value.Trim()
    }
}

$SshPubKeyPath = $envVars["SSH_PUBLIC_KEY_PATH"]
if (-not $SshPubKeyPath -or -not (Test-Path $SshPubKeyPath)) {
    Write-Error "SSH public key not found at '$SshPubKeyPath'. Check SSH_PUBLIC_KEY_PATH in .env."
    exit 1
}
$SshPubKey = (Get-Content $SshPubKeyPath -Raw).Trim()

$WifiSsid     = $envVars["WIFI_SSID"]
$WifiPassword  = $envVars["WIFI_PASSWORD"]

# ── Confirm drive ────────────────────────────────────────────────────────
$volume = Get-Volume -DriveLetter $DriveLetter -ErrorAction SilentlyContinue
if (-not $volume) {
    Write-Error "Drive ${DriveLetter}: not found. Insert the USB stick and try again."
    exit 1
}

Write-Warning "ALL DATA on ${DriveLetter}: ($($volume.FileSystemLabel)) will be DESTROYED."
$confirm = Read-Host "Type YES to continue"
if ($confirm -ne "YES") {
    Write-Host "Aborted." -ForegroundColor Yellow
    exit 0
}

# ── Format the drive (FAT32 for broad BIOS/UEFI compatibility) ──────────
Write-Host "Formatting ${DriveLetter}: as FAT32..." -ForegroundColor Cyan
Format-Volume -DriveLetter $DriveLetter -FileSystem FAT32 -NewFileSystemLabel "SLXSETUP" -Confirm:$false | Out-Null

# ── Download latest Debian netinst ISO ───────────────────────────────────
$IsoUrl  = "https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/"
Write-Host "Fetching latest Debian netinst ISO filename..." -ForegroundColor Cyan

$page    = Invoke-WebRequest -Uri $IsoUrl -UseBasicParsing
$isoLink = ($page.Links | Where-Object { $_.href -match "debian-\d+[\d.]*-amd64-netinst\.iso$" } | Select-Object -First 1).href

if (-not $isoLink) {
    Write-Error "Could not find a Debian netinst ISO link at $IsoUrl"
    exit 1
}

$IsoDownloadUrl = "${IsoUrl}${isoLink}"
$IsoLocal       = Join-Path $env:TEMP $isoLink

if (Test-Path $IsoLocal) {
    Write-Host "ISO already cached at $IsoLocal, skipping download." -ForegroundColor Green
} else {
    Write-Host "Downloading $IsoDownloadUrl ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $IsoDownloadUrl -OutFile $IsoLocal -UseBasicParsing
    Write-Host "Download complete." -ForegroundColor Green
}

# ── Extract ISO contents to flash drive ──────────────────────────────────
Write-Host "Mounting ISO and copying contents to ${DriveLetter}:\ ..." -ForegroundColor Cyan
$mountResult = Mount-DiskImage -ImagePath $IsoLocal -PassThru
$isoDriveLetter = ($mountResult | Get-Volume).DriveLetter

try {
    Copy-Item -Path "${isoDriveLetter}:\*" -Destination "${DriveRoot}\" -Recurse -Force
} finally {
    Dismount-DiskImage -ImagePath $IsoLocal | Out-Null
}

# ── Place preseed and supporting files ───────────────────────────────────
Write-Host "Copying preseed.cfg and setup files..." -ForegroundColor Cyan
Copy-Item -Path $PreseedFile -Destination "${DriveRoot}\preseed.cfg" -Force
Copy-Item -Path $LateScript  -Destination "${DriveRoot}\late-install.sh" -Force

# Write the SSH public key so preseed can pick it up
Set-Content -Path "${DriveRoot}\authorized_keys" -Value $SshPubKey -NoNewline

# Write wifi credentials for the late-install script
$wifiConf = @"
WIFI_SSID=$WifiSsid
WIFI_PASSWORD=$WifiPassword
"@
Set-Content -Path "${DriveRoot}\wifi.conf" -Value $wifiConf

# ── Patch boot config for automatic preseed ──────────────────────────────
# For BIOS boot (isolinux)
$isolinuxCfg = Join-Path $DriveRoot "isolinux\isolinux.cfg"
if (Test-Path $isolinuxCfg) {
    $bootEntry = @"
default auto
label auto
  kernel /install.amd/vmlinuz
  append initrd=/install.amd/initrd.gz auto=true priority=critical preseed/file=/cdrom/preseed.cfg
"@
    Set-Content -Path $isolinuxCfg -Value $bootEntry
    Write-Host "Patched isolinux.cfg for automated install." -ForegroundColor Green
}

# For UEFI boot (grub)
$grubCfg = Join-Path $DriveRoot "boot\grub\grub.cfg"
if (Test-Path $grubCfg) {
    $grubEntry = @"
set default=0
set timeout=3

menuentry 'Automated Debian Install' {
    linux  /install.amd/vmlinuz auto=true priority=critical preseed/file=/cdrom/preseed.cfg ---
    initrd /install.amd/initrd.gz
}
"@
    Set-Content -Path $grubCfg -Value $grubEntry
    Write-Host "Patched grub.cfg for automated install." -ForegroundColor Green
}

Write-Host ""
Write-Host "USB drive ${DriveLetter}: is ready. Plug it into your server and boot from USB." -ForegroundColor Green
