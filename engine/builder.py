"""
Builder — Orchestrates the full distro build pipeline.
Coordinates all engines: ISO → Branding → Packages → Kickstart → Repack.
"""

import os
import shutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

from engine.iso import ISOEngine
from engine.branding import BrandingEngine
from engine.packages import PackageEngine
from engine.kickstart import KickstartEngine
from engine.gui import GUIEngine


class Builder:
    """Main build orchestrator."""

    def __init__(self, manifest: dict, output_dir: Path):
        self.manifest = manifest
        self.output_dir = output_dir
        self.name = manifest["name"]
        self.version = manifest["version"]
        self.os_id = manifest.get("branding", {}).get(
            "os_id", self.name.lower().replace(" ", "-")
        )

        # Work directory — temp space for ISO manipulation
        self.work_dir = Path(tempfile.mkdtemp(prefix="distro-forge-"))

    def run(self):
        """Execute the full build pipeline."""
        print(f"\n{'═' * 50}")
        print(f"  Building {self.name} {self.version}")
        print(f"  Work dir: {self.work_dir}")
        print(f"{'═' * 50}\n")

        try:
            # ── Step 1: Extract ISO ─────────────────────────
            iso_engine = ISOEngine(self.manifest["base_iso"], self.work_dir)
            iso_root = iso_engine.extract()

            # ── Step 2: Apply Branding ──────────────────────
            branding_engine = BrandingEngine(iso_root, self.manifest)
            branding_engine.apply_all()

            # ── Step 3: Handle Packages ─────────────────────
            pkg_engine = PackageEngine(iso_root, self.manifest)
            pkg_engine.apply_all()

            # ── Step 4: GUI Configuration ───────────────────
            gui_engine = GUIEngine(self.manifest)

            # ── Step 5: Generate Kickstart ──────────────────
            ks_engine = KickstartEngine(iso_root, self.manifest)
            ks_engine.generate(
                packages_install=pkg_engine.get_install_packages(),
                packages_remove=pkg_engine.get_remove_packages(),
                repo_configs=pkg_engine.get_repo_configs()
            )

            # ── Step 6: Create product.img if needed ────────
            self._create_product_img(iso_root, branding_engine)

            # ── Step 7: Repack ISO ──────────────────────────
            output_filename = f"{self.name}-{self.version}-x86_64.iso"
            output_path = self.output_dir / output_filename

            # Use the same volume ID that the branding engine
            # patched into the boot configs (CRITICAL for boot)
            vol_id = branding_engine.new_volume_id

            iso_engine.repack(output_path, volume_id=vol_id)

            # ── Step 8: Generate checksum ───────────────────
            self._generate_checksums(output_path)

            return output_path

        except Exception as e:
            print(f"\n❌ Build failed at: {e}")
            raise

        finally:
            # ── Cleanup ─────────────────────────────────────
            print("\n⚙️  Cleaning up...")
            try:
                iso_engine.cleanup()
            except Exception:
                pass
            # Keep work dir for debugging? Make configurable later.
            print(f"  → Work dir preserved: {self.work_dir}")
            print(f"    (delete manually when done: rm -rf {self.work_dir})")

    def _create_product_img(self, iso_root: Path, branding_engine: BrandingEngine):
        """
        Create a product.img overlay for Anaconda branding.
        This overlays the installer to show custom branding.
        """
        staging_dir = iso_root / "_product_staging"
        if not staging_dir.exists():
            return

        product_img = iso_root / "images" / "product.img"
        product_img.parent.mkdir(parents=True, exist_ok=True)

        print("⚙️  Creating product.img...")

        # Try creating with mksquashfs
        if shutil.which("mksquashfs"):
            try:
                subprocess.run(
                    ["mksquashfs", str(staging_dir), str(product_img),
                     "-noappend", "-no-progress"],
                    capture_output=True, text=True, check=True
                )
                print("  → product.img created (squashfs)")
            except subprocess.CalledProcessError as e:
                print(f"  ⚠️  mksquashfs failed: {e.stderr[:200]}")
        else:
            # Fall back to cpio archive
            try:
                result = subprocess.run(
                    ["bash", "-c",
                     f"cd {staging_dir} && find . | cpio -o -H newc | gzip > {product_img}"],
                    capture_output=True, text=True, check=True
                )
                print("  → product.img created (cpio)")
            except subprocess.CalledProcessError as e:
                print(f"  ⚠️  product.img creation failed: {e.stderr[:200]}")

        # Cleanup staging
        shutil.rmtree(staging_dir, ignore_errors=True)

        # Also clean release staging
        release_staging = iso_root / "_release_staging"
        if release_staging.exists():
            shutil.rmtree(release_staging, ignore_errors=True)

    def _generate_checksums(self, iso_path: Path):
        """Generate SHA256 checksum file."""
        print("⚙️  Generating checksums...")

        if shutil.which("sha256sum"):
            cmd = "sha256sum"
        elif shutil.which("shasum"):
            cmd = "shasum -a 256"
        else:
            print("  ⚠️  No checksum tool found, skipping")
            return

        checksum_file = iso_path.with_suffix(".iso.sha256")
        try:
            result = subprocess.run(
                f"{cmd} {iso_path}",
                shell=True, capture_output=True, text=True
            )
            if result.returncode == 0:
                checksum_file.write_text(result.stdout)
                print(f"  → Checksum: {checksum_file}")
        except Exception:
            print("  ⚠️  Checksum generation failed")
