"""
GUI Engine — Manages desktop environment configuration.
Handles: DE selection, graphical target, display manager setup.
"""

from pathlib import Path


class GUIEngine:
    """Configure desktop environment settings."""

    # Package groups for each desktop environment
    DESKTOP_PACKAGES = {
        "gnome": {
            "group": "@gnome-desktop",
            "packages": [
                "gnome-shell",
                "gnome-terminal",
                "nautilus",
                "gnome-tweaks",
                "gdm",
            ],
            "display_manager": "gdm",
        },
        "kde": {
            "group": "@kde-desktop-environment",
            "packages": [
                "plasma-desktop",
                "konsole",
                "dolphin",
                "sddm",
            ],
            "display_manager": "sddm",
        },
        "xfce": {
            "group": "@xfce-desktop",
            "packages": [
                "xfce4-panel",
                "xfce4-terminal",
                "thunar",
                "lightdm",
            ],
            "display_manager": "lightdm",
        },
        "mate": {
            "group": "@mate-desktop",
            "packages": [
                "mate-panel",
                "mate-terminal",
                "caja",
                "lightdm",
            ],
            "display_manager": "lightdm",
        },
        "cinnamon": {
            "group": "@cinnamon-desktop",
            "packages": [
                "cinnamon",
                "nemo",
                "gnome-terminal",
                "lightdm",
            ],
            "display_manager": "lightdm",
        },
    }

    def __init__(self, manifest: dict):
        self.manifest = manifest
        self.gui_config = manifest.get("gui", {})
        self.enabled = self.gui_config.get("enabled", False)
        self.desktop = self.gui_config.get("desktop", "GNOME").lower()

    def get_packages(self):
        """Get the list of packages/groups needed for the selected DE."""
        if not self.enabled:
            return [], []

        desktop_info = self.DESKTOP_PACKAGES.get(self.desktop, {})
        groups = [desktop_info.get("group", "@gnome-desktop")]
        packages = desktop_info.get("packages", [])

        return groups, packages

    def get_display_manager(self):
        """Get the display manager for the selected DE."""
        if not self.enabled:
            return None
        desktop_info = self.DESKTOP_PACKAGES.get(self.desktop, {})
        return desktop_info.get("display_manager", "gdm")

    def get_post_script(self):
        """
        Return post-install shell commands for DE setup.
        These get appended to the kickstart %post section.
        """
        if not self.enabled:
            return (
                "# GUI disabled — ensuring multi-user target\n"
                "systemctl set-default multi-user.target\n"
            )

        dm = self.get_display_manager()
        lines = [
            f"# Enable {self.desktop.upper()} desktop environment",
            f"systemctl set-default graphical.target",
        ]

        if dm:
            lines.append(f"systemctl enable {dm}")

        return "\n".join(lines) + "\n"
