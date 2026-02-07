"""
TUI Wizard — ncurses-based interactive wizard using the `dialog` utility.
Provides the classic blue-box terminal UI for distro configuration.

Requires: dialog or whiptail (pre-installed on most Linux systems)
  - Fedora/CentOS: dnf install dialog
  - Debian/Ubuntu: apt install dialog (or whiptail is usually pre-installed)
  - macOS: brew install dialog
"""

import os
import sys
import subprocess
import tempfile
import json
from pathlib import Path


class TUIWizard:
    """NCurses TUI wizard using dialog/whiptail."""

    def __init__(self):
        self.backend = self._detect_backend()
        if not self.backend:
            raise RuntimeError(
                "TUI requires 'dialog' or 'whiptail'. "
                "Install: dnf install dialog / brew install dialog"
            )
        self.manifest = {}

    def _detect_backend(self):
        """Find dialog or whiptail."""
        for cmd in ["dialog", "whiptail"]:
            if self._which(cmd):
                return cmd
        return None

    @staticmethod
    def _which(cmd):
        """Check if command exists."""
        try:
            subprocess.run(
                ["which", cmd], capture_output=True, check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _run_dialog(self, *args, **kwargs):
        """
        Run a dialog/whiptail command and return (returncode, output).
        Dialog writes user input to stderr.
        """
        height = kwargs.get("height", 12)
        width = kwargs.get("width", 60)

        cmd = [self.backend]

        # whiptail needs --title before the widget
        title = kwargs.get("title", "Distro Forge")
        cmd += ["--title", title]

        # Backtitle
        cmd += ["--backtitle", "🔨 Distro Forge — RHEL/CentOS Distro Builder"]

        # Add the widget args
        cmd += list(args)

        result = subprocess.run(cmd, capture_output=True, text=True)
        # dialog outputs to stderr, whiptail also outputs to stderr
        output = result.stderr.strip()
        return result.returncode, output

    def _inputbox(self, text, default="", title="Distro Forge", height=10, width=60):
        """Show an input box and return the entered text."""
        rc, val = self._run_dialog(
            "--inputbox", text, str(height), str(width), default,
            title=title
        )
        if rc != 0:
            return None
        return val

    def _yesno(self, text, title="Distro Forge", height=8, width=50, default_yes=True):
        """Show a yes/no dialog. Returns True for Yes."""
        args = ["--yesno", text, str(height), str(width)]
        if not default_yes and self.backend == "dialog":
            args = ["--defaultno"] + args
        rc, _ = self._run_dialog(*args, title=title)
        return rc == 0

    def _menu(self, text, choices, title="Distro Forge", height=18, width=65, menu_height=8):
        """
        Show a menu. choices is list of (tag, description) tuples.
        Returns the selected tag.
        """
        args = ["--menu", text, str(height), str(width), str(menu_height)]
        for tag, desc in choices:
            args += [tag, desc]
        rc, val = self._run_dialog(*args, title=title)
        if rc != 0:
            return None
        return val

    def _checklist(self, text, choices, title="Distro Forge", height=20, width=65, list_height=10):
        """
        Show a checklist. choices is list of (tag, description, on/off) tuples.
        Returns list of selected tags.
        """
        args = ["--checklist", text, str(height), str(width), str(list_height)]
        for tag, desc, state in choices:
            args += [tag, desc, state]
        rc, val = self._run_dialog(*args, title=title)
        if rc != 0:
            return None
        # dialog returns space-separated quoted tags
        return [t.strip('"') for t in val.split() if t.strip('"')]

    def _radiolist(self, text, choices, title="Distro Forge", height=18, width=65, list_height=8):
        """
        Show a radiolist. choices is list of (tag, description, on/off) tuples.
        Returns the selected tag.
        """
        args = ["--radiolist", text, str(height), str(width), str(list_height)]
        for tag, desc, state in choices:
            args += [tag, desc, state]
        rc, val = self._run_dialog(*args, title=title)
        if rc != 0:
            return None
        return val.strip('"')

    def _msgbox(self, text, title="Distro Forge", height=10, width=50):
        """Show a message box."""
        self._run_dialog("--msgbox", text, str(height), str(width), title=title)

    def _passwordbox(self, text, title="Distro Forge", height=10, width=50):
        """Show a password input box."""
        rc, val = self._run_dialog(
            "--passwordbox", text, str(height), str(width),
            title=title
        )
        if rc != 0:
            return None
        return val

    def _gauge(self, text, percent, title="Building..."):
        """Show a progress gauge (non-blocking start)."""
        # This is typically used with piped input for real-time progress
        pass

    def _fselect(self, start_path, title="Select File", height=14, width=60):
        """File selection dialog (dialog only, not whiptail)."""
        if self.backend == "dialog":
            rc, val = self._run_dialog(
                "--fselect", str(start_path), str(height), str(width),
                title=title
            )
            if rc != 0:
                return None
            return val
        else:
            # whiptail doesn't have fselect, fall back to inputbox
            return self._inputbox(
                "Enter file path:", default=str(start_path), title=title
            )

    def run(self):
        """Run the full TUI wizard and return a manifest dict."""

        # ── Build Mode ──────────────────────────────────────
        mode = self._menu(
            "How do you want to build your distro?",
            [
                ("remaster", "Modify an existing RHEL/CentOS ISO"),
                ("build_system", "Compose from upstream repos (lorax/pungi)"),
            ],
            title="Build Mode"
        )
        if mode is None:
            return None
        self.manifest["build_mode"] = mode

        # ── Basic Info ──────────────────────────────────────
        name = self._inputbox("Distro Name:", title="[1/9] Basic Info")
        if not name:
            return None
        self.manifest["name"] = name

        version = self._inputbox("Version:", default="1.0", title="[1/9] Basic Info")
        if version is None:
            return None
        self.manifest["version"] = version

        vendor = self._inputbox("Vendor / Organization:", default="", title="[1/9] Basic Info")
        self.manifest["vendor"] = vendor or ""

        bug_url = self._inputbox("Bug Report URL (optional):", default="", title="[1/9] Basic Info")
        self.manifest["bug_url"] = bug_url or ""

        # ── Base ISO / Upstream ─────────────────────────────
        if mode == "build_system":
            upstream = self._menu(
                "Select upstream source:",
                [
                    ("centos-stream-9", "CentOS Stream 9"),
                    ("centos-stream-10", "CentOS Stream 10"),
                    ("rocky-9", "Rocky Linux 9"),
                    ("alma-9", "AlmaLinux 9"),
                    ("custom", "Custom (define your own repos)"),
                ],
                title="[2/9] Upstream Source"
            )
            if upstream is None:
                return None

            arch = self._menu(
                "Target architecture:",
                [
                    ("x86_64", "x86_64 (AMD/Intel 64-bit)"),
                    ("aarch64", "aarch64 (ARM 64-bit)"),
                ],
                title="[2/9] Architecture"
            )

            tool = self._menu(
                "Compose tool:",
                [
                    ("lorax", "Lighter, faster, good for boot ISOs"),
                    ("pungi", "Full compose, production-grade"),
                ],
                title="[2/9] Compose Tool"
            )

            self.manifest["build_system"] = {
                "upstream": upstream,
                "arch": arch or "x86_64",
                "tool": tool or "lorax",
            }
        else:
            iso_path = self._fselect(
                "/", title="[2/9] Select Base ISO"
            )
            if not iso_path:
                iso_path = self._inputbox(
                    "Path to base RHEL/CentOS ISO:",
                    title="[2/9] Base ISO"
                )
            if not iso_path:
                return None
            self.manifest["base_iso"] = iso_path

        # ── Branding ────────────────────────────────────────
        os_id = self._inputbox(
            "OS ID (lowercase, no spaces):",
            default=name.lower().replace(" ", "-"),
            title="[3/9] Branding"
        )
        branding = {
            "os_name": name,
            "os_id": os_id or name.lower().replace(" ", "-"),
            "assets_dir": None,
        }

        if self._yesno("Do you have a branding assets directory?\n(logos, splash images, etc.)", title="[3/9] Branding"):
            assets_dir = self._fselect("./", title="[3/9] Select Assets Directory")
            branding["assets_dir"] = assets_dir

        grub_title = self._inputbox(
            "GRUB bootloader menu title:",
            default=f"Install {name}",
            title="[3/9] Branding"
        )
        branding["grub_title"] = grub_title or f"Install {name}"

        anaconda_title = self._inputbox(
            "Anaconda installer title:",
            default=f"{name} {version}",
            title="[3/9] Branding"
        )
        branding["anaconda_title"] = anaconda_title or f"{name} {version}"

        self.manifest["branding"] = branding

        # ── GUI ─────────────────────────────────────────────
        gui = {"enabled": False, "desktop": None, "default_target": "multi-user"}

        if self._yesno("Enable a desktop environment (GUI)?", title="[4/9] Desktop"):
            desktop = self._radiolist(
                "Select desktop environment:",
                [
                    ("GNOME", "GNOME Desktop", "on"),
                    ("KDE", "KDE Plasma", "off"),
                    ("XFCE", "XFCE (lightweight)", "off"),
                    ("MATE", "MATE Desktop", "off"),
                    ("Cinnamon", "Cinnamon Desktop", "off"),
                ],
                title="[4/9] Desktop"
            )
            gui = {
                "enabled": True,
                "desktop": desktop or "GNOME",
                "default_target": "graphical",
            }

        self.manifest["gui"] = gui

        # ── Repos ───────────────────────────────────────────
        repos = []
        if self._yesno("Add custom yum/dnf repositories?", title="[5/9] Repositories", default_yes=False):
            while True:
                repo_name = self._inputbox(f"Repo #{len(repos)+1} — Name/ID:", title="[5/9] Add Repo")
                if not repo_name:
                    break
                repo_url = self._inputbox(f"Repo '{repo_name}' — Base URL:", title="[5/9] Add Repo")
                if not repo_url:
                    break
                gpgcheck = self._yesno(f"Enable GPG check for '{repo_name}'?", default_yes=False)
                gpgkey = None
                if gpgcheck:
                    gpgkey = self._inputbox("GPG key path or URL:", title="[5/9] GPG Key")

                repos.append({
                    "name": repo_name,
                    "baseurl": repo_url,
                    "gpgcheck": gpgcheck,
                    "gpgkey": gpgkey,
                    "enabled": True,
                })

                if not self._yesno("Add another repo?", default_yes=False):
                    break

        self.manifest["repos"] = repos

        # ── Packages ────────────────────────────────────────
        install_pkgs = self._inputbox(
            "Packages to INSTALL (comma-separated, or empty):",
            default="",
            title="[6/9] Packages"
        )
        remove_pkgs = self._inputbox(
            "Packages to REMOVE (comma-separated, or empty):\n\n"
            "Common: centos-logos, centos-release, centos-stream-release",
            default="",
            title="[6/9] Packages",
            height=12
        )

        packages = {
            "install": [p.strip() for p in (install_pkgs or "").split(",") if p.strip()],
            "remove": [p.strip() for p in (remove_pkgs or "").split(",") if p.strip()],
            "local_rpms": None,
        }

        if self._yesno("Install custom RPMs from a local directory?", default_yes=False, title="[6/9] Packages"):
            rpm_dir = self._fselect("./", title="[6/9] RPMs Directory")
            packages["local_rpms"] = rpm_dir

        self.manifest["packages"] = packages

        # ── Kickstart ───────────────────────────────────────
        kickstart = {"template": None, "root_password_value": None}

        if self._yesno("Use a custom kickstart template?", default_yes=False, title="[7/9] Kickstart"):
            ks_path = self._fselect("./", title="[7/9] Kickstart Template")
            kickstart["template"] = ks_path

        if self._yesno("Set a default root password?", default_yes=False, title="[7/9] Kickstart"):
            pw = self._passwordbox("Enter root password:", title="[7/9] Root Password")
            kickstart["root_password"] = True
            kickstart["root_password_value"] = pw
        else:
            kickstart["root_password"] = False

        tz = self._inputbox("Default timezone:", default="UTC", title="[7/9] Kickstart")
        kickstart["timezone"] = tz or "UTC"

        lang = self._inputbox("Default language:", default="en_US.UTF-8", title="[7/9] Kickstart")
        kickstart["lang"] = lang or "en_US.UTF-8"

        kb = self._inputbox("Keyboard layout:", default="us", title="[7/9] Kickstart")
        kickstart["keyboard"] = kb or "us"

        self.manifest["kickstart"] = kickstart

        # ── Advanced ────────────────────────────────────────
        timeout = self._inputbox("Boot menu timeout (seconds):", default="60", title="[8/9] Advanced")
        self.manifest["boot_timeout"] = int(timeout) if timeout and timeout.isdigit() else 60

        selinux = self._radiolist(
            "SELinux mode:",
            [
                ("enforcing", "SELinux enforcing (recommended)", "on"),
                ("permissive", "SELinux permissive", "off"),
                ("disabled", "SELinux disabled", "off"),
            ],
            title="[8/9] Advanced"
        )
        self.manifest["selinux"] = selinux or "enforcing"

        if self._yesno("Enable firewall?", title="[8/9] Advanced"):
            self.manifest["firewall"] = True
            svc = self._inputbox(
                "Allowed services (comma-separated):",
                default="ssh",
                title="[8/9] Firewall Services"
            )
            self.manifest["firewall_services"] = [
                s.strip() for s in (svc or "ssh").split(",") if s.strip()
            ]
        else:
            self.manifest["firewall"] = False
            self.manifest["firewall_services"] = []

        self.manifest["post_scripts"] = []

        # ── Output ──────────────────────────────────────────
        self.manifest["generate_sample_assets"] = self._yesno(
            "Generate sample branding assets directory?",
            default_yes=False,
            title="[9/9] Output"
        )

        return self.manifest


def run_tui_wizard():
    """Entry point for TUI wizard."""
    try:
        wizard = TUIWizard()
        return wizard.run()
    except RuntimeError as e:
        print(f"❌ {e}")
        return None
