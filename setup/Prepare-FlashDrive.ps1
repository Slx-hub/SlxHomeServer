<#
.SYNOPSIS
    Prepares a bootable USB flash drive with Debian minimal (netinst) installer
    and unattended preseed configuration for SlxHomeServer.

.DESCRIPTION
    Produces a UEFI-bootable USB (FAT32 with EFI/BOOT/bootx64.efi) with
    a fully automated Debian preseed. BIOS legacy boot is also enabled via
    the 'active' partition flag; the isolinux config is patched when present.

    Requires: PowerShell running as Administrator.

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
$WifiPassword = $envVars["WIFI_PASSWORD"]

# ── Locate the physical disk backing the drive letter ────────────────────
$partition = Get-Partition -DriveLetter $DriveLetter -ErrorAction SilentlyContinue
if (-not $partition) {
    Write-Error "Drive ${DriveLetter}: not found. Insert the USB stick and try again."
    exit 1
}
$diskNumber = ($partition | Get-Disk).Number
$diskSize   = [math]::Round(($partition | Get-Disk).Size / 1GB, 1)

# ── Confirm ──────────────────────────────────────────────────────────────
Write-Warning "ALL DATA on ${DriveLetter}: (Disk $diskNumber, ${diskSize} GB) will be DESTROYED."
$confirm = Read-Host "Type YES to continue"
if ($confirm -ne "YES") {
    Write-Host "Aborted." -ForegroundColor Yellow
    exit 0
}

# ── Partition and format the drive ───────────────────────────────────────
# Write the diskpart script as ASCII (no BOM) — diskpart silently fails on
# UTF-8 BOM which is PowerShell's default encoding for Set-Content.
# Letter assignment is intentionally left out of diskpart and done in
# PowerShell below, which is more reliable.
Write-Host "Partitioning and formatting Disk $diskNumber as FAT32..." -ForegroundColor Cyan
$diskpartFile = Join-Path $env:TEMP "slx-diskpart.txt"
$diskpartCommands = "select disk $diskNumber`r`nclean`r`ncreate partition primary`r`nactive`r`nformat fs=fat32 quick label=SLXSETUP`r`n"
[System.IO.File]::WriteAllText($diskpartFile, $diskpartCommands, [System.Text.Encoding]::ASCII)
$dpOutput = diskpart /s $diskpartFile
Remove-Item $diskpartFile -Force

# Show diskpart output so any errors are visible
$dpOutput | ForEach-Object { Write-Host "  diskpart: $_" }

# Wait for the new partition to appear on the disk
Write-Host "Waiting for partition on Disk $diskNumber..." -ForegroundColor Cyan
$newPartition = $null
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    $newPartition = Get-Partition -DiskNumber $diskNumber -ErrorAction SilentlyContinue |
                    Where-Object { $_.Type -notin @('Reserved', 'System', 'Recovery', 'Unknown') -and $_.Size -gt 1MB } |
                    Select-Object -First 1
    if ($newPartition) { break }
}
if (-not $newPartition) {
    Write-Error "No partition found on Disk $diskNumber after formatting. See diskpart output above."
    exit 1
}

