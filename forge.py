#!/usr/bin/env python3
"""
Distro Forge — RHEL/CentOS-based Distro Builder
Build your own Linux distro by remastering an existing ISO
or composing from scratch using upstream repos.
"""

import os
import sys
import shutil
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from engine.wizard import run_wizard

BANNER = r"""
╔══════════════════════════════════════════════╗
║  🔨 Distro Forge                             ║
║  RHEL/CentOS-based Distro Builder            ║
║                                              ║
║  Modes:                                      ║
║    Remaster  — Rebrand an existing ISO       ║
║    Build     — Compose from upstream repos   ║
╚══════════════════════════════════════════════╝
"""

def main():
    parser = argparse.ArgumentParser(
        description="Distro Forge — Build your own RHEL/CentOS-based distro"
    )
    parser.add_argument(
        "-c", "--config",
        help="Path to a manifest YAML (skip interactive wizard)",
        default=None
    )
    parser.add_argument(
        "-o", "--output",
        help="Output directory (default: ./output)",
        default="./output"
    )
    parser.add_argument(
        "--save-config",
        help="Save wizard answers to YAML for reuse",
        action="store_true"
    )
    parser.add_argument(
        "--dry-run",
        help="Show what would be done without executing",
        action="store_true"
    )
    parser.add_argument(
        "--check-deps",
        help="Check if all required tools are installed and exit",
        action="store_true"
    )
    parser.add_argument(
        "--generate-assets",
        help="Generate a sample branding assets directory structure",
        metavar="DIR"
    )
    args = parser.parse_args()

    print(BANNER)

    # ── Generate sample assets ──────────────────────────────
    if args.generate_assets:
        generate_sample_assets(args.generate_assets)
        sys.exit(0)

    # ── Dependency check ────────────────────────────────────
    if args.check_deps:
        check_dependencies()
        sys.exit(0)

    # ── Collect config ──────────────────────────────────────
    if args.config:
        import yaml
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"❌ Config file not found: {args.config}")
            sys.exit(1)
        with open(config_path) as f:
            manifest = yaml.safe_load(f)
        print(f"📄 Loaded manifest: {args.config}")
    else:
        manifest = run_wizard()

    if not manifest:
        print("\n❌ Aborted.")
        sys.exit(1)

    # ── Generate sample assets if requested ─────────────────
    if manifest.get("generate_sample_assets"):
        assets_dir = Path(args.output) / f"{manifest['name']}-assets"
        generate_sample_assets(str(assets_dir))
        manifest["branding"]["assets_dir"] = str(assets_dir)

    # ── Optionally save config ──────────────────────────────
    if args.save_config and not args.config:
        import yaml
        save_path = Path(args.output) / f"{manifest['name']}-{manifest['version']}-manifest.yaml"
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Don't save passwords to YAML
        save_manifest = manifest.copy()
        if "kickstart" in save_manifest:
            ks = save_manifest["kickstart"].copy()
            if ks.get("root_password_value"):
                ks["root_password_value"] = "REDACTED"
            save_manifest["kickstart"] = ks

        with open(save_path, "w") as f:
            yaml.dump(save_manifest, f, default_flow_style=False, sort_keys=False)
        print(f"💾 Manifest saved: {save_path}")

    # ── Show summary ────────────────────────────────────────
    print_summary(manifest)

    if args.dry_run:
        print("\n🏜️  Dry run — nothing was modified.")
        sys.exit(0)

    # ── Confirm ─────────────────────────────────────────────
    confirm = input("\nProceed? (y/n): ").strip().lower()
    if confirm not in ("y", "yes"):
        print("❌ Aborted.")
        sys.exit(1)

    # ── Build ───────────────────────────────────────────────
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    build_mode = manifest.get("build_mode", "remaster")

    if build_mode == "build_system":
        # Build from scratch
        from engine.buildsystem import BuildSystem
        builder = BuildSystem(manifest, output_dir)
        try:
            iso_path = builder.run()
            print(f"\n✅ Done! → {iso_path}")
        except Exception as e:
            print(f"\n❌ Build failed: {e}")
            sys.exit(1)
    else:
        # Remaster existing ISO
        from engine.builder import Builder
        builder = Builder(manifest, output_dir)
        try:
            iso_path = builder.run()
            print(f"\n✅ Done! → {iso_path}")
        except Exception as e:
            print(f"\n❌ Build failed: {e}")
            sys.exit(1)


def print_summary(manifest):
    """Print a human-readable summary of the build config."""
    build_mode = manifest.get("build_mode", "remaster")

    gui_str = "Disabled"
    if manifest.get("gui", {}).get("enabled"):
        gui_str = manifest["gui"].get("desktop", "GNOME").upper()

    repos = manifest.get("repos", [])
    pkgs_install = manifest.get("packages", {}).get("install", [])
    pkgs_remove = manifest.get("packages", {}).get("remove", [])

    print("\n" + "─" * 50)
    print("📋 Build Summary")
    print("─" * 50)
    print(f"  Mode:      {'🔨 Build System' if build_mode == 'build_system' else '💿 Remaster'}")
    print(f"  Name:      {manifest['name']} {manifest['version']}")

    if build_mode == "build_system":
        bs = manifest.get("build_system", {})
        print(f"  Upstream:  {bs.get('upstream', 'unknown')}")
        print(f"  Arch:      {bs.get('arch', 'x86_64')}")
        print(f"  Tool:      {bs.get('tool', 'lorax')}")
    else:
        print(f"  Base ISO:  {manifest.get('base_iso', 'N/A')}")

    print(f"  GUI:       {gui_str}")
    print(f"  Repos:     {len(repos)} custom")
    print(f"  Packages:  +{len(pkgs_install)}, -{len(pkgs_remove)}")

    branding = manifest.get("branding", {})
    if branding.get("assets_dir"):
        print(f"  Branding:  {branding['assets_dir']}")
    else:
        print(f"  Branding:  Auto-generated (text only)")

    print(f"  SELinux:   {manifest.get('selinux', 'enforcing')}")
    print(f"  Firewall:  {'Enabled' if manifest.get('firewall') else 'Disabled'}")
    print("─" * 50)


