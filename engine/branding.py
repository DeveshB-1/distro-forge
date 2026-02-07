"""
Branding Engine — Applies distro branding to the extracted ISO.
Handles: os-release, GRUB, Plymouth, Anaconda, release RPM, MOTD, etc.
"""

import os
import re
import shutil
import glob
from pathlib import Path


class BrandingEngine:
    """Apply branding changes to an extracted ISO."""

    def __init__(self, iso_root: Path, manifest: dict):
        self.iso_root = iso_root
        self.manifest = manifest
        self.branding = manifest.get("branding", {})
        self.name = manifest["name"]
        self.version = manifest["version"]
        self.vendor = manifest.get("vendor", "")
        self.os_id = self.branding.get("os_id", self.name.lower().replace(" ", "-"))

    def apply_all(self):
        """Apply all branding modifications."""
        print("⚙️  Applying branding...")

        self._patch_grub_config()
        self._patch_isolinux_config()
        self._patch_treeinfo()
        self._patch_discinfo()
        self._copy_branding_assets()
        self._create_release_files()

        print("  ✅ Branding applied")

    def _patch_grub_config(self):
        """Modify GRUB boot menu entries."""
        grub_cfg = self.iso_root / "EFI" / "BOOT" / "grub.cfg"
        if not grub_cfg.exists():
            # Try alternate locations
            for alt in ["EFI/BOOT/BOOT.conf", "boot/grub2/grub.cfg"]:
                alt_path = self.iso_root / alt
                if alt_path.exists():
                    grub_cfg = alt_path
                    break
            else:
                print("  ⚠️  No GRUB config found, skipping")
                return

        content = grub_cfg.read_text()

        # Replace menu entry titles
        grub_title = self.branding.get("grub_title", f"Install {self.name}")
        
        # Common RHEL/CentOS patterns
        replacements = [
            (r"Install CentOS\s*\S*", f"Install {self.name}"),
            (r"Install Red Hat Enterprise Linux\s*\S*", f"Install {self.name}"),
            (r"Install CentOS Stream\s*\d*", f"Install {self.name}"),
            (r"Test this media & install CentOS\s*\S*", f"Test this media & install {self.name}"),
            (r"Test this media & install Red Hat\s*\S*", f"Test this media & install {self.name}"),
            (r"Troubleshooting", "Troubleshooting"),
        ]

        for pattern, replacement in replacements:
            content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)

        # Update timeout
        boot_timeout = self.manifest.get("boot_timeout", 60)
        content = re.sub(r"set timeout=\d+", f"set timeout={boot_timeout}", content)

        grub_cfg.write_text(content)
        print("  → GRUB config patched")

    def _patch_isolinux_config(self):
        """Modify isolinux/syslinux boot menu (BIOS boot)."""
        for cfg_name in ["isolinux.cfg", "syslinux.cfg"]:
            cfg_path = self.iso_root / "isolinux" / cfg_name
            if not cfg_path.exists():
                continue

            content = cfg_path.read_text()

            # Replace menu labels
            content = re.sub(
                r"menu title .*",
                f"menu title {self.name} {self.version}",
                content, flags=re.IGNORECASE
            )

            # Replace label text
            patterns = [
                (r"Install CentOS\s*\S*", f"Install {self.name}"),
                (r"Install Red Hat\s*\S*", f"Install {self.name}"),
                (r"Test this media.*install\s+\S+", f"Test this media & install {self.name}"),
            ]
            for pattern, replacement in patterns:
                content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)

            # Timeout
            boot_timeout = self.manifest.get("boot_timeout", 60)
            content = re.sub(r"timeout \d+", f"timeout {boot_timeout}0", content)

            cfg_path.write_text(content)
            print(f"  → {cfg_name} patched")

    def _patch_treeinfo(self):
        """Update .treeinfo metadata file."""
        treeinfo = self.iso_root / ".treeinfo"
        if not treeinfo.exists():
            print("  ⚠️  .treeinfo not found, skipping")
            return

        content = treeinfo.read_text()

        # Update family/name/short
        content = re.sub(r"family = .*", f"family = {self.name}", content)
        content = re.sub(r"name = .*", f"name = {self.name} {self.version}", content)
        content = re.sub(r"short = .*", f"short = {self.os_id}", content)
        content = re.sub(r"version = .*", f"version = {self.version}", content)

        treeinfo.write_text(content)
        print("  → .treeinfo patched")

    def _patch_discinfo(self):
        """Update .discinfo metadata file."""
        discinfo = self.iso_root / ".discinfo"
        if not discinfo.exists():
            return

        lines = discinfo.read_text().splitlines()
        if len(lines) >= 2:
            # Line 2 is typically the release name
            lines[1] = f"{self.name} {self.version}"
            discinfo.write_text("\n".join(lines) + "\n")
            print("  → .discinfo patched")

    def _copy_branding_assets(self):
        """Copy custom branding assets if provided."""
        assets_dir = self.branding.get("assets_dir")
        if not assets_dir:
            return

        assets_path = Path(assets_dir)
        if not assets_path.is_dir():
            print(f"  ⚠️  Assets directory not found: {assets_dir}")
            return

        # GRUB theme
        grub_src = assets_path / "grub"
        if grub_src.is_dir():
            grub_dst = self.iso_root / "EFI" / "BOOT"
            grub_dst.mkdir(parents=True, exist_ok=True)
            for f in grub_src.iterdir():
                shutil.copy2(f, grub_dst / f.name)
            print("  → GRUB assets copied")

        # Plymouth
        plymouth_src = assets_path / "plymouth"
        if plymouth_src.is_dir():
            # Plymouth theme goes into the initramfs — we'll handle this
            # during kickstart post-install instead
            self._plymouth_assets = plymouth_src
            print("  → Plymouth assets staged (applied during install)")

        # Anaconda (installer branding)
        anaconda_src = assets_path / "anaconda"
        if anaconda_src.is_dir():
            # Anaconda branding is typically in a product.img or updates.img
            self._create_product_img(anaconda_src)

        # Logos
        logos_src = assets_path / "logos"
        if logos_src.is_dir():
            self._logos_path = logos_src
            print("  → Logos staged for RPM packaging")

    def _create_product_img(self, anaconda_src: Path):
        """
        Create a product.img to override Anaconda installer branding.
        This is a small ext4/squashfs image that overlays the installer.
        """
        product_dir = self.iso_root / "_product_staging"
        product_dir.mkdir(parents=True, exist_ok=True)

        # Create the overlay structure
        installclass_dir = product_dir / "run" / "install" / "product"
        installclass_dir.mkdir(parents=True, exist_ok=True)

        # Copy anaconda branding files
        pyanaconda_dir = product_dir / "usr" / "share" / "anaconda" / "pixmaps"
        pyanaconda_dir.mkdir(parents=True, exist_ok=True)

        for f in anaconda_src.iterdir():
            if f.is_file():
                shutil.copy2(f, pyanaconda_dir / f.name)

        # Create .buildstamp for anaconda
        buildstamp = installclass_dir / ".buildstamp"
        buildstamp.write_text(
            f"[Main]\n"
            f"Product={self.name}\n"
            f"Version={self.version}\n"
            f"BugURL={self.manifest.get('bug_url', '')}\n"
            f"IsFinal=True\n"
        )

        # We'll pack this into product.img during the build step
        self._product_staging = product_dir
        print("  → Anaconda branding staged for product.img")

    def _create_release_files(self):
        """
        Stage custom os-release and release files.
        These will be injected via kickstart %post or custom RPM.
        """
        release_dir = self.iso_root / "_release_staging"
        release_dir.mkdir(parents=True, exist_ok=True)

        # os-release
        os_release = release_dir / "os-release"
        os_release.write_text(
            f'NAME="{self.name}"\n'
            f'VERSION="{self.version}"\n'
            f'ID="{self.os_id}"\n'
            f'ID_LIKE="rhel centos fedora"\n'
            f'VERSION_ID="{self.version}"\n'
            f'PRETTY_NAME="{self.name} {self.version}"\n'
            f'ANSI_COLOR="0;31"\n'
            f'CPE_NAME="cpe:/o:{self.os_id}:{self.os_id}:{self.version}"\n'
            f'HOME_URL="{self.manifest.get("bug_url", "")}"\n'
            f'BUG_REPORT_URL="{self.manifest.get("bug_url", "")}"\n'
        )

        # redhat-release / centos-release equivalent
        release_file = release_dir / f"{self.os_id}-release"
        release_file.write_text(f"{self.name} release {self.version}\n")

        # system-release (symlink target)
        system_release = release_dir / "system-release"
        system_release.write_text(f"{self.name} release {self.version}\n")

        # MOTD
        motd = release_dir / "motd"
        motd.write_text(
            f"\n"
            f"  Welcome to {self.name} {self.version}\n"
            f"  {'─' * (len(self.name) + len(self.version) + 14)}\n"
            f"\n"
        )

        # issue / issue.net
        issue = release_dir / "issue"
        issue.write_text(
            f"{self.name} {self.version}\n"
            f"Kernel \\r on an \\m\n\n"
        )

        self._release_staging = release_dir
        print("  → Release files staged")
