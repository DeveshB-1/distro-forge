# 🔨 Distro Forge

Build your own RHEL/CentOS-based Linux distribution from a stock ISO.

## What It Does

Distro Forge takes a base RHEL, CentOS, or CentOS Stream ISO and transforms it into a fully rebranded, customized distribution — ready to install.

### Features

- **Interactive wizard** — answers questions, builds your distro. No YAML required.
- **Full rebranding** — OS name, GRUB, Plymouth, Anaconda installer, boot screens, release files
- **GUI management** — Enable/disable desktop environments (GNOME, KDE, XFCE, MATE, Cinnamon)
- **Custom repos** — Inject your own yum/dnf repositories
- **RPM injection** — Add custom packages directly into the ISO
- **Kickstart generation** — Automated install with your settings baked in
- **ISO repacking** — Produces a bootable, USB-hybrid ISO with checksums
- **Config reuse** — Save wizard answers as YAML, reuse for automated builds

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# System tools needed (on the build machine):
# - xorriso (ISO creation)
# - createrepo_c (repo metadata)
# - Optional: mksquashfs, isohybrid, implantisomd5

# Run the wizard
python forge.py

# Or use a saved manifest
python forge.py -c my-distro-manifest.yaml

# Save your wizard answers for later
python forge.py --save-config

# Dry run (show what would happen)
python forge.py --dry-run
```

## System Requirements

**Build machine:**
- Linux (RHEL/CentOS/Fedora recommended)
- Python 3.8+
- ~10GB free disk space (for ISO extraction + rebuild)

**Required tools:**
| Tool | Package | Purpose |
|------|---------|---------|
| `xorriso` | `xorriso` | ISO creation/extraction |
| `createrepo_c` | `createrepo_c` | Repository metadata |

**Optional tools:**
| Tool | Package | Purpose |
|------|---------|---------|
| `mksquashfs` | `squashfs-tools` | Product.img for Anaconda branding |
| `isohybrid` | `syslinux` | USB-bootable ISO |
| `implantisomd5` | `isomd5sum` | ISO integrity checksums |
| `isoinfo` | `genisoimage` | Read ISO volume info |

## How It Works

1. **Wizard** collects your distro definition (or reads from YAML)
2. **ISO Engine** extracts the base ISO
3. **Branding Engine** patches GRUB, isolinux, .treeinfo, .discinfo
4. **Package Engine** injects custom RPMs and rebuilds repo metadata
5. **Kickstart Engine** generates an automated install config with branding in %post
6. **Builder** creates product.img for Anaconda, repacks everything into a bootable ISO

## Manifest Format

```yaml
name: MyDistro
version: "1.0"
vendor: "My Organization"
base_iso: /path/to/CentOS-Stream-9-x86_64-dvd1.iso

branding:
  os_name: MyDistro
  os_id: mydistro
  grub_title: "Install MyDistro"
  anaconda_title: "MyDistro 1.0"
  assets_dir: ./assets/    # Optional

gui:
  enabled: true
  desktop: GNOME

repos:
  - name: mydistro-extras
    baseurl: https://repo.example.com/extras/
    gpgcheck: false

packages:
  install: [nginx, vim-enhanced, htop]
  remove: [centos-logos, centos-stream-release]
  local_rpms: ./rpms/     # Optional

kickstart:
  timezone: UTC
  lang: en_US.UTF-8
  keyboard: us

selinux: enforcing
firewall: true
firewall_services: [ssh, http, https]
boot_timeout: 60
post_scripts: []
```

## Project Structure

```
distro-forge/
├── forge.py              # CLI entrypoint
├── engine/
│   ├── wizard.py         # Interactive config wizard
│   ├── iso.py            # ISO mount/extract/repack
│   ├── branding.py       # OS branding & theming
│   ├── packages.py       # Repo & RPM management
│   ├── kickstart.py      # Kickstart generation
│   ├── gui.py            # Desktop environment config
│   └── builder.py        # Build pipeline orchestrator
├── config/               # Sample manifests
├── assets/               # Branding templates
├── templates/            # Kickstart templates
├── output/               # Built ISOs
├── requirements.txt
└── README.md
```

## Examples

### Minimal desktop distro
```bash
python forge.py --save-config
# Name: MyDesktopOS, Version: 1.0
# Base: CentOS-Stream-9 DVD ISO
# GUI: GNOME enabled
# Everything else: defaults
```

### Server-only distro
```bash
python forge.py -c configs/server-manifest.yaml
```

### Fully branded distro
Provide an assets directory with:
```
assets/
├── grub/         # splash.png, font.pf2, theme.txt
├── plymouth/     # logo.png, theme script
├── anaconda/     # sidebar.png, topbar.png
└── logos/        # fedora_logo.png → your_logo.png
```

## License

MIT
