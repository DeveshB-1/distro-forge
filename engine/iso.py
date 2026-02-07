"""
ISO Engine — Mount, unpack, modify, and repack RHEL/CentOS ISOs.
Handles the low-level ISO manipulation.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class ISOEngine:
    """Handles ISO extraction and repacking."""

    def __init__(self, base_iso: str, work_dir: Path):
        self.base_iso = Path(base_iso)
        self.work_dir = work_dir
        self.mount_point = work_dir / "mnt"
        self.extract_dir = work_dir / "iso_root"
        self.volume_id = None

    def extract(self):
        """Extract the base ISO contents to a working directory."""
        print("⚙️  Extracting ISO...")

        self.mount_point.mkdir(parents=True, exist_ok=True)
        self.extract_dir.mkdir(parents=True, exist_ok=True)

        # Get volume ID from original ISO
        self.volume_id = self._get_volume_id()

        # Try extraction methods in order of preference:
        # xorriso (best) → mount (needs root on Linux) → 7z (fallback)
        extracted = False
        errors = []

        if shutil.which("xorriso"):
            try:
                self._extract_with_xorriso()
                extracted = True
            except subprocess.CalledProcessError as e:
                errors.append(f"xorriso: {e}")

        if not extracted:
            try:
                self._extract_with_mount()
                extracted = True
            except (PermissionError, OSError, subprocess.CalledProcessError, FileNotFoundError) as e:
                errors.append(f"mount: {e}")

        if not extracted and shutil.which("7z"):
            try:
                self._extract_with_7z()
                extracted = True
            except subprocess.CalledProcessError as e:
                errors.append(f"7z: {e}")

        if not extracted:
            raise RuntimeError(
                "Cannot extract ISO. Tried: " +
                "; ".join(errors) +
                ". Install xorriso (recommended): brew/dnf install xorriso"
            )

        print(f"  ✅ Extracted to {self.extract_dir}")
        return self.extract_dir

    def repack(self, output_path: Path, volume_id: str = None):
        """Repack the working directory into a new bootable ISO."""
        print("⚙️  Repacking ISO...")

        vol_id = volume_id or self.volume_id or "CUSTOM_ISO"

        # Detect if EFI boot is present
        efi_boot = self.extract_dir / "images" / "efiboot.img"
        isolinux_bin = self.extract_dir / "isolinux" / "isolinux.bin"
        isolinux_cat = self.extract_dir / "isolinux" / "boot.cat"

        cmd = ["xorriso", "-as", "mkisofs"]

        # Volume ID
        cmd += ["-V", vol_id]

        # BIOS boot (isolinux)
        if isolinux_bin.exists():
            cmd += [
                "-b", "isolinux/isolinux.bin",
                "-c", "isolinux/boot.cat",
                "-no-emul-boot",
                "-boot-load-size", "4",
                "-boot-info-table",
            ]

        # EFI boot
        if efi_boot.exists():
            cmd += [
                "-eltorito-alt-boot",
                "-e", "images/efiboot.img",
                "-no-emul-boot",
            ]

        # Rock Ridge + Joliet
        cmd += ["-R", "-J"]

        # Output
        cmd += ["-o", str(output_path)]

        # Source
        cmd += [str(self.extract_dir)]

        self._run(cmd)

        # Make ISO hybrid bootable (for USB)
        if shutil.which("isohybrid"):
            try:
                self._run(["isohybrid", "--uefi", str(output_path)])
            except subprocess.CalledProcessError:
                # isohybrid without --uefi
                try:
                    self._run(["isohybrid", str(output_path)])
                except subprocess.CalledProcessError:
                    print("  ⚠️  isohybrid failed, ISO may not be USB-bootable")

        # Implant MD5 checksum
        if shutil.which("implantisomd5"):
            try:
                self._run(["implantisomd5", str(output_path)])
            except subprocess.CalledProcessError:
                print("  ⚠️  implantisomd5 failed, skipping checksum")

        print(f"  ✅ ISO created: {output_path}")
        return output_path

    def cleanup(self):
        """Clean up mount points and temp dirs."""
        # Unmount if mounted
        if self.mount_point.is_mount():
            subprocess.run(["umount", str(self.mount_point)], check=False)

        # Remove mount point
        if self.mount_point.exists():
            shutil.rmtree(self.mount_point, ignore_errors=True)

    def _get_volume_id(self):
        """Get the volume ID from the ISO."""
        if shutil.which("isoinfo"):
            try:
                result = subprocess.run(
                    ["isoinfo", "-d", "-i", str(self.base_iso)],
                    capture_output=True, text=True
                )
                for line in result.stdout.splitlines():
                    if line.startswith("Volume id:"):
                        return line.split(":", 1)[1].strip()
            except Exception:
                pass

        if shutil.which("xorriso"):
            try:
                result = subprocess.run(
                    ["xorriso", "-indev", str(self.base_iso),
                     "-report_el_torito", "as_mkisofs"],
                    capture_output=True, text=True
                )
                for line in result.stdout.splitlines():
                    if "-V " in line or "-volid" in line:
                        parts = line.split("-V", 1)
                        if len(parts) > 1:
                            return parts[1].strip().strip("'\"")
            except Exception:
                pass

        return None

    def _extract_with_mount(self):
        """Extract ISO by mounting it (needs root)."""
        self._run(["mount", "-o", "loop,ro", str(self.base_iso), str(self.mount_point)])
        try:
            self._run([
                "rsync", "-a", "--progress",
                f"{self.mount_point}/", f"{self.extract_dir}/"
            ])
        finally:
            subprocess.run(["umount", str(self.mount_point)], check=False)

    def _extract_with_xorriso(self):
        """Extract ISO using xorriso."""
        # Use -abort_on NEVER to handle hybrid ISOs where some files
        # span past the ISO9660 boundary (El Torito boot partitions).
        # These files are still extracted correctly in practice.
        result = subprocess.run(
            [
                "xorriso", "-abort_on", "NEVER",
                "-osirrox", "on",
                "-indev", str(self.base_iso),
                "-extract", "/", str(self.extract_dir)
            ],
            capture_output=True, text=True
        )
        # xorriso may return non-zero even on partial success.
        # Check if we actually got files.
        extracted_files = list(self.extract_dir.iterdir())
        if not extracted_files:
            raise subprocess.CalledProcessError(
                result.returncode,
                "xorriso",
                output=result.stdout,
                stderr=result.stderr
            )
        if result.stderr and "FAILURE" in result.stderr:
            # Log warnings but don't fail — hybrid ISOs always trigger these
            failures = [l for l in result.stderr.splitlines() if "FAILURE" in l]
            for f in failures[:3]:
                print(f"  ⚠️  {f.strip()}")
            if len(failures) > 3:
                print(f"  ⚠️  ... and {len(failures) - 3} more warnings")

        # Fix permissions (xorriso extracts read-only)
        subprocess.run(
            ["chmod", "-R", "u+w", str(self.extract_dir)],
            capture_output=True
        )

    def _extract_with_7z(self):
        """Extract ISO using 7z."""
        self._run(["7z", "x", f"-o{self.extract_dir}", str(self.base_iso)])

    @staticmethod
    def _run(cmd, **kwargs):
        """Run a command, raising on failure."""
        print(f"  → {' '.join(cmd[:4])}{'...' if len(cmd) > 4 else ''}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            **kwargs
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd,
                output=result.stdout,
                stderr=result.stderr
            )
        return result
