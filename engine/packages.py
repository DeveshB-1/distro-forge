"""
Package Engine — Manages repo injection, RPM handling, and dependency resolution.
Modifies the ISO's package repository and comps.xml.
"""

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


class PackageEngine:
    """Handle package and repository modifications on the ISO."""

    def __init__(self, iso_root: Path, manifest: dict):
        self.iso_root = iso_root
        self.manifest = manifest
        self.packages = manifest.get("packages", {})
        self.repos = manifest.get("repos", [])
        self.repodata_dir = self._find_repodata()

    def apply_all(self):
        """Apply all package modifications."""
        print("⚙️  Configuring packages & repos...")

        self._inject_local_rpms()
        self._rebuild_repodata()

        print("  ✅ Packages configured")

    def _find_repodata(self):
        """Find the repodata directory in the ISO."""
        candidates = [
            self.iso_root / "repodata",
            self.iso_root / "BaseOS" / "repodata",
            self.iso_root / "Packages" / "repodata",
            self.iso_root / "AppStream" / "repodata",
        ]
        for path in candidates:
            if path.is_dir():
                return path

        # Search recursively
        for dirpath, dirnames, _ in os.walk(self.iso_root):
            if "repodata" in dirnames:
                return Path(dirpath) / "repodata"

        return None

    def _find_packages_dir(self):
        """Find where RPM packages live in the ISO."""
        candidates = [
            self.iso_root / "Packages",
            self.iso_root / "BaseOS" / "Packages",
            self.iso_root / "AppStream" / "Packages",
        ]
        for path in candidates:
            if path.is_dir():
                return path

        # Check for packages in repodata parent
        if self.repodata_dir:
            pkgs = self.repodata_dir.parent / "Packages"
            if pkgs.is_dir():
                return pkgs

        return None

    def _inject_local_rpms(self):
        """Copy local RPMs into the ISO's package directory."""
        local_rpms = self.packages.get("local_rpms")
        if not local_rpms:
            return

        rpm_src = Path(local_rpms)
        if not rpm_src.is_dir():
            print(f"  ⚠️  Local RPMs directory not found: {local_rpms}")
            return

        packages_dir = self._find_packages_dir()
        if not packages_dir:
            # Create one
            packages_dir = self.iso_root / "Packages"
            packages_dir.mkdir(parents=True, exist_ok=True)

        rpm_files = list(rpm_src.glob("*.rpm"))
        if not rpm_files:
            print(f"  ⚠️  No .rpm files found in {local_rpms}")
            return

        for rpm in rpm_files:
            shutil.copy2(rpm, packages_dir / rpm.name)
            print(f"  → Injected: {rpm.name}")

        print(f"  → {len(rpm_files)} RPMs injected")

    def _rebuild_repodata(self):
        """Rebuild the repository metadata after injecting RPMs."""
        if not self.repodata_dir:
            print("  ⚠️  No repodata found, skipping rebuild")
            return

        repo_root = self.repodata_dir.parent

        # Preserve comps.xml if it exists
        comps_file = self._find_comps()

        if not shutil.which("createrepo_c") and not shutil.which("createrepo"):
            print("  ⚠️  createrepo not found, skipping repodata rebuild")
            print("    Install: dnf install createrepo_c")
            return

        cmd = ["createrepo_c" if shutil.which("createrepo_c") else "createrepo"]

        if comps_file:
            cmd += ["-g", str(comps_file)]

        cmd += ["--update", str(repo_root)]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print("  → Repodata rebuilt")
            else:
                print(f"  ⚠️  createrepo warning: {result.stderr[:200]}")
        except Exception as e:
            print(f"  ⚠️  createrepo failed: {e}")

    def _find_comps(self):
        """Find the comps.xml file in repodata."""
        if not self.repodata_dir:
            return None

        for f in self.repodata_dir.iterdir():
            if "comps" in f.name.lower() and f.name.endswith(".xml"):
                return f

        return None

    def get_install_packages(self):
        """Get list of packages to install (for kickstart)."""
        return self.packages.get("install", [])

    def get_remove_packages(self):
        """Get list of packages to remove (for kickstart)."""
        return self.packages.get("remove", [])

    def get_repo_configs(self):
        """Generate yum .repo file content for custom repos."""
        configs = []
        for repo in self.repos:
            config = (
                f"[{repo['name']}]\n"
                f"name={repo['name']}\n"
                f"baseurl={repo['baseurl']}\n"
                f"enabled={1 if repo.get('enabled', True) else 0}\n"
                f"gpgcheck={1 if repo.get('gpgcheck', False) else 0}\n"
            )
            if repo.get("gpgkey"):
                config += f"gpgkey={repo['gpgkey']}\n"
            configs.append({"name": repo["name"], "content": config})
        return configs
