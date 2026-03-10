# SlxHomeServer

Infrastructure-as-code repository for my home server. Everything needed to go from bare metal to a fully configured machine — automated, versioned, reproducible.

## Quick Start

See the **[Setup Guide](docs/setup-guide.md)** for step-by-step instructions.

## Repository Structure

```
SlxHomeServer/
├── setup/              # OS installation & initial machine setup
│   ├── .env.example    # Template for secrets (Wi-Fi, SSH key path)
│   ├── Prepare-FlashDrive.ps1  # Create bootable USB from Windows
│   ├── preseed.cfg     # Debian unattended install answers
│   ├── late-install.sh # Runs at end of OS install
│   ├── setup.sh        # Post-SSH package installation
│   └── pkglist.txt     # Packages to install
├── main/               # Service configurations (coming soon)
└── docs/               # Documentation
    └── setup-guide.md  # Full setup walkthrough
```

## Overview

1. **Prepare a USB stick** on your Windows PC (`setup/Prepare-FlashDrive.ps1`).
2. **Boot** the target machine from USB — Debian installs itself with zero user input.
3. **SSH in** and run `setup/setup.sh` to install Docker, Python, and other essentials.

That's it. From power-on to ready-to-use server.