def check_dependencies():
    """Check and report on all required/optional dependencies."""
    print("🔍 Checking dependencies...\n")

    required = {
        "python3": "Python 3.8+",
        "xorriso": "ISO creation & extraction",
        "createrepo_c": "Repository metadata (fallback: createrepo)",
    }

    optional = {
        "lorax": "Build system — compose install trees",
        "pungi-koji": "Build system — full production composes",
        "mock": "Build system — RPM building in chroot",
        "mksquashfs": "Product.img for Anaconda branding",
        "isohybrid": "USB-bootable ISO creation",
        "implantisomd5": "ISO integrity checksums",
        "isoinfo": "Read ISO volume information",
        "7z": "Alternative ISO extraction",
    }

    print("  Required:")
    all_ok = True
    for tool, desc in required.items():
        found = shutil.which(tool)
        status = "✅" if found else "❌"
        if not found:
            all_ok = False
        print(f"    {status} {tool:20s} — {desc}")

    # Special check: createrepo or createrepo_c
    if not shutil.which("createrepo_c"):
        if shutil.which("createrepo"):
            print(f"    ✅ {'createrepo':20s} — (fallback for createrepo_c)")
        else:
            print(f"    ❌ {'createrepo_c':20s} — Repository metadata")
            all_ok = False

    print("\n  Optional:")
    for tool, desc in optional.items():
        found = shutil.which(tool)
        status = "✅" if found else "⬜" 
        print(f"    {status} {tool:20s} — {desc}")

    # Check Python packages
    print("\n  Python packages:")
    try:
        import yaml
        print(f"    ✅ {'PyYAML':20s} — YAML manifest support")
    except ImportError:
        print(f"    ❌ {'PyYAML':20s} — pip install PyYAML")

    print()
    if all_ok:
        print("  ✅ All required dependencies satisfied!")
    else:
        print("  ❌ Some required dependencies are missing.")
        print("     Install them with: dnf install <package>")


def generate_sample_assets(target_dir):
    """Generate a sample branding assets directory structure."""
    target = Path(target_dir)
    print(f"📁 Generating sample assets structure at: {target}\n")

    dirs = [
        target / "grub",
        target / "plymouth",
        target / "anaconda",
        target / "logos",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # GRUB theme template
    (target / "grub" / "theme.txt").write_text(
        "# GRUB Theme — customize this\n"
        "# See: https://www.gnu.org/software/grub/manual/grub/html_node/Theme-file-format.html\n"
        "\n"
        "title-text: \"\"\n"
        "desktop-color: \"#1a1a2e\"\n"
        "terminal-font: \"DejaVu Sans Mono Regular 14\"\n"
        "\n"
        "+ boot_menu {\n"
        "  left = 15%\n"
        "  top = 25%\n"
        "  width = 70%\n"
        "  height = 50%\n"
        "  item_font = \"DejaVu Sans Regular 16\"\n"
        "  item_color = \"#cccccc\"\n"
        "  selected_item_color = \"#ffffff\"\n"
        "  item_height = 30\n"
        "  item_spacing = 5\n"
        "}\n"
    )

    # Plymouth theme template
    (target / "plymouth" / "README.md").write_text(
        "# Plymouth Boot Splash\n\n"
        "Place your Plymouth theme files here:\n"
        "- `*.plymouth` — theme descriptor\n"
        "- `*.script` — animation script\n"
        "- `*.png` — splash images / logo\n\n"
        "Example minimal theme:\n"
        "```\n"
        "[Plymouth Theme]\n"
        "Name=MyDistro\n"
        "Description=MyDistro boot splash\n"
        "ModuleName=script\n"
        "\n"
        "[script]\n"
        "ImageDir=/usr/share/plymouth/themes/mydistro\n"
        "ScriptFile=/usr/share/plymouth/themes/mydistro/mydistro.script\n"
        "```\n"
    )

    # Anaconda branding template
    (target / "anaconda" / "README.md").write_text(
        "# Anaconda Installer Branding\n\n"
        "Place your installer images here:\n"
        "- `sidebar-logo.png` — sidebar logo (approximately 300x600)\n"
        "- `topbar-bg.png` — topbar background\n"
        "- `banner-bg.png` — banner background\n"
        "- `progress-first.png` — install progress first screen\n\n"
        "These get packed into `product.img` and overlaid\n"
        "on the Anaconda installer at boot time.\n"
    )

    # Logos template
    (target / "logos" / "README.md").write_text(
        "# OS Logos\n\n"
        "Place your distro logos here:\n"
        "- `logo.png` — main logo (256x256 recommended)\n"
        "- `logo.svg` — vector logo\n"
        "- `logo-small.png` — small variant (64x64)\n"
        "- `watermark.png` — GNOME/GDM watermark\n"
        "- `favicon.ico` — for any web interfaces\n"
    )

    print("  Created:")
    print(f"    📁 {target}/grub/         — GRUB theme template")
    print(f"    📁 {target}/plymouth/     — Plymouth splash readme")
    print(f"    📁 {target}/anaconda/     — Installer branding readme")
    print(f"    📁 {target}/logos/        — Logo placement guide")
    print(f"\n  Fill in your assets and point the wizard to this directory.")


if __name__ == "__main__":
    main()
