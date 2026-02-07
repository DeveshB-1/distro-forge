"""
Interactive wizard — walks the user through all distro config options.
Returns a manifest dict ready for the build engine.
Supports two modes: Remaster (from ISO) and Build System (from scratch).
"""

import os
import sys
from pathlib import Path


def ask(prompt, default=None, required=True, validator=None):
    """Ask a question with optional default and validation."""
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"  {prompt}{suffix}: ").strip()
        if not answer and default is not None:
            answer = default
        if required and not answer:
            print("    ⚠️  This field is required.")
            continue
        if validator:
            err = validator(answer)
            if err:
                print(f"    ⚠️  {err}")
                continue
        return answer


def ask_yn(prompt, default="y"):
    """Yes/no question."""
    suffix = "(Y/n)" if default == "y" else "(y/N)"
    answer = input(f"  {prompt} {suffix}: ").strip().lower()
    if not answer:
        answer = default
    return answer in ("y", "yes")


def ask_choice(prompt, choices, default=1):
    """Multiple choice question."""
    print(f"  {prompt}")
    for i, choice in enumerate(choices, 1):
        marker = "→" if i == default else " "
        print(f"    {marker} ({i}) {choice}")
    while True:
        answer = input(f"  Choice [{default}]: ").strip()
        if not answer:
            return choices[default - 1]
        try:
            idx = int(answer)
            if 1 <= idx <= len(choices):
                return choices[idx - 1]
        except ValueError:
            # Check if they typed the name directly
            for c in choices:
                if answer.lower() == c.lower():
                    return c
        print(f"    ⚠️  Pick 1-{len(choices)}")


def ask_list(prompt, allow_empty=True):
    """Collect a comma-separated list."""
    raw = input(f"  {prompt}: ").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def validate_iso_path(path):
    """Validate that the ISO path exists."""
    if not Path(path).exists():
        return f"File not found: {path}"
    if not path.lower().endswith(".iso"):
        return "File doesn't look like an ISO (expected .iso extension)"
    return None


def validate_dir_path(path):
    """Validate directory exists."""
    if path and not Path(path).is_dir():
        return f"Directory not found: {path}"
    return None


