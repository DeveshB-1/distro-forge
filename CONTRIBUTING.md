# Contributing to Distro Forge

Thanks for wanting to contribute! Here's how to get started.

## Getting Started

1. Fork the repo
2. Clone your fork
3. Create a feature branch: `git checkout -b my-feature`
4. Make your changes
5. Test against a real ISO if possible
6. Submit a PR

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/distro-forge.git
cd distro-forge
pip install -r requirements.txt
```

## Project Structure

- `forge.py` — CLI entrypoint
- `engine/` — Core modules (each file is self-contained)
  - `wizard.py` — Interactive config collection
  - `iso.py` — ISO extraction and repacking
  - `branding.py` — OS branding (GRUB, release files, etc.)
  - `packages.py` — RPM/repo management
  - `kickstart.py` — Kickstart generation
  - `gui.py` — Desktop environment configuration
  - `builder.py` — Build pipeline orchestrator

## Guidelines

- Keep modules self-contained — each engine file should work independently
- No hardcoded distro names or branding — everything comes from user input or manifest
- Fail gracefully — if a tool is missing, warn and skip, don't crash
- Test on both CentOS Stream 9 and RHEL 9 if possible

## Ideas for Contributions

- [ ] Support for Fedora/Rocky/Alma base ISOs
- [ ] TUI interface (curses/textual)
- [ ] Web UI for the wizard
- [ ] ARM64 ISO support
- [ ] Custom installer themes (full Anaconda theming)
- [ ] CI pipeline for automated ISO builds
- [ ] Plugin system for custom build steps
- [ ] Docker-based build environment

## Reporting Issues

Please include:
- Base ISO used (name, version, arch)
- Python version
- OS of the build machine
- Full error output

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