# Assign our drive letter via PowerShell (avoids diskpart letter-assignment quirks)
Write-Host "Assigning drive letter ${DriveLetter}:..." -ForegroundColor Cyan
$existingLetter = $newPartition.DriveLetter
if ($existingLetter -and $existingLetter -ne $DriveLetter[0]) {
    Remove-PartitionAccessPath -DiskNumber $diskNumber -PartitionNumber $newPartition.PartitionNumber `
        -AccessPath "${existingLetter}:\" -ErrorAction SilentlyContinue
}
if (-not $newPartition.DriveLetter -or $newPartition.DriveLetter -ne $DriveLetter[0]) {
    Set-Partition -DiskNumber $diskNumber -PartitionNumber $newPartition.PartitionNumber -NewDriveLetter $DriveLetter[0]
}

# Final check: confirm the volume is visible and formatted
$ready = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    $vol = Get-Volume -DriveLetter $DriveLetter -ErrorAction SilentlyContinue
    if ($vol -and $vol.FileSystem -eq 'FAT32') { $ready = $true; break }
}
if (-not $ready) {
    Write-Error "Volume ${DriveLetter}: did not become ready. Diskpart output is shown above."
    exit 1
}
Write-Host "Volume ready (FAT32, label: $((Get-Volume -DriveLetter $DriveLetter).FileSystemLabel))." -ForegroundColor Green

# ── Download latest Debian netinst ISO ───────────────────────────────────
$IsoUrl = "https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/"
Write-Host "Fetching latest Debian netinst ISO filename..." -ForegroundColor Cyan

$page    = Invoke-WebRequest -Uri $IsoUrl -UseBasicParsing
$isoLink = ($page.Links |
            Where-Object { $_.href -match "debian-\d+[\d.]*-amd64-netinst\.iso$" } |
            Select-Object -First 1).href

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
$mountResult    = Mount-DiskImage -ImagePath $IsoLocal -PassThru
$isoDriveLetter = ($mountResult | Get-Volume).DriveLetter

try {
    Copy-Item -Path "${isoDriveLetter}:\*" -Destination "${DriveRoot}\" -Recurse -Force
} finally {
    Dismount-DiskImage -ImagePath $IsoLocal | Out-Null
}

# ISO files land read-only; strip that flag so we can overwrite boot configs below
Write-Host "Clearing read-only flags..." -ForegroundColor Cyan
Get-ChildItem -Path "${DriveRoot}\" -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }

# ── Place preseed and supporting files ───────────────────────────────────
Write-Host "Copying preseed.cfg and setup files..." -ForegroundColor Cyan
Copy-Item -Path $PreseedFile -Destination "${DriveRoot}\preseed.cfg" -Force

# late-install.sh was written on Windows (CRLF). Linux bash will see \r at the
# end of every line, making the shebang #!/bin/bash\r which is "not found" (exit 127).
# Convert to LF before writing to the drive.
$lateScriptContent = (Get-Content $LateScript -Raw) -replace "`r`n", "`n"
[System.IO.File]::WriteAllText("${DriveRoot}\late-install.sh", $lateScriptContent, [System.Text.Encoding]::UTF8)

# SSH public key (not a secret — it's the public half)
Set-Content -Path "${DriveRoot}\authorized_keys" -Value $SshPubKey -NoNewline

# Always write wifi.conf so the preseed late_command can unconditionally copy it.
# late-install.sh ignores empty values, so this is safe when Ethernet is used.
$wifiContent = "WIFI_SSID=$WifiSsid`nWIFI_PASSWORD=$WifiPassword"
[System.IO.File]::WriteAllText("${DriveRoot}\wifi.conf", $wifiContent, [System.Text.Encoding]::UTF8)
if ($WifiSsid -and $WifiPassword) {
    Write-Host "Wi-Fi credentials written." -ForegroundColor Green
} else {
    Write-Host "No Wi-Fi credentials in .env — wifi.conf written empty (Ethernet assumed)." -ForegroundColor Yellow
}

# ── Patch boot configs for fully automated (preseed) install ─────────────

# BIOS boot: isolinux
$isolinuxCfg = Join-Path $DriveRoot "isolinux\isolinux.cfg"
if (Test-Path $isolinuxCfg) {
    Set-Content -Path $isolinuxCfg -Value @"
default auto
label auto
  kernel /install.amd/vmlinuz
  append initrd=/install.amd/initrd.gz auto=true priority=critical preseed/file=/cdrom/preseed.cfg
"@
    Write-Host "Patched isolinux.cfg (BIOS boot)." -ForegroundColor Green
}

# UEFI boot: grub
# 'search --label SLXSETUP' ensures GRUB finds the right partition even if
# drive numbering differs between the EFI stub loader and GRUB's view.
$grubCfg = Join-Path $DriveRoot "boot\grub\grub.cfg"
if (Test-Path $grubCfg) {
    Set-Content -Path $grubCfg -Value @"
set default=0
set timeout=5

search --no-floppy --label --set=root SLXSETUP

menuentry 'Automated Debian Install' {
    linux  /install.amd/vmlinuz auto=true priority=critical preseed/file=/cdrom/preseed.cfg ---
    initrd /install.amd/initrd.gz
}
"@
    Write-Host "Patched grub.cfg (UEFI boot)." -ForegroundColor Green
}

Write-Host ""
Write-Host "USB drive ${DriveLetter}: is ready." -ForegroundColor Green
Write-Host "Plug it into the server, enter BIOS (Secure Boot OFF), select USB from the one-time boot menu, then walk away." -ForegroundColor Green
