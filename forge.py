#!/usr/bin/env python3
"""
Distro Forge — RHEL/CentOS-based Distro Builder
Takes a stock RHEL/CentOS ISO and rebrands it into your own distro.
Interactive wizard collects all info, then builds the ISO end-to-end.
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from engine.wizard import run_wizard
from engine.iso import ISOEngine
from engine.branding import BrandingEngine
from engine.packages import PackageEngine
from engine.kickstart import KickstartEngine
from engine.gui import GUIEngine
from engine.builder import Builder

BANNER = r"""
╔══════════════════════════════════════════╗
║  🔨 Distro Forge                        ║
║  RHEL/CentOS-based Distro Builder       ║
╚══════════════════════════════════════════╝
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
    args = parser.parse_args()

    print(BANNER)

    # ── Collect config ──────────────────────────────────────────
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

    # ── Optionally save config ──────────────────────────────────
    if args.save_config and not args.config:
        import yaml
        save_path = Path(args.output) / f"{manifest['name']}-{manifest['version']}-manifest.yaml"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)
        print(f"💾 Manifest saved: {save_path}")

    # ── Show summary ────────────────────────────────────────────
    print_summary(manifest)

    if args.dry_run:
        print("\n🏜️  Dry run — nothing was modified.")
        sys.exit(0)

    # ── Confirm ─────────────────────────────────────────────────
    confirm = input("\nProceed? (y/n): ").strip().lower()
    if confirm not in ("y", "yes"):
        print("❌ Aborted.")
        sys.exit(1)

    # ── Build ───────────────────────────────────────────────────
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    builder = Builder(manifest, output_dir)
    try:
        iso_path = builder.run()
        print(f"\n✅ Done! → {iso_path}")
    except Exception as e:
        print(f"\n❌ Build failed: {e}")
        sys.exit(1)


def print_summary(manifest):
    """Print a human-readable summary of the build config."""
    gui_str = "Disabled"
    if manifest.get("gui", {}).get("enabled"):
        gui_str = manifest["gui"].get("desktop", "GNOME").upper()

    repos = manifest.get("repos", [])
    pkgs_install = manifest.get("packages", {}).get("install", [])
    pkgs_remove = manifest.get("packages", {}).get("remove", [])

    print("\n" + "─" * 44)
    print("📋 Build Summary")
    print("─" * 44)
    print(f"  Name:      {manifest['name']} {manifest['version']}")
    print(f"  Base ISO:  {manifest['base_iso']}")
    print(f"  GUI:       {gui_str}")
    print(f"  Repos:     {len(repos)} custom")
    print(f"  Packages:  +{len(pkgs_install)}, -{len(pkgs_remove)}")
    branding = manifest.get("branding", {})
    if branding.get("assets_dir"):
        print(f"  Branding:  {branding['assets_dir']}")
    else:
        print(f"  Branding:  Auto-generated")
    print("─" * 44)


if __name__ == "__main__":
    main()
