# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

Every pull request adds its entries under **Unreleased**, ending each with the PR number.
On release, **Unreleased** is renamed to the new version; that section becomes the release notes.

## [Unreleased]

### Added
- Loading indicators: a spinner over each list while it loads (installed and available Pythons,
  packages, environments, project requirements, disk usage), a status bar indicator for background
  work, and "checking…" in the *Updates* column while environments are checked. ([#4])
- Projects page: add a folder with `pyproject.toml`, `requirements.txt` or `uv.lock`, see which
  requirements are missing or have the wrong version in its environment, create `.venv` and sync
  it (`uv sync --frozen` when a `uv.lock` and uv are present). ([#3])
- Scheduled checks: every environment is checked daily in the background for outdated and
  vulnerable packages; results appear in a new *Updates* column, as a count in the sidebar, in the
  Packages page and as a desktop notification. *File → Check environments now* runs it on
  demand. ([#3])
- Disk Usage page: sizes of environments, installed Pythons, the download cache and the pip and uv
  caches, with buttons to clean a cache or delete an environment. ([#3])
- Screenshots in the README. ([#3])

### Changed
- Faster package lists: names, versions and dependencies are read from installed metadata in one
  call instead of `pip list` plus a second call (about 3× faster with pip); they also load when
  pip is missing. ([#4])
- Python build lists, scheduled checks, disk usage sizes and project comparisons run their
  requests in parallel. ([#4])
- Filtering the package list hides rows instead of rebuilding the table; tables repaint once
  after filling; settings are read from disk only when the file changed. ([#4])
- Environments named `.venv`, `venv` or `env` outside the app folder are listed as
  `<project>/.venv`. ([#3])

### Fixed
- Security results of one environment no longer show up after switching to another. ([#3])

## [0.2.0] - 2026-10-22

### Added
- Release builds: pushing a `v*` tag builds the app with PyInstaller for Windows x64, macOS
  (Apple silicon and Intel) and Linux x64 and publishes a GitHub release with the archives.
  Release notes come from this changelog. ([#1])
- Rotating log file (`logs/python-manager.log` in the app data folder) with task output,
  failures and unhandled exceptions; open it from *File → Open log file*. ([#1])
- Clone a virtual environment with the same packages, optionally onto another Python. ([#1])
- Export a virtual environment as `requirements.txt` (pinned versions) or `pyproject.toml`
  (top-level packages). ([#1])
- Create a virtual environment from a `requirements.txt` or `pyproject.toml`. ([#1])
- Package name autocomplete from the full PyPI package list, cached locally and refreshed
  weekly. ([#1])
- Security check: looks up the installed packages in the OSV database, marks affected packages
  in a *Security* column, lists each vulnerability with severity, fixed version and a link to
  osv.dev, and upgrades to fixed versions in one click. ([#1])
- This changelog, a pull request template and a CI check that every pull request updates it. ([#1])

### Changed
- Creating an environment with packages removes the half-created environment if installing the
  packages fails. ([#1])
- The About dialog shows the log file location. ([#1])
- `packaging` is now a dependency, for comparing versions. ([#1])

## [0.1.0] - 2026-10-22

First version. These changes were committed directly to `main`, before pull requests were used.

### Added
- Download, install and uninstall CPython versions, including pre-releases and free-threaded
  builds, from python-build-standalone, verified with SHA-256. ([a036314])
- Detection of Python installations already on the system. ([a036314])
- Install, upgrade, uninstall and download packages for any interpreter or virtual environment;
  install from wheel, sdist or `requirements.txt`; check for updates; export
  `requirements.txt`. ([a036314])
- Create, register, open in a terminal and delete virtual environments. ([a036314])
- PySide6 interface with background tasks, progress, cancellation and an Output panel. ([a036314])
- Favourite packages: star column, *Favourites only* filter, install missing favourites in one
  click, and an option to install favourites into new environments. ([2ea1319])
- uv backend for package operations and environment creation when uv is installed, with a
  *File → Use uv when installed* toggle; pip and `venv` remain the fallback. ([3653ddf])
- *Upgrade all* button for every outdated package. ([3653ddf])
- Dependency view: requires / required-by tree, a *Required by* column, a warning before
  uninstalling packages others depend on, and an option to remove dependencies left
  unused. ([3653ddf])
- Offline pytest suite and a CI workflow for Windows, macOS and Linux. ([a036314])

[Unreleased]: https://github.com/faheemkhaskheli9/python-manager/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/faheemkhaskheli9/python-manager/compare/3653ddf...v0.2.0
[0.1.0]: https://github.com/faheemkhaskheli9/python-manager/commits/3653ddf
[#1]: https://github.com/faheemkhaskheli9/python-manager/pull/1
[#3]: https://github.com/faheemkhaskheli9/python-manager/pull/3
[#4]: https://github.com/faheemkhaskheli9/python-manager/pull/4
[a036314]: https://github.com/faheemkhaskheli9/python-manager/commit/a036314
[2ea1319]: https://github.com/faheemkhaskheli9/python-manager/commit/2ea1319
[3653ddf]: https://github.com/faheemkhaskheli9/python-manager/commit/3653ddf
