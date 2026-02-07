"""
Koji Rebuild Engine — Rebuild branding/release RPMs from source.

Instead of rebuilding ALL packages (thousands), this focuses on the
packages that contain distro branding and identity. Everything else
is pulled pre-built from upstream.

Branding packages to rebuild:
  - centos-release / redhat-release → your-distro-release
  - centos-logos / redhat-logos → your-distro-logos
  - centos-backgrounds → your-distro-backgrounds
  - centos-indexhtml → your-distro-indexhtml
  - system-release (virtual provide)

Pipeline:
  1. Download SRPMs for branding packages
  2. Patch spec files (rename, rebrand)
  3. Inject custom assets (logos, backgrounds)
  4. Build new RPMs via Koji or mock
  5. Sign with your GPG key (optional)
  6. Push to your repo
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime


class KojiRebuilder:
    """
    Rebuild branding RPMs from source using Koji or mock.

    Supports two backends:
      - koji: Full Koji build system (needs a running Koji hub)
      - mock: Local builds in a chroot (simpler, no server needed)
    """

    # Branding SRPMs to look for and rebuild
    BRANDING_PACKAGES = {
        "centos-stream": [
            "centos-stream-release",
            "centos-logos",
            "centos-backgrounds",
            "centos-indexhtml",
        ],
        "centos": [
            "centos-release",
            "centos-logos",
            "centos-backgrounds",
            "centos-indexhtml",
        ],
        "rocky": [
            "rocky-release",
            "rocky-logos",
            "rocky-backgrounds",
            "rocky-indexhtml",
        ],
        "alma": [
            "almalinux-release",
            "almalinux-logos",
            "almalinux-backgrounds",
            "almalinux-indexhtml",
        ],
    }

    def __init__(self, manifest: dict, output_dir: Path):
        self.manifest = manifest
        self.output_dir = output_dir
        self.name = manifest["name"]
        self.version = manifest["version"]
        self.os_id = manifest.get("branding", {}).get(
            "os_id", self.name.lower().replace(" ", "-")
        )
        self.vendor = manifest.get("vendor", self.name)

        rebuild_config = manifest.get("rebuild", {})
        self.backend = rebuild_config.get("backend", "mock")  # mock or koji
        self.koji_hub = rebuild_config.get("koji_hub", None)
        self.koji_tag = rebuild_config.get("koji_tag", None)
        self.mock_config = rebuild_config.get("mock_config", "centos-stream-9-x86_64")
        self.gpg_key_id = rebuild_config.get("gpg_key_id", None)
        self.upstream = rebuild_config.get("upstream", "centos-stream")

        self.work_dir = Path(tempfile.mkdtemp(prefix="distro-forge-koji-"))
        self.srpms_dir = self.work_dir / "srpms"
        self.rpms_dir = self.work_dir / "rpms"
        self.specs_dir = self.work_dir / "specs"
        self.sources_dir = self.work_dir / "sources"

        for d in [self.srpms_dir, self.rpms_dir, self.specs_dir, self.sources_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def check_environment(self):
        """Verify build tools are available."""
        print("⚙️  Checking rebuild environment...")

        required = {}
        if self.backend == "koji":
            required["koji"] = "koji"
        else:
            required["mock"] = "mock"

        required["rpm"] = "rpm"
        required["rpmbuild"] = "rpm-build"
        required["rpmdev-setuptree"] = "rpmdevtools"

        missing = []
        for tool, package in required.items():
            if not shutil.which(tool):
                missing.append(f"{tool} (dnf install {package})")

        if missing:
            print("  ❌ Missing required tools:")
            for m in missing:
                print(f"    - {m}")
            return False

        print(f"  ✅ Backend: {self.backend}")
        return True

    def run(self):
        """Execute the full rebuild pipeline."""
        print(f"\n{'═' * 50}")
        print(f"  Koji Rebuild — {self.name} branding packages")
        print(f"  Backend: {self.backend}")
        print(f"  Upstream: {self.upstream}")
        print(f"  Work dir: {self.work_dir}")
        print(f"{'═' * 50}\n")

        if not self.check_environment():
            raise RuntimeError("Missing required build tools.")

        try:
            # Step 1: Download source RPMs
            srpms = self._download_srpms()

            # Step 2: Unpack and patch spec files
            patched_specs = self._patch_specs(srpms)

            # Step 3: Inject custom assets
            self._inject_assets()

            # Step 4: Build RPMs
            built_rpms = self._build_rpms(patched_specs)

            # Step 5: Sign RPMs (optional)
            if self.gpg_key_id:
                self._sign_rpms(built_rpms)

            # Step 6: Copy to output
            output_rpms_dir = self.output_dir / "rpms"
            output_rpms_dir.mkdir(parents=True, exist_ok=True)
            for rpm in built_rpms:
                shutil.copy2(rpm, output_rpms_dir / rpm.name)
                print(f"  → {rpm.name}")

            print(f"\n✅ {len(built_rpms)} RPMs built → {output_rpms_dir}")
            return built_rpms

        except Exception as e:
            print(f"\n❌ Rebuild failed: {e}")
            raise
        finally:
            print(f"\n  Work dir: {self.work_dir}")

    def _download_srpms(self):
        """Download source RPMs for branding packages."""
        print("⚙️  Downloading source RPMs...")

        packages = self.BRANDING_PACKAGES.get(self.upstream, [])
        if not packages:
            print(f"  ⚠️  No known branding packages for upstream: {self.upstream}")
            print("  Attempting generic centos-stream packages...")
            packages = self.BRANDING_PACKAGES["centos-stream"]

        srpms = []
        for pkg in packages:
            srpm = self._download_srpm(pkg)
            if srpm:
                srpms.append(srpm)

        if not srpms:
            raise RuntimeError("Could not download any source RPMs")

        print(f"  ✅ Downloaded {len(srpms)} SRPMs")
        return srpms

    def _download_srpm(self, package_name):
        """Download a single SRPM using dnf/yumdownloader."""
        print(f"  → Downloading SRPM: {package_name}")

        # Try dnf download --source
        if shutil.which("dnf"):
            try:
                result = subprocess.run(
                    ["dnf", "download", "--source", "--destdir",
                     str(self.srpms_dir), package_name],
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode == 0:
                    # Find the downloaded SRPM
                    for f in self.srpms_dir.glob(f"{package_name}*.src.rpm"):
                        return f
            except Exception as e:
                print(f"    ⚠️  dnf download failed: {e}")

        # Try yumdownloader
        if shutil.which("yumdownloader"):
            try:
                result = subprocess.run(
                    ["yumdownloader", "--source", "--destdir",
                     str(self.srpms_dir), package_name],
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode == 0:
                    for f in self.srpms_dir.glob(f"{package_name}*.src.rpm"):
                        return f
            except Exception:
                pass

        # Try direct URL for CentOS Stream
        if "centos" in self.upstream:
            urls = [
                f"https://vault.centos.org/centos/9-stream/BaseOS/Source/SPackages/{package_name}",
                f"https://git.centos.org/rpms/{package_name}",
            ]
            print(f"    ⚠️  Could not download {package_name} via package manager")
            print(f"    💡 Try manually: dnf download --source {package_name}")

        return None

    def _patch_specs(self, srpms):
        """Unpack SRPMs and patch spec files for rebranding."""
        print("⚙️  Patching spec files...")

        patched = []
        for srpm in srpms:
            spec = self._patch_single_spec(srpm)
            if spec:
                patched.append(spec)

        print(f"  ✅ {len(patched)} specs patched")
        return patched

    def _patch_single_spec(self, srpm_path):
        """Unpack a single SRPM and rebrand its spec file."""
        pkg_name = srpm_path.stem.rsplit("-", 2)[0]  # Strip version-release
        pkg_dir = self.specs_dir / pkg_name
        pkg_dir.mkdir(parents=True, exist_ok=True)

        # Unpack SRPM
        try:
            subprocess.run(
                ["rpm", "-i", "--define", f"_topdir {pkg_dir}", str(srpm_path)],
                capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"  ⚠️  Failed to unpack {srpm_path.name}: {e}")
            return None

        # Find spec file
        specs = list((pkg_dir / "SPECS").glob("*.spec"))
        if not specs:
            print(f"  ⚠️  No spec file found in {srpm_path.name}")
            return None

        spec_file = specs[0]
        content = spec_file.read_text()

        # ── Rebrand the spec ────────────────────────────────
        original_name = pkg_name
        new_name = pkg_name

        # Replace package names
        upstream_prefixes = ["centos-stream-", "centos-", "rocky-", "almalinux-"]
        for prefix in upstream_prefixes:
            if pkg_name.startswith(prefix):
                suffix = pkg_name[len(prefix):]
                new_name = f"{self.os_id}-{suffix}"
                break

        # Replace in spec content
        content = self._rebrand_spec_content(content, original_name, new_name)

        # Write patched spec
        new_spec = spec_file.parent / f"{new_name}.spec"
        new_spec.write_text(content)
        if new_spec != spec_file:
            spec_file.unlink()

        print(f"  → {original_name} → {new_name}")
        return {
            "name": new_name,
            "spec": new_spec,
            "topdir": pkg_dir,
            "original": original_name,
        }

    def _rebrand_spec_content(self, content, original_name, new_name):
        """Replace upstream branding in a spec file."""

        # Package name
        content = re.sub(
            rf"^Name:\s+{re.escape(original_name)}",
            f"Name:           {new_name}",
            content, flags=re.MULTILINE
        )

        # Vendor
        content = re.sub(
            r"^Vendor:\s+.*$",
            f"Vendor:         {self.vendor}",
            content, flags=re.MULTILINE
        )
        if "Vendor:" not in content:
            content = re.sub(
                r"(^Name:.*$)",
                rf"\1\nVendor:         {self.vendor}",
                content, flags=re.MULTILINE
            )

        # Summary / Description references
        upstream_names = [
            "CentOS Stream", "CentOS Linux", "CentOS",
            "Rocky Linux", "AlmaLinux", "Red Hat Enterprise Linux",
        ]
        for uname in upstream_names:
            content = content.replace(uname, self.name)

        # Provides/Obsoletes for clean upgrade path
        provides_block = (
            f"\n# Distro Forge: replace upstream branding\n"
            f"Provides:       {original_name} = %{{version}}-%{{release}}\n"
            f"Obsoletes:      {original_name} < %{{version}}-%{{release}}\n"
            f"Conflicts:      {original_name}\n"
        )

        # Add after Release: line
        content = re.sub(
            r"(^Release:.*$)",
            rf"\1{provides_block}",
            content, count=1, flags=re.MULTILINE
        )

        # Add changelog entry
        today = datetime.now().strftime("%a %b %d %Y")
        changelog_entry = (
            f"\n%changelog\n"
            f"* {today} Distro Forge <forge@{self.os_id}> - %{{version}}-%{{release}}\n"
            f"- Rebranded from {original_name} to {new_name} by Distro Forge\n"
            f"- All upstream trademarks replaced with {self.name}\n"
        )

        if "%changelog" in content:
            content = re.sub(
                r"%changelog",
                changelog_entry.lstrip("\n"),
                content, count=1
            )
        else:
            content += changelog_entry

        return content

    def _inject_assets(self):
        """Inject custom branding assets into the build sources."""
        assets_dir = self.manifest.get("branding", {}).get("assets_dir")
        if not assets_dir:
            return

        assets_path = Path(assets_dir)
        if not assets_path.is_dir():
            return

        # Copy logos into any logo package build
        logos_src = assets_path / "logos"
        if logos_src.is_dir():
            for spec_dir in self.specs_dir.iterdir():
                if "logo" in spec_dir.name:
                    sources = spec_dir / "SOURCES"
                    sources.mkdir(parents=True, exist_ok=True)
                    for f in logos_src.iterdir():
                        if f.is_file():
                            shutil.copy2(f, sources / f.name)
                    print(f"  → Injected logos into {spec_dir.name}")

        # Copy backgrounds
        bg_src = assets_path / "backgrounds"
        if bg_src.is_dir():
            for spec_dir in self.specs_dir.iterdir():
                if "background" in spec_dir.name:
                    sources = spec_dir / "SOURCES"
                    sources.mkdir(parents=True, exist_ok=True)
                    for f in bg_src.iterdir():
                        if f.is_file():
                            shutil.copy2(f, sources / f.name)
                    print(f"  → Injected backgrounds into {spec_dir.name}")

    def _build_rpms(self, specs):
        """Build RPMs from patched specs using mock or koji."""
        print(f"⚙️  Building RPMs ({self.backend})...")

        built = []
        for spec_info in specs:
            if self.backend == "koji":
                rpms = self._build_with_koji(spec_info)
            else:
                rpms = self._build_with_mock(spec_info)
            built.extend(rpms)

        print(f"  ✅ {len(built)} RPMs built")
        return built

    def _build_with_mock(self, spec_info):
        """Build an RPM using mock (local chroot build)."""
        spec = spec_info["spec"]
        topdir = spec_info["topdir"]
        name = spec_info["name"]

        print(f"  → Building {name} with mock...")

        # First build the SRPM
        try:
            result = subprocess.run(
                [
                    "rpmbuild", "-bs",
                    "--define", f"_topdir {topdir}",
                    str(spec)
                ],
                capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"    ⚠️  SRPM build failed: {e.stderr[:200]}")
            return []

        # Find built SRPM
        new_srpms = list((topdir / "SRPMS").glob("*.src.rpm"))
        if not new_srpms:
            print(f"    ⚠️  No SRPM produced for {name}")
            return []

        # Build with mock
        try:
            result = subprocess.run(
                [
                    "mock", "-r", self.mock_config,
                    "--rebuild", str(new_srpms[0]),
                    "--resultdir", str(self.rpms_dir / name),
                ],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                print(f"    ⚠️  mock build failed: {result.stderr[:300]}")
                return []
        except subprocess.TimeoutExpired:
            print(f"    ⚠️  mock build timed out for {name}")
            return []

        # Collect built RPMs
        rpms = list((self.rpms_dir / name).glob("*.rpm"))
        rpms = [r for r in rpms if not r.name.endswith(".src.rpm")]
        for rpm in rpms:
            print(f"    ✅ {rpm.name}")
        return rpms

    def _build_with_koji(self, spec_info):
        """Build an RPM using Koji build system."""
        spec = spec_info["spec"]
        topdir = spec_info["topdir"]
        name = spec_info["name"]

        if not self.koji_hub:
            print(f"  ❌ Koji hub URL required for koji backend")
            print(f"     Set rebuild.koji_hub in manifest")
            return []

        print(f"  → Submitting {name} to Koji...")

        # Build SRPM first
        try:
            subprocess.run(
                [
                    "rpmbuild", "-bs",
                    "--define", f"_topdir {topdir}",
                    str(spec)
                ],
                capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"    ⚠️  SRPM build failed: {e.stderr[:200]}")
            return []

        new_srpms = list((topdir / "SRPMS").glob("*.src.rpm"))
        if not new_srpms:
            return []

        # Submit to Koji
        tag = self.koji_tag or f"{self.os_id}-{self.version}-candidate"
        try:
            result = subprocess.run(
                [
                    "koji", "--server", self.koji_hub,
                    "build", "--scratch", tag,
                    str(new_srpms[0])
                ],
                capture_output=True, text=True, timeout=1800
            )
            if result.returncode != 0:
                print(f"    ⚠️  Koji build failed: {result.stderr[:300]}")
                return []

            # Parse task ID from output
            task_match = re.search(r"Task ID:\s+(\d+)", result.stdout)
            if task_match:
                task_id = task_match.group(1)
                print(f"    → Koji task: {task_id}")

                # Wait for and download results
                return self._koji_download_results(task_id, name)
        except subprocess.TimeoutExpired:
            print(f"    ⚠️  Koji build timed out for {name}")
            return []

        return []

    def _koji_download_results(self, task_id, name):
        """Download built RPMs from a Koji task."""
        result_dir = self.rpms_dir / name
        result_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Wait for task
            subprocess.run(
                ["koji", "--server", self.koji_hub, "watch-task", task_id],
                capture_output=True, text=True, timeout=1800
            )

            # Download results
            subprocess.run(
                [
                    "koji", "--server", self.koji_hub,
                    "download-task", "--arch=x86_64", "--arch=noarch",
                    task_id, "--dir", str(result_dir)
                ],
                capture_output=True, text=True, timeout=300
            )

            rpms = list(result_dir.glob("*.rpm"))
            rpms = [r for r in rpms if not r.name.endswith(".src.rpm")]
            for rpm in rpms:
                print(f"    ✅ {rpm.name}")
            return rpms

        except Exception as e:
            print(f"    ⚠️  Failed to download Koji results: {e}")
            return []

    def _sign_rpms(self, rpms):
        """Sign RPMs with a GPG key."""
        if not self.gpg_key_id:
            return

        print(f"⚙️  Signing RPMs with key: {self.gpg_key_id}")

        for rpm in rpms:
            try:
                subprocess.run(
                    [
                        "rpmsign", "--addsign",
                        "--key-id", self.gpg_key_id,
                        str(rpm)
                    ],
                    capture_output=True, text=True, check=True
                )
                print(f"  → Signed: {rpm.name}")
            except subprocess.CalledProcessError as e:
                print(f"  ⚠️  Failed to sign {rpm.name}: {e}")

    def generate_repo(self, rpms_dir=None):
        """Create a yum/dnf repo from built RPMs."""
        rpms_dir = rpms_dir or (self.output_dir / "rpms")

        if not rpms_dir.exists() or not list(rpms_dir.glob("**/*.rpm")):
            print("  ⚠️  No RPMs found to create repo")
            return None

        print("⚙️  Creating repo from built RPMs...")

        repo_dir = self.output_dir / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)

        # Copy all RPMs to repo dir
        for rpm in rpms_dir.glob("**/*.rpm"):
            if not rpm.name.endswith(".src.rpm"):
                shutil.copy2(rpm, repo_dir / rpm.name)

        # Create repo metadata
        createrepo = "createrepo_c" if shutil.which("createrepo_c") else "createrepo"
        if not shutil.which(createrepo):
            print("  ⚠️  createrepo not found, skipping repo creation")
            return None

        try:
            subprocess.run(
                [createrepo, str(repo_dir)],
                capture_output=True, text=True, check=True
            )
            print(f"  ✅ Repo created: {repo_dir}")
            return repo_dir
        except subprocess.CalledProcessError as e:
            print(f"  ⚠️  createrepo failed: {e}")
            return None
