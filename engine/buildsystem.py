"""
Build System Engine — Build a distro from scratch using mock + pungi/lorax.
Instead of remastering an existing ISO, this pulls packages from upstream
repos and composes a fresh ISO with your branding and package selection.
"""

import os
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime


class BuildSystem:
    """
    Build a distro ISO from scratch.

    Pipeline:
    1. Validate build environment (mock, pungi/lorax installed)
    2. Generate pungi config or lorax kickstart from manifest
    3. Set up repos (upstream + custom)
    4. Run the compose (pungi-koji or lorax)
    5. Apply branding to the output
    6. Generate checksums
    """

    SUPPORTED_ARCHES = ["x86_64", "aarch64"]

    # Upstream repo base URLs for known distros
    UPSTREAM_REPOS = {
        "centos-stream-9": {
            "baseos": "https://mirror.stream.centos.org/9-stream/BaseOS/$arch/os/",
            "appstream": "https://mirror.stream.centos.org/9-stream/AppStream/$arch/os/",
            "crb": "https://mirror.stream.centos.org/9-stream/CRB/$arch/os/",
            "extras": "https://mirror.stream.centos.org/SIGs/9-stream/extras/$arch/extras-common/",
        },
        "centos-stream-10": {
            "baseos": "https://mirror.stream.centos.org/10-stream/BaseOS/$arch/os/",
            "appstream": "https://mirror.stream.centos.org/10-stream/AppStream/$arch/os/",
            "crb": "https://mirror.stream.centos.org/10-stream/CRB/$arch/os/",
        },
        "rocky-9": {
            "baseos": "https://dl.rockylinux.org/pub/rocky/9/BaseOS/$arch/os/",
            "appstream": "https://dl.rockylinux.org/pub/rocky/9/AppStream/$arch/os/",
            "crb": "https://dl.rockylinux.org/pub/rocky/9/CRB/$arch/os/",
            "extras": "https://dl.rockylinux.org/pub/rocky/9/extras/$arch/os/",
        },
        "alma-9": {
            "baseos": "https://repo.almalinux.org/almalinux/9/BaseOS/$arch/os/",
            "appstream": "https://repo.almalinux.org/almalinux/9/AppStream/$arch/os/",
            "crb": "https://repo.almalinux.org/almalinux/9/CRB/$arch/os/",
            "extras": "https://repo.almalinux.org/almalinux/9/extras/$arch/os/",
        },
    }

    def __init__(self, manifest: dict, output_dir: Path):
        self.manifest = manifest
        self.output_dir = output_dir
        self.name = manifest["name"]
        self.version = manifest["version"]
        self.os_id = manifest.get("branding", {}).get(
            "os_id", self.name.lower().replace(" ", "-")
        )

        build_config = manifest.get("build_system", {})
        self.upstream = build_config.get("upstream", "centos-stream-9")
        self.arch = build_config.get("arch", "x86_64")
        self.compose_tool = build_config.get("tool", "lorax")  # lorax or pungi
        self.release = build_config.get("release", self.version)
        self.mirror_locally = build_config.get("mirror", False)

        self.work_dir = Path(tempfile.mkdtemp(prefix="distro-forge-build-"))
        self.compose_dir = self.work_dir / "compose"
        self.repo_dir = self.work_dir / "repos"
        self.ks_dir = self.work_dir / "kickstarts"

    def check_environment(self):
        """Verify all required tools are installed."""
        print("⚙️  Checking build environment...")

        required = {
            "lorax": "lorax" if self.compose_tool == "lorax" else None,
            "pungi": "pungi-koji" if self.compose_tool == "pungi" else None,
            "createrepo_c": "createrepo_c",
            "mock": "mock",
        }

        missing = []
        for tool, package in required.items():
            if package is None:
                continue
            if not shutil.which(tool):
                missing.append(f"{tool} (dnf install {package})")

        # Optional but recommended
        optional = {
            "xorriso": "xorriso",
            "isohybrid": "syslinux",
            "implantisomd5": "isomd5sum",
            "mksquashfs": "squashfs-tools",
        }

        optional_missing = []
        for tool, package in optional.items():
            if not shutil.which(tool):
                optional_missing.append(f"{tool} (dnf install {package})")

        if missing:
            print("  ❌ Missing required tools:")
            for m in missing:
                print(f"    - {m}")
            return False

        if optional_missing:
            print("  ⚠️  Missing optional tools:")
            for m in optional_missing:
                print(f"    - {m}")

        print("  ✅ Build environment OK")
        return True

    def run(self):
        """Execute the full build-from-scratch pipeline."""
        print(f"\n{'═' * 50}")
        print(f"  Build System — {self.name} {self.version}")
        print(f"  Upstream: {self.upstream}")
        print(f"  Architecture: {self.arch}")
        print(f"  Compose tool: {self.compose_tool}")
        print(f"  Work dir: {self.work_dir}")
        print(f"{'═' * 50}\n")

        if not self.check_environment():
            raise RuntimeError("Missing required build tools. Install them and retry.")

        try:
            # Step 1: Set up repository configuration
            self._setup_repos()

            # Step 2: Generate kickstart for lorax / comps for pungi
            if self.compose_tool == "lorax":
                self._run_lorax_compose()
            elif self.compose_tool == "pungi":
                self._run_pungi_compose()
            else:
                raise ValueError(f"Unknown compose tool: {self.compose_tool}")

            # Step 3: Apply branding to composed output
            self._apply_branding()

            # Step 4: Generate checksums
            output_iso = self._find_output_iso()
            if output_iso:
                final_name = f"{self.name}-{self.version}-{self.arch}.iso"
                final_path = self.output_dir / final_name
                self.output_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(output_iso), str(final_path))
                self._generate_checksums(final_path)
                print(f"\n✅ Done! → {final_path}")
                return final_path
            else:
                raise RuntimeError("No ISO found in compose output")

        except Exception as e:
            print(f"\n❌ Build failed: {e}")
            raise
        finally:
            print(f"\n  Work dir preserved: {self.work_dir}")

    def _setup_repos(self):
        """Set up repository configs for the build."""
        print("⚙️  Setting up repositories...")

        self.repo_dir.mkdir(parents=True, exist_ok=True)

        # Get upstream repo URLs
        upstream_repos = self.UPSTREAM_REPOS.get(self.upstream)
        if not upstream_repos:
            # Allow custom upstream definition
            upstream_repos = self.manifest.get("build_system", {}).get("upstream_repos", {})
            if not upstream_repos:
                raise ValueError(
                    f"Unknown upstream: {self.upstream}. "
                    f"Supported: {', '.join(self.UPSTREAM_REPOS.keys())} "
                    f"or define 'upstream_repos' in build_system config."
                )

        # Write repo files
        all_repos = []

        for repo_id, baseurl in upstream_repos.items():
            url = baseurl.replace("$arch", self.arch)
            repo_content = (
                f"[{repo_id}]\n"
                f"name={self.upstream} - {repo_id}\n"
                f"baseurl={url}\n"
                f"enabled=1\n"
                f"gpgcheck=0\n"
            )
            repo_file = self.repo_dir / f"{repo_id}.repo"
            repo_file.write_text(repo_content)
            all_repos.append({"id": repo_id, "url": url, "file": repo_file})
            print(f"  → {repo_id}: {url}")

        # Add custom repos from manifest
        for repo in self.manifest.get("repos", []):
            repo_content = (
                f"[{repo['name']}]\n"
                f"name={repo['name']}\n"
                f"baseurl={repo['baseurl']}\n"
                f"enabled=1\n"
                f"gpgcheck={1 if repo.get('gpgcheck') else 0}\n"
            )
            if repo.get("gpgkey"):
                repo_content += f"gpgkey={repo['gpgkey']}\n"
            repo_file = self.repo_dir / f"{repo['name']}.repo"
            repo_file.write_text(repo_content)
            all_repos.append({"id": repo["name"], "url": repo["baseurl"], "file": repo_file})
            print(f"  → {repo['name']}: {repo['baseurl']}")

        self._all_repos = all_repos
        print(f"  ✅ {len(all_repos)} repos configured")

    def _run_lorax_compose(self):
        """
        Use lorax to compose a bootable install ISO.
        Lorax builds the installer image (Anaconda) + boot images.
        """
        print("⚙️  Running lorax compose...")

        self.compose_dir.mkdir(parents=True, exist_ok=True)

        # Generate lorax kickstart
        ks_path = self._generate_lorax_kickstart()

        # Build repo args
        repo_args = []
        for repo in self._all_repos:
            repo_args += ["--repo", repo["url"]]

        # Build lorax command
        cmd = [
            "lorax",
            f"--product={self.name}",
            f"--version={self.version}",
            f"--release={self.release}",
            f"--source={self._all_repos[0]['url']}",  # Primary source
            f"--resultdir={self.compose_dir}",
            f"--variant=BaseOS",
            f"--buildarch={self.arch}",
            "--isfinal",
        ]

        # Add all repos as sources
        for repo in self._all_repos:
            cmd += [f"--source={repo['url']}"]

        # Volume ID
        vol_id = f"{self.name}-{self.version}-{self.arch}"
        if len(vol_id) > 32:
            vol_id = vol_id[:32]
        cmd += [f"--volid={vol_id}"]

        print(f"  → Running: lorax (this takes a while...)")
        self._run_cmd(cmd, timeout=3600)
        print("  ✅ Lorax compose complete")

    def _run_pungi_compose(self):
        """
        Use pungi to compose a full distro with multiple variants.
        Pungi is more complex but produces production-quality composes.
        """
        print("⚙️  Running pungi compose...")

        self.compose_dir.mkdir(parents=True, exist_ok=True)

        # Generate pungi config
        pungi_conf = self._generate_pungi_config()

        cmd = [
            "pungi-koji",
            f"--config={pungi_conf}",
            f"--target-dir={self.compose_dir}",
            f"--label={self.name}-{self.version}",
            "--no-latest-link",
            "--noinput",
        ]

        print(f"  → Running: pungi-koji (this takes a long while...)")
        self._run_cmd(cmd, timeout=7200)
        print("  ✅ Pungi compose complete")

    def _generate_lorax_kickstart(self):
        """Generate a kickstart for lorax to define the install tree."""
        self.ks_dir.mkdir(parents=True, exist_ok=True)
        ks_path = self.ks_dir / "lorax.ks"

        gui = self.manifest.get("gui", {})
        packages = self.manifest.get("packages", {})

        # Package list
        pkg_lines = ["@core"]
        if gui.get("enabled"):
            desktop = gui.get("desktop", "GNOME").lower()
            desktop_map = {
                "gnome": "@gnome-desktop",
                "kde": "@kde-desktop-environment",
                "xfce": "@xfce-desktop",
                "mate": "@mate-desktop",
                "cinnamon": "@cinnamon-desktop",
            }
            pkg_lines.append(desktop_map.get(desktop, "@gnome-desktop"))

        for pkg in packages.get("install", []):
            pkg_lines.append(pkg)
        for pkg in packages.get("remove", []):
            pkg_lines.append(f"-{pkg}")

        # Repo lines
        repo_lines = []
        for repo in self._all_repos:
            repo_lines.append(f"repo --name={repo['id']} --baseurl={repo['url']}")

        ks = self._render_kickstart(repo_lines, pkg_lines)
        ks_path.write_text(ks)
        print(f"  → Kickstart: {ks_path}")
        return ks_path

    def _generate_pungi_config(self):
        """Generate a pungi configuration file."""
        conf_path = self.work_dir / "pungi.conf"

        gui = self.manifest.get("gui", {})
        packages = self.manifest.get("packages", {})

        # Collect packages
        all_packages = ["@core"] + packages.get("install", [])
        if gui.get("enabled"):
            desktop = gui.get("desktop", "GNOME").lower()
            desktop_map = {
                "gnome": "@gnome-desktop",
                "kde": "@kde-desktop-environment",
                "xfce": "@xfce-desktop",
                "mate": "@mate-desktop",
                "cinnamon": "@cinnamon-desktop",
            }
            all_packages.append(desktop_map.get(desktop, "@gnome-desktop"))

        # Build repo list for pungi
        repo_entries = {}
        for repo in self._all_repos:
            repo_entries[repo["id"]] = repo["url"]

        # Volume ID
        vol_id = f"{self.name}-{self.version}"
        if len(vol_id) > 32:
            vol_id = vol_id[:32]

        config = f"""# Pungi config for {self.name} {self.version}
# Generated by Distro Forge on {datetime.now().strftime('%Y-%m-%d %H:%M')}

release_name = "{self.name}"
release_short = "{self.os_id}"
release_version = "{self.version}"
release_is_layered = False

bootable = True
comps_file = "{self._generate_comps()}"

arch = ["{self.arch}"]

# ── Variants ──
variants_file = "{self._generate_variants()}"

# ── Signing ──
sigkeys = [""]

# ── Repos ──
pkgset_source = "repos"
pkgset_repos = {{
"""
        for repo_id, url in repo_entries.items():
            config += f'    "{repo_id}": "{url}",\n'

        config += f"""}}

# ── Gather ──
gather_method = "deps"
gather_backend = "dnf"
check_deps = False
greedy_method = "build"

# ── Create ISO ──
createiso_skip = []
create_optional_isos = False

# ── Build install images ──
buildinstall_method = "lorax"
buildinstall_treeinfo_name = "{self.name}"

# ── ISO naming ──
image_name_format = "{self.name}-{self.version}-%(variant)s-%(arch)s-%(disc_type)s%(disc_num)s.iso"
image_volid_formats = {{
    "boot": "{vol_id}-%(variant)s-%(arch)s-boot",
    "dvd": "{vol_id}-%(variant)s-%(arch)s-dvd",
}}
"""
        conf_path.write_text(config)
        print(f"  → Pungi config: {conf_path}")
        return str(conf_path)

    def _generate_comps(self):
        """Generate a minimal comps.xml for package groups."""
        comps_path = self.work_dir / "comps.xml"

        gui = self.manifest.get("gui", {})
        packages = self.manifest.get("packages", {})

        groups_xml = ""

        # Core group (always present)
        core_packages = "\n".join(
            f'      <packagereq type="mandatory">{pkg}</packagereq>'
            for pkg in packages.get("install", [])
        )

        groups_xml += f"""
  <group>
    <id>core</id>
    <name>Core</name>
    <description>Minimal install</description>
    <default>true</default>
    <uservisible>true</uservisible>
    <packagelist>
      <packagereq type="mandatory">basesystem</packagereq>
      <packagereq type="mandatory">bash</packagereq>
      <packagereq type="mandatory">coreutils</packagereq>
      <packagereq type="mandatory">filesystem</packagereq>
      <packagereq type="mandatory">glibc</packagereq>
      <packagereq type="mandatory">NetworkManager</packagereq>
      <packagereq type="mandatory">rpm</packagereq>
      <packagereq type="mandatory">dnf</packagereq>
      <packagereq type="mandatory">systemd</packagereq>
{core_packages}
    </packagelist>
  </group>
"""

        # Desktop group if GUI enabled
        if gui.get("enabled"):
            desktop = gui.get("desktop", "GNOME").lower()
            desktop_pkgs = {
                "gnome": ["gnome-shell", "gnome-terminal", "nautilus", "gdm", "gnome-tweaks"],
                "kde": ["plasma-desktop", "konsole", "dolphin", "sddm"],
                "xfce": ["xfce4-panel", "xfce4-terminal", "thunar", "lightdm"],
                "mate": ["mate-panel", "mate-terminal", "caja", "lightdm"],
                "cinnamon": ["cinnamon", "nemo", "gnome-terminal", "lightdm"],
            }
            pkgs = desktop_pkgs.get(desktop, desktop_pkgs["gnome"])
            pkg_xml = "\n".join(
                f'      <packagereq type="mandatory">{p}</packagereq>'
                for p in pkgs
            )
            groups_xml += f"""
  <group>
    <id>{desktop}-desktop</id>
    <name>{desktop.upper()} Desktop</name>
    <description>{desktop.upper()} Desktop Environment</description>
    <default>true</default>
    <uservisible>true</uservisible>
    <packagelist>
{pkg_xml}
    </packagelist>
  </group>
"""

        comps_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE comps PUBLIC "-//Red Hat, Inc.//DTD Comps info//EN" "comps.dtd">
