"""
Branding Engine — Applies distro branding to the extracted ISO.
Handles: os-release, GRUB, Plymouth, Anaconda, release RPM, MOTD, etc.

Tested against CentOS Stream 9 boot ISO structure:
  EFI/BOOT/grub.cfg     — GRUB2 EFI menu (volume label in boot params)
  isolinux/isolinux.cfg  — Syslinux BIOS menu (volume label in boot params)
  isolinux/grub.conf     — Legacy GRUB (template vars)
  isolinux/boot.msg      — Boot message
  .discinfo              — Timestamp / version / arch
  .treeinfo              — (DVD ISOs only)
"""

import os
import re
import shutil
import glob
from pathlib import Path


class BrandingEngine:
    """Apply branding changes to an extracted ISO."""

    # Known upstream distro name patterns to replace
    UPSTREAM_PATTERNS = [
        r"CentOS\s+Stream\s+\d+",
        r"CentOS\s+Linux\s+\d+",
        r"CentOS\s+\d+",
        r"Red\s+Hat\s+Enterprise\s+Linux\s+\d+(?:\.\d+)?",
        r"Rocky\s+Linux\s+\d+(?:\.\d+)?",
        r"AlmaLinux\s+\d+(?:\.\d+)?",
        r"Fedora\s+\d+",
    ]

    def __init__(self, iso_root: Path, manifest: dict):
        self.iso_root = iso_root
        self.manifest = manifest
        self.branding = manifest.get("branding", {})
        self.name = manifest["name"]
        self.version = manifest["version"]
        self.vendor = manifest.get("vendor", "")
        self.os_id = self.branding.get("os_id", self.name.lower().replace(" ", "-"))

        # Build the new volume ID (max 32 chars)
        vol_id = f"{self.name}-{self.version}-x86_64"
        arch = manifest.get("build_system", {}).get("arch", "x86_64")
        vol_id = f"{self.name}-{self.version}-{arch}"
        if len(vol_id) > 32:
            vol_id = vol_id[:32]
        self.new_volume_id = vol_id.replace(" ", "-")

        # Detect original volume ID from grub.cfg or isolinux.cfg
        self.original_volume_id = self._detect_original_volume_id()

    def _detect_original_volume_id(self):
        """Detect the original ISO volume label from boot config files."""
        # Check grub.cfg for LABEL= reference
        grub_cfg = self.iso_root / "EFI" / "BOOT" / "grub.cfg"
        if grub_cfg.exists():
            content = grub_cfg.read_text()
            # Match: hd:LABEL=CentOS-Stream-9-BaseOS-x86_64
            match = re.search(r"hd:LABEL=(\S+)", content)
            if match:
                return match.group(1)
            # Match: search ... -l 'VOLUME-ID'
            match = re.search(r"-l\s+'([^']+)'", content)
            if match:
                return match.group(1)

        # Check isolinux.cfg
        isolinux_cfg = self.iso_root / "isolinux" / "isolinux.cfg"
        if isolinux_cfg.exists():
            content = isolinux_cfg.read_text()
            match = re.search(r"hd:LABEL=(\S+)", content)
            if match:
                return match.group(1)

        return None

    def apply_all(self):
        """Apply all branding modifications."""
        print("⚙️  Applying branding...")

        if self.original_volume_id:
            print(f"  → Original volume ID: {self.original_volume_id}")
            print(f"  → New volume ID:      {self.new_volume_id}")

        self._patch_grub_config()
        self._patch_isolinux_config()
        self._patch_grub_conf_legacy()
        self._patch_boot_msg()
        self._patch_treeinfo()
        self._patch_discinfo()
        self._copy_branding_assets()
        self._create_release_files()

        print("  ✅ Branding applied")

    def _replace_distro_name(self, text, context=""):
        """Replace any known upstream distro name with the new name."""
        for pattern in self.UPSTREAM_PATTERNS:
            text = re.sub(pattern, self.name, text, flags=re.IGNORECASE)

        # Also catch standalone references like "CentOS Stream" without version
        text = re.sub(r"CentOS\s+Stream(?!\s*\d)", self.name, text, flags=re.IGNORECASE)
        text = re.sub(r"CentOS(?!\s*Stream)(?!\s*-)", self.name, text, flags=re.IGNORECASE)
        text = re.sub(r"Red\s+Hat\s+Enterprise\s+Linux", self.name, text, flags=re.IGNORECASE)

        return text

    def _replace_volume_label(self, text):
        """Replace the original volume label with the new one in boot params."""
        if not self.original_volume_id:
            return text

        # Replace hd:LABEL=OLD_LABEL with hd:LABEL=NEW_LABEL
        text = text.replace(
            f"hd:LABEL={self.original_volume_id}",
            f"hd:LABEL={self.new_volume_id}"
        )

        # Replace search -l 'OLD_LABEL' with search -l 'NEW_LABEL'
        text = text.replace(
            f"'{self.original_volume_id}'",
            f"'{self.new_volume_id}'"
        )

        return text

    def _patch_grub_config(self):
        """Modify GRUB2 EFI boot menu entries."""
        grub_cfg = self.iso_root / "EFI" / "BOOT" / "grub.cfg"
        if not grub_cfg.exists():
            for alt in ["EFI/BOOT/BOOT.conf", "boot/grub2/grub.cfg"]:
                alt_path = self.iso_root / alt
                if alt_path.exists():
                    grub_cfg = alt_path
                    break
            else:
                print("  ⚠️  No GRUB config found, skipping")
                return

        content = grub_cfg.read_text()

        # Replace volume label references (CRITICAL for boot)
        content = self._replace_volume_label(content)

        # Replace distro names in menu entries
        content = self._replace_distro_name(content, context="grub.cfg")

        # Handle "Rescue a CentOS Stream system"
        content = re.sub(
            r"Rescue a\s+\S+(?:\s+\S+)?\s+system",
            f"Rescue a {self.name} system",
            content, flags=re.IGNORECASE
        )

        # Update timeout
        boot_timeout = self.manifest.get("boot_timeout", 60)
        content = re.sub(r"set timeout=\d+", f"set timeout={boot_timeout}", content)

        grub_cfg.write_text(content)
        print("  → EFI/BOOT/grub.cfg patched")

    def _patch_isolinux_config(self):
        """Modify isolinux/syslinux boot menu (BIOS boot)."""
        for cfg_name in ["isolinux.cfg", "syslinux.cfg"]:
            cfg_path = self.iso_root / "isolinux" / cfg_name
            if not cfg_path.exists():
                continue

            content = cfg_path.read_text()

            # Replace volume label references (CRITICAL for boot)
            content = self._replace_volume_label(content)

            # Replace menu title
            content = re.sub(
                r"menu title .*",
                f"menu title {self.name} {self.version}",
                content, flags=re.IGNORECASE
            )

            # Replace all distro name references
            content = self._replace_distro_name(content, context="isolinux.cfg")

            # Handle help text references
            content = re.sub(
                r"Rescue a\s+\S+(?:\s+\S+)?\s+system",
                f"Rescue a {self.name} system",
                content, flags=re.IGNORECASE
            )
            content = re.sub(
                r"installing\s*\n\s*CentOS\s+Stream\s*\d*",
                f"installing\n\t{self.name}",
                content, flags=re.IGNORECASE
            )

            # Timeout (isolinux uses tenths of seconds)
            boot_timeout = self.manifest.get("boot_timeout", 60)
            content = re.sub(r"^timeout \d+", f"timeout {boot_timeout}0", content, flags=re.MULTILINE)

            cfg_path.write_text(content)
            print(f"  → isolinux/{cfg_name} patched")

    def _patch_grub_conf_legacy(self):
        """Modify legacy grub.conf (isolinux/grub.conf)."""
        grub_conf = self.iso_root / "isolinux" / "grub.conf"
        if not grub_conf.exists():
            return

        content = grub_conf.read_text()
        content = self._replace_distro_name(content, context="grub.conf")

        # Update timeout
        boot_timeout = self.manifest.get("boot_timeout", 60)
        content = re.sub(r"timeout \d+", f"timeout {boot_timeout}", content)

        grub_conf.write_text(content)
        print("  → isolinux/grub.conf patched")

    def _patch_boot_msg(self):
        """Modify isolinux boot message."""
        boot_msg = self.iso_root / "isolinux" / "boot.msg"
        if not boot_msg.exists():
            return

        content = boot_msg.read_text()
        content = self._replace_distro_name(content, context="boot.msg")
        boot_msg.write_text(content)
        print("  → isolinux/boot.msg patched")

    def _patch_treeinfo(self):
        """Update .treeinfo metadata file (DVD ISOs only)."""
        treeinfo = self.iso_root / ".treeinfo"
        if not treeinfo.exists():
            # Boot ISOs don't have .treeinfo — this is normal
            return

        content = treeinfo.read_text()

        content = re.sub(r"family = .*", f"family = {self.name}", content)
        content = re.sub(r"name = .*", f"name = {self.name} {self.version}", content)
        content = re.sub(r"short = .*", f"short = {self.os_id}", content)
        content = re.sub(r"version = .*", f"version = {self.version}", content)

        treeinfo.write_text(content)
        print("  → .treeinfo patched")

    def _patch_discinfo(self):
        """
        Update .discinfo metadata file.
        Format: line 1 = timestamp, line 2 = version/release, line 3 = arch
        """
        discinfo = self.iso_root / ".discinfo"
        if not discinfo.exists():
            return

        content = discinfo.read_text().strip()
        lines = content.splitlines()

        # .discinfo format:
        # 1770004599.657164       ← timestamp (keep)
        # 9                       ← version / release string
        # x86_64                  ← arch (keep)
        if len(lines) >= 2:
            lines[1] = self.version

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

        # GRUB theme files
        grub_src = assets_path / "grub"
        if grub_src.is_dir():
            grub_dst = self.iso_root / "EFI" / "BOOT"
            grub_dst.mkdir(parents=True, exist_ok=True)
            for f in grub_src.iterdir():
                if f.is_file():
                    shutil.copy2(f, grub_dst / f.name)
            print("  → GRUB assets copied")

        # Splash image for isolinux
        splash_candidates = [
            assets_path / "grub" / "splash.png",
            assets_path / "logos" / "splash.png",
        ]
        for splash in splash_candidates:
            if splash.exists():
                dst = self.iso_root / "isolinux" / "splash.png"
                shutil.copy2(splash, dst)
                print("  → isolinux/splash.png replaced")
                break

        # Plymouth (staged for kickstart %post)
        plymouth_src = assets_path / "plymouth"
        if plymouth_src.is_dir():
            self._plymouth_assets = plymouth_src
            print("  → Plymouth assets staged (applied during install)")

        # Anaconda (installer branding → product.img)
        anaconda_src = assets_path / "anaconda"
        if anaconda_src.is_dir():
            self._create_product_img(anaconda_src)

        # Logos (staged for RPM packaging)
        logos_src = assets_path / "logos"
        if logos_src.is_dir():
            self._logos_path = logos_src
            print("  → Logos staged for RPM packaging")

    def _create_product_img(self, anaconda_src: Path):
        """
        Create a product.img to override Anaconda installer branding.
        This is overlaid on the installer's filesystem at boot.
        """
        product_dir = self.iso_root / "_product_staging"
        product_dir.mkdir(parents=True, exist_ok=True)

        # Anaconda branding lives in /usr/share/anaconda/pixmaps/
        pyanaconda_dir = product_dir / "usr" / "share" / "anaconda" / "pixmaps"
        pyanaconda_dir.mkdir(parents=True, exist_ok=True)

        for f in anaconda_src.iterdir():
            if f.is_file() and not f.name.startswith(".") and f.name != "README.md":
                shutil.copy2(f, pyanaconda_dir / f.name)

        # Create .buildstamp — tells Anaconda the product name
        buildstamp_dir = product_dir / "run" / "install" / "product"
        buildstamp_dir.mkdir(parents=True, exist_ok=True)
        buildstamp = buildstamp_dir / ".buildstamp"
        buildstamp.write_text(
            f"[Main]\n"
            f"Product={self.name}\n"
            f"Version={self.version}\n"
            f"BugURL={self.manifest.get('bug_url', '')}\n"
            f"IsFinal=True\n"
        )

        self._product_staging = product_dir
        print("  → Anaconda branding staged for product.img")

    def _create_release_files(self):
        """
        Stage custom os-release and release files.
        Injected via kickstart %post during installation.
        """
        release_dir = self.iso_root / "_release_staging"
        release_dir.mkdir(parents=True, exist_ok=True)

        # /etc/os-release
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

        # /etc/redhat-release & /etc/system-release
        for fname in [f"{self.os_id}-release", "system-release"]:
            (release_dir / fname).write_text(
                f"{self.name} release {self.version}\n"
            )

        # /etc/motd
        (release_dir / "motd").write_text(
            f"\n"
            f"  Welcome to {self.name} {self.version}\n"
            f"  {'─' * (len(self.name) + len(self.version) + 14)}\n"
            f"\n"
        )

        # /etc/issue & /etc/issue.net
        (release_dir / "issue").write_text(
            f"{self.name} {self.version}\n"
            f"Kernel \\r on an \\m\n\n"
        )

        self._release_staging = release_dir
        print("  → Release files staged")