def run_wizard():
    """Run the interactive wizard and return a manifest dict."""
    print("Let's build your distro. Answer the questions below.\n")
    print("─" * 44)

    # ── Step 0: Build Mode ──────────────────────────────────
    print("\n🔧 Build Mode\n")
    mode = ask_choice(
        "How do you want to build?",
        [
            "Remaster — Modify an existing RHEL/CentOS ISO",
            "Build System — Compose a fresh ISO from upstream repos",
        ],
        default=1
    )
    is_build_system = "Build System" in mode

    manifest = {}
    manifest["build_mode"] = "build_system" if is_build_system else "remaster"

    # ── Step 1: Basic Info ──────────────────────────────────
    print("\n📛 [1/9] Basic Info\n")
    manifest["name"] = ask("Distro name", required=True)
    manifest["version"] = ask("Version", default="1.0")
    manifest["vendor"] = ask("Vendor / Organization", default="")
    manifest["bug_url"] = ask("Bug report URL (optional)", default="", required=False)

    # ── Step 2: Base ISO or Upstream ────────────────────────
    if is_build_system:
        print("\n🌐 [2/9] Upstream Source\n")
        build_system = {}

        upstream = ask_choice(
            "Which upstream to base on?",
            [
                "centos-stream-9",
                "centos-stream-10",
                "rocky-9",
                "alma-9",
                "Custom (define your own repos)",
            ],
            default=1
        )

        if "Custom" in upstream:
            build_system["upstream"] = "custom"
            print("\n  Define your upstream repos:")
            custom_repos = {}
            while True:
                repo_id = ask("    Repo ID (e.g. baseos)")
                repo_url = ask("    Base URL")
                custom_repos[repo_id] = repo_url
                if not ask_yn("    Add another?", default="n"):
                    break
            build_system["upstream_repos"] = custom_repos
        else:
            build_system["upstream"] = upstream

        build_system["arch"] = ask_choice(
            "Target architecture?",
            ["x86_64", "aarch64"],
            default=1
        )

        build_system["tool"] = ask_choice(
            "Compose tool?",
            [
                "lorax — Lighter, faster, good for boot/install ISOs",
                "pungi — Full compose, production-grade, multi-variant",
            ],
            default=1
        )
        # Extract just the tool name
        build_system["tool"] = build_system["tool"].split(" —")[0].strip()

        manifest["build_system"] = build_system

    else:
        print("\n💿 [2/9] Base ISO\n")
        manifest["base_iso"] = ask(
            "Path to base RHEL/CentOS ISO",
            required=True,
            validator=validate_iso_path
        )

    # ── Step 3: Branding ────────────────────────────────────
    print("\n🎨 [3/9] Branding\n")
    branding = {}
    branding["os_name"] = manifest["name"]
    branding["os_id"] = ask(
        "OS ID (lowercase, no spaces)",
        default=manifest["name"].lower().replace(" ", "-")
    )

    if ask_yn("Do you have a branding assets directory? (logos, splash, etc.)"):
        branding["assets_dir"] = ask(
            "Assets directory path",
            validator=validate_dir_path
        )
        print("    Expected structure:")
        print("      assets/")
        print("      ├── grub/        # GRUB theme files")
        print("      ├── plymouth/    # Plymouth boot splash")
        print("      ├── anaconda/    # Installer sidebar/topbar images")
        print("      └── logos/       # OS logos (SVG/PNG)")
    else:
        branding["assets_dir"] = None
        print("    ℹ️  Will use text-based branding (no custom graphics)")

    if ask_yn("Customize GRUB bootloader text?"):
        branding["grub_title"] = ask("GRUB menu title", default=f"Install {manifest['name']}")
    else:
        branding["grub_title"] = f"Install {manifest['name']}"

    if ask_yn("Customize Anaconda installer title?"):
        branding["anaconda_title"] = ask(
            "Anaconda title bar text",
            default=f"{manifest['name']} {manifest['version']}"
        )
    else:
        branding["anaconda_title"] = f"{manifest['name']} {manifest['version']}"

    manifest["branding"] = branding

    # ── Step 4: GUI ─────────────────────────────────────────
    print("\n🖥️  [4/9] Desktop Environment\n")
    gui = {}
    gui["enabled"] = ask_yn("Enable GUI (desktop environment)?")
    if gui["enabled"]:
        gui["desktop"] = ask_choice(
            "Which desktop?",
            ["GNOME", "KDE", "XFCE", "MATE", "Cinnamon"],
            default=1
        )
        gui["default_target"] = "graphical"
    else:
        gui["desktop"] = None
        gui["default_target"] = "multi-user"
    manifest["gui"] = gui

    # ── Step 5: Repos ───────────────────────────────────────
    print("\n📦 [5/9] Custom Repositories\n")
    repos = []
    if ask_yn("Add custom yum/dnf repositories?"):
        while True:
            print(f"\n    Repo #{len(repos) + 1}:")
            repo = {}
            repo["name"] = ask("    Repo name/ID")
            repo["baseurl"] = ask("    Base URL")
            repo["gpgcheck"] = ask_yn("    Enable GPG check?", default="n")
            if repo["gpgcheck"]:
                repo["gpgkey"] = ask("    GPG key path or URL")
            else:
                repo["gpgkey"] = None
            repo["enabled"] = True
            repos.append(repo)
            if not ask_yn("    Add another repo?", default="n"):
                break
    manifest["repos"] = repos

    # ── Step 6: Packages ────────────────────────────────────
    print("\n📥 [6/9] Packages\n")
    packages = {}

    print("  Packages to INSTALL (comma-separated, or empty to skip):")
    packages["install"] = ask_list("  Install")

    print("  Packages to REMOVE (comma-separated, or empty to skip):")
    print("  Common: centos-logos, centos-release, centos-stream-release")
    packages["remove"] = ask_list("  Remove")

    if ask_yn("Install custom RPMs from a local directory?", default="n"):
        packages["local_rpms"] = ask(
            "Path to directory containing .rpm files",
            validator=validate_dir_path
        )
    else:
        packages["local_rpms"] = None

    manifest["packages"] = packages

    # ── Step 7: Kickstart ───────────────────────────────────
    print("\n📝 [7/9] Kickstart Configuration\n")
    kickstart = {}
    if ask_yn("Use a custom kickstart template?", default="n"):
        kickstart["template"] = ask("Path to kickstart template (.cfg)")
    else:
        kickstart["template"] = None
        print("    ℹ️  Will generate a default kickstart")

    kickstart["root_password"] = ask_yn("Set a default root password?", default="n")
    if kickstart["root_password"]:
        import getpass
        kickstart["root_password_value"] = getpass.getpass("    Root password: ")
    else:
        kickstart["root_password_value"] = None

    kickstart["timezone"] = ask("Default timezone", default="UTC")
    kickstart["lang"] = ask("Default language", default="en_US.UTF-8")
    kickstart["keyboard"] = ask("Keyboard layout", default="us")

    manifest["kickstart"] = kickstart

    # ── Step 8: Advanced ────────────────────────────────────
    print("\n⚙️  [8/9] Advanced Options\n")

    if ask_yn("Customize boot menu timeout?", default="n"):
        manifest["boot_timeout"] = int(ask("Timeout in seconds", default="60"))
    else:
        manifest["boot_timeout"] = 60

    if ask_yn("Add post-install scripts?", default="n"):
        scripts = []
        while True:
            script_path = ask("    Script path")
            scripts.append(script_path)
            if not ask_yn("    Add another?", default="n"):
                break
        manifest["post_scripts"] = scripts
    else:
        manifest["post_scripts"] = []

    if ask_yn("Enable SELinux?", default="y"):
        manifest["selinux"] = ask_choice(
            "SELinux mode?",
            ["enforcing", "permissive"],
            default=1
        )
    else:
        manifest["selinux"] = "disabled"

    if ask_yn("Enable firewall?", default="y"):
        manifest["firewall"] = True
        manifest["firewall_services"] = ask_list(
            "  Allowed services (e.g. ssh, http, https)"
        )
    else:
        manifest["firewall"] = False
        manifest["firewall_services"] = []

    # ── Step 9: Output ──────────────────────────────────────
    print("\n📤 [9/9] Output\n")
    if ask_yn("Generate sample branding assets structure?", default="n"):
        manifest["generate_sample_assets"] = True
    else:
        manifest["generate_sample_assets"] = False

    print("\n" + "─" * 44)

    return manifest