<comps>
{groups_xml}

  <environment>
    <id>minimal-environment</id>
    <name>Minimal Install</name>
    <description>Basic functionality.</description>
    <display_order>5</display_order>
    <grouplist>
      <groupid>core</groupid>
    </grouplist>
  </environment>
"""

        if gui.get("enabled"):
            desktop = gui.get("desktop", "GNOME").lower()
            comps_xml += f"""
  <environment>
    <id>desktop-environment</id>
    <name>{desktop.upper()} Desktop</name>
    <description>Desktop with {desktop.upper()}.</description>
    <display_order>1</display_order>
    <grouplist>
      <groupid>core</groupid>
      <groupid>{desktop}-desktop</groupid>
    </grouplist>
  </environment>
"""

        comps_xml += "\n</comps>\n"

        comps_path.write_text(comps_xml)
        print(f"  → Comps XML: {comps_path}")
        return str(comps_path)

    def _generate_variants(self):
        """Generate a variants XML file for pungi."""
        variants_path = self.work_dir / "variants.xml"

        gui = self.manifest.get("gui", {})

        env_id = "minimal-environment"
        if gui.get("enabled"):
            env_id = "desktop-environment"

        variants_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<variants>
  <variant id="BaseOS" name="BaseOS" type="variant">
    <arches>
      <arch>{self.arch}</arch>
    </arches>
    <groups>
      <group>core</group>
    </groups>
    <environments>
      <environment>{env_id}</environment>
    </environments>
  </variant>
"""

        if gui.get("enabled"):
            desktop = gui.get("desktop", "GNOME").lower()
            variants_xml += f"""
  <variant id="AppStream" name="AppStream" type="variant">
    <arches>
      <arch>{self.arch}</arch>
    </arches>
    <groups>
      <group>{desktop}-desktop</group>
    </groups>
  </variant>
"""

        variants_xml += "</variants>\n"

        variants_path.write_text(variants_xml)
        print(f"  → Variants XML: {variants_path}")
        return str(variants_path)

    def _render_kickstart(self, repo_lines, pkg_lines):
        """Render a kickstart file from parts."""
        ks_config = self.manifest.get("kickstart", {})
        gui = self.manifest.get("gui", {})

        tz = ks_config.get("timezone", "UTC")
        lang = ks_config.get("lang", "en_US.UTF-8")
        keyboard = ks_config.get("keyboard", "us")
        selinux = self.manifest.get("selinux", "enforcing")

        display = "graphical" if gui.get("enabled") else "text"

        firewall_line = "firewall --enabled --service=ssh"
        if self.manifest.get("firewall") is False:
            firewall_line = "firewall --disabled"
        elif self.manifest.get("firewall_services"):
            svcs = ",".join(self.manifest["firewall_services"])
            firewall_line = f"firewall --enabled --service={svcs}"

        root_pw = "rootpw --lock"
        if ks_config.get("root_password_value"):
            root_pw = f"rootpw --plaintext {ks_config['root_password_value']}"

        repo_section = "\n".join(repo_lines)
        pkg_section = "\n".join(pkg_lines)

        return f"""# {self.name} {self.version} — Build System Kickstart
# Generated by Distro Forge

{display}

lang {lang}
keyboard --vckeymap={keyboard} --xlayouts='{keyboard}'
timezone {tz} --utc
network --bootproto=dhcp --activate
network --hostname={self.os_id}

{root_pw}

selinux --{selinux}
{firewall_line}

ignoredisk --only-use=sda
autopart --type=lvm
clearpart --all --initlabel
bootloader --append="crashkernel=auto" --location=mbr

{repo_section}

reboot --eject

%packages
{pkg_section}
%end

%post --log=/root/distro-forge-post.log
echo '=== {self.name} post-install ==='

cat > /etc/os-release << 'EOF'
NAME="{self.name}"
VERSION="{self.version}"
ID="{self.os_id}"
ID_LIKE="rhel centos fedora"
VERSION_ID="{self.version}"
PRETTY_NAME="{self.name} {self.version}"
ANSI_COLOR="0;31"
CPE_NAME="cpe:/o:{self.os_id}:{self.os_id}:{self.version}"
EOF

echo "{self.name} release {self.version}" > /etc/system-release
echo "{self.name} release {self.version}" > /etc/redhat-release

cat > /etc/motd << 'EOF'

  Welcome to {self.name} {self.version}

EOF

echo '{self.name} installation complete.'
%end
"""

    def _apply_branding(self):
        """Apply branding to the composed output."""
        print("⚙️  Applying branding to compose output...")

        # Find the compose output directory
        # Lorax outputs directly to compose_dir
        # Pungi creates a nested structure
        iso_dir = self._find_compose_output()
        if not iso_dir:
            print("  ⚠️  Could not locate compose output for branding")
            return

        # Apply branding engine to the output
        from engine.branding import BrandingEngine
        branding = BrandingEngine(iso_dir, self.manifest)
        branding.apply_all()

    def _find_compose_output(self):
        """Find the compose output directory."""
        # Lorax
        if (self.compose_dir / "images").exists():
            return self.compose_dir

        # Pungi — look for the compose tree
        for dirpath, dirnames, filenames in os.walk(self.compose_dir):
            if "images" in dirnames or ".treeinfo" in filenames:
                return Path(dirpath)

        return self.compose_dir

    def _find_output_iso(self):
        """Find the built ISO in the compose output."""
        # Search for .iso files
        for dirpath, _, filenames in os.walk(self.compose_dir):
            for f in filenames:
                if f.endswith(".iso"):
                    return Path(dirpath) / f

        # Lorax may not produce an ISO directly — we need to create one
        if (self.compose_dir / "images" / "boot.iso").exists():
            return self.compose_dir / "images" / "boot.iso"

        # If no ISO found, try to create one from the compose tree
        return self._create_iso_from_tree()

    def _create_iso_from_tree(self):
        """Create an ISO from the compose tree if lorax didn't make one."""
        print("⚙️  Creating ISO from compose tree...")

        if not shutil.which("xorriso"):
            print("  ❌ xorriso required to create ISO")
            return None

        output_iso = self.compose_dir / f"{self.name}-{self.version}-{self.arch}.iso"
        vol_id = f"{self.name}-{self.version}-{self.arch}"[:32]

        cmd = [
            "xorriso", "-as", "mkisofs",
            "-V", vol_id,
            "-R", "-J",
            "-o", str(output_iso),
            str(self.compose_dir),
        ]

        # Check for boot images
        efi_boot = self.compose_dir / "images" / "efiboot.img"
        isolinux_bin = self.compose_dir / "isolinux" / "isolinux.bin"

        if isolinux_bin.exists():
            cmd = cmd[:-1] + [
                "-b", "isolinux/isolinux.bin",
                "-c", "isolinux/boot.cat",
                "-no-emul-boot",
                "-boot-load-size", "4",
                "-boot-info-table",
            ] + cmd[-1:]

        if efi_boot.exists():
            cmd = cmd[:-1] + [
                "-eltorito-alt-boot",
                "-e", "images/efiboot.img",
                "-no-emul-boot",
            ] + cmd[-1:]

        try:
            self._run_cmd(cmd)
            return output_iso
        except Exception as e:
            print(f"  ❌ ISO creation failed: {e}")
            return None

    def _generate_checksums(self, iso_path: Path):
        """Generate SHA256 checksum."""
        print("⚙️  Generating checksums...")
        checksum_file = iso_path.with_suffix(".iso.sha256")
        try:
            if shutil.which("sha256sum"):
                cmd = f"sha256sum {iso_path}"
            elif shutil.which("shasum"):
                cmd = f"shasum -a 256 {iso_path}"
            else:
                return

            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                checksum_file.write_text(result.stdout)
                print(f"  → Checksum: {checksum_file}")
        except Exception:
            pass

    @staticmethod
    def _run_cmd(cmd, timeout=600):
        """Run a command with output streaming."""
        print(f"  → {' '.join(str(c) for c in cmd[:5])}...")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            stderr_snippet = result.stderr[:500] if result.stderr else "no stderr"
            raise subprocess.CalledProcessError(
                result.returncode, cmd,
                output=result.stdout,
                stderr=result.stderr
            )
        return result
