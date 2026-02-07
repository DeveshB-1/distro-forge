# 🔨 Distro Forge

Build your own RHEL/CentOS-based Linux distribution — from an existing ISO or from scratch.

## Two Modes

### 💿 Remaster Mode
Takes a stock RHEL/CentOS/Rocky/Alma ISO and transforms it into your fully branded distro.

### 🔨 Build System Mode
Composes a fresh ISO from upstream repos using `lorax` or `pungi`. No base ISO needed — pulls packages directly from mirrors.

## Features

- **Interactive wizard** — answers questions, builds your distro. No YAML required.
- **Full rebranding** — OS name, GRUB, Plymouth, Anaconda installer, boot screens, release files
- **GUI management** — Enable/disable desktop environments (GNOME, KDE, XFCE, MATE, Cinnamon)
- **Custom repos** — Inject your own yum/dnf repositories
- **RPM injection** — Add custom packages directly into the ISO
- **Kickstart generation** — Automated install with your settings baked in
- **Build system** — Compose from upstream (CentOS Stream, Rocky, Alma) using lorax or pungi
- **Multi-arch** — x86_64 and aarch64 support (build system mode)
- **ISO repacking** — Produces a bootable, USB-hybrid ISO with checksums
- **Config reuse** — Save wizard answers as YAML, reuse for automated/CI builds

## Quick Start

```bash
# Install Python dependency
pip install -r requirements.txt

# Run the wizard (choose remaster or build system)
python forge.py

# Check if all tools are installed
python forge.py --check-deps

# Generate sample branding assets directory
python forge.py --generate-assets ./my-branding

# Use a saved manifest
python forge.py -c my-distro-manifest.yaml

# Save wizard answers for later
python forge.py --save-config

# Dry run (show what would happen)
python forge.py --dry-run
```

## System Requirements

**Build machine:** Linux (RHEL/CentOS/Fedora recommended), Python 3.8+, 10GB+ free disk

### Remaster Mode — Required Tools
| Tool | Package | Purpose |
|------|---------|---------|
| `xorriso` | `xorriso` | ISO creation/extraction |
| `createrepo_c` | `createrepo_c` | Repository metadata |

### Build System Mode — Required Tools
| Tool | Package | Purpose |
|------|---------|---------|
| `lorax` | `lorax` | Compose install trees (lighter) |
| `pungi-koji` | `pungi` | Full production composes (heavier) |
| `mock` | `mock` | RPM building in chroot |
| `createrepo_c` | `createrepo_c` | Repository metadata |
| `xorriso` | `xorriso` | ISO creation |

### Optional Tools (both modes)
| Tool | Package | Purpose |
|------|---------|---------|
| `mksquashfs` | `squashfs-tools` | Product.img for Anaconda branding |
| `isohybrid` | `syslinux` | USB-bootable ISO |
| `implantisomd5` | `isomd5sum` | ISO integrity checksums |
| `isoinfo` | `genisoimage` | Read ISO volume info |

**Quick install (Fedora/CentOS/RHEL):**
```bash
sudo dnf install xorriso createrepo_c lorax squashfs-tools syslinux isomd5sum
```

## How It Works

### Remaster Mode
1. **Wizard** collects your distro definition (or reads from YAML)
2. **ISO Engine** extracts the base ISO (mount/xorriso/7z fallback)
3. **Branding Engine** patches GRUB, isolinux, .treeinfo, .discinfo
4. **Package Engine** injects custom RPMs and rebuilds repo metadata
5. **Kickstart Engine** generates an automated install config with branding in `%post`
6. **Builder** creates `product.img` for Anaconda, repacks into a bootable ISO

### Build System Mode
1. **Wizard** collects config including upstream source selection
2. **Repo Setup** configures upstream + custom repositories
3. **Compose** runs `lorax` or `pungi-koji` to build the install tree from packages
4. **Branding** applies your branding to the composed output
5. **ISO Creation** packages everything into a bootable ISO with checksums

## Manifest Format

```yaml
# Build mode: "remaster" or "build_system"
build_mode: remaster  # or build_system

name: MyDistro
version: "1.0"
vendor: "My Organization"

# ── Remaster mode only ──
base_iso: /path/to/CentOS-Stream-9-x86_64-dvd1.iso

# ── Build system mode only ──
build_system:
  upstream: centos-stream-9    # or rocky-9, alma-9, custom
  arch: x86_64                 # or aarch64
  tool: lorax                  # or pungi
  # For custom upstream:
  # upstream_repos:
  #   baseos: https://mirror.example.com/baseos/x86_64/os/
  #   appstream: https://mirror.example.com/appstream/x86_64/os/

branding:
  os_name: MyDistro
  os_id: mydistro
  grub_title: "Install MyDistro"
  anaconda_title: "MyDistro 1.0"
  assets_dir: ./assets/

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
  local_rpms: ./rpms/

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

## Branding Assets

Generate a starter template:
```bash
python forge.py --generate-assets ./my-branding
```

This creates:
```
my-branding/
├── grub/           # GRUB theme (theme.txt, splash.png, font)
├── plymouth/       # Boot splash (theme script + images)
├── anaconda/       # Installer branding (sidebar, topbar images)
└── logos/          # OS logos (PNG, SVG, watermarks)
```

## Project Structure

```
distro-forge/
├── forge.py                # CLI entrypoint
├── engine/
│   ├── wizard.py           # Interactive config wizard
│   ├── iso.py              # ISO mount/extract/repack
│   ├── branding.py         # OS branding & theming
│   ├── packages.py         # Repo & RPM management
│   ├── kickstart.py        # Kickstart generation
│   ├── gui.py              # Desktop environment config
│   ├── builder.py          # Remaster pipeline orchestrator
│   └── buildsystem.py      # Build-from-scratch compose engine
├── config/                 # Sample manifests
├── assets/                 # Branding templates
├── templates/              # Kickstart templates
├── output/                 # Built ISOs
├── requirements.txt
├── LICENSE                 # MIT
├── CONTRIBUTING.md
└── README.md
```

## Examples

### Quick remaster
```bash
python forge.py
# → Choose "Remaster"
# → Point to CentOS-Stream-9 ISO
# → Name it, brand it, done
```

### Build from CentOS Stream 9
```bash
python forge.py
# → Choose "Build System"
# → Select centos-stream-9 upstream
# → Pick lorax, customize packages
# → Compose and get ISO
```

### CI/CD automated build
```bash
python forge.py -c manifests/production.yaml -o /builds/ --save-config
```

## Supported Upstreams (Build System)

| Upstream | Status |
|----------|--------|
| CentOS Stream 9 | ✅ |
| CentOS Stream 10 | ✅ |
| Rocky Linux 9 | ✅ |
| AlmaLinux 9 | ✅ |
| Custom repos | ✅ |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
