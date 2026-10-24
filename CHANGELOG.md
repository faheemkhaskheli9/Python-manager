# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

Every pull request adds its entries under **Unreleased**, ending each with the PR number.
On release, **Unreleased** is renamed to the new version; that section becomes the release notes.

## [Unreleased]

### Added
- Import check: *Check imports…* on the Projects page lists imports no installed package provides,
  imports the requirements do not declare and requirements the code never imports. ([#13])
- Command line: `python-manager-cli` lists Pythons and environments, checks environments for
  outdated and vulnerable packages and checks a project's imports, with JSON output and exit
  codes for CI. ([#13])
- Package history: a snapshot of the packages is saved before each change made from the Packages page,
  *Update all* or *Compare…*; *History…* on the Packages page lists them and restores one. ([#12])
- Compare: *Compare…* on the Packages page shows two interpreters' or environments' packages side by
  side and can install the left side's versions on the right. ([#11])
- Find package: *Find package…* on the Virtual Environments page lists every interpreter and
  environment with a matching package; double-click one to manage its packages. ([#11])
- Rebuild: *Rebuild…* on the Virtual Environments page recreates an environment in the same folder
  on another Python with the same packages, restoring the old one if it fails; it also works when
  the environment's Python is gone. After a Python update the environments on the old Python can
  be rebuilt on the new one in one step. ([#11])
- Packages page: a *Size* column with the disk space of each package, and the total in the status
  line. ([#11])
- Package index: *File → Settings → Package index* sets an index URL (a private index or mirror),
  extra indexes and trusted hosts for every pip, uv and pipx command. ([#10])
- Python updates: the Pythons page shows when an installed Python has a newer patch release and
  *Install update* installs it, listing the environments still on the old one. ([#10])
- License report: *Licenses…* on the Packages page lists each package's licence (from
  `License-Expression`, classifiers or `License`) and its category (permissive, weak copyleft,
  copyleft, public domain, other, unknown); filter it and save it as CSV, Markdown or JSON. ([#9])
- UI smoke tests that build every page, switch themes and open the license report offscreen; CI
  installs PySide6 and runs them on every OS. ([#9])
- Dark theme: *File → Settings → Theme* switches between light, dark and the system's colours;
  status colours stay readable in both. ([#8])
- Projects page: show the Python a project asks for in `.python-version` and `requires-python`,
  warn when its environment does not match, set or remove `.python-version`, and preselect a
  matching Python when creating the environment. ([#8])
- Jupyter kernels: add or remove an environment's kernel from the Virtual Environments page
  (ipykernel is installed when missing); a *Jupyter kernel* column shows which environments have
  one, and *Jupyter kernels…* lists every kernel and removes those whose Python is gone. ([#8])
- Tools page: list command-line tools installed with `uv tool` or pipx with their commands, Python
  and latest version; install (optionally on a chosen Python), upgrade, upgrade all and
  uninstall. ([#7])
- Conda, mamba and micromamba environments are listed read-only on the Virtual Environments page
  with their activation command, and their packages can be viewed on the Packages page. ([#7])
- Projects page: compare against any `requirements*.txt` or `pyproject.toml` with an extra, a
  dependency group or all of them; list installed packages the requirements do not name; refresh
  automatically when a requirements file or the environment changes. ([#6])
- Disk Usage page: flag environments whose base Python is gone or that have not changed for a
  long time, *Select stale*, and delete several items at once. Broken environments are also marked
  on the Virtual Environments page. ([#6])
- *File → Settings*: uv, default Python and location for new environments, check interval,
  security lookup and notifications for scheduled checks, and the stale-environment limit. ([#6])
- Update all: choose which outdated packages to update from a list showing installed and new
  versions, with major versions flagged and, on the Projects page, updates the project's
  requirements exclude left unticked. Afterwards it shows what changed and any broken
  requirements (`pip check`). Available on the Packages, Virtual Environments and Projects pages. ([#5])
- Export / lock: save an environment as pinned `requirements.txt` (all or top-level packages),
  `requirements.txt` with hashes, `pylock.toml` (PEP 751) or `pyproject.toml`; the Projects page
  saves into the project folder. ([#5])
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
- *Use uv when installed* and *Check environments daily* moved from the File menu into
  Settings. ([#6])
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
- Rebuild: environments installed from a folder (editable), archive or VCS keep that source when
  rebuilt from a broken environment. ([#12])
- Rebuild: Jupyter kernels that ran a versioned interpreter (e.g. `python3.12`) are pointed at the
  rebuilt environment. ([#12])
- Rebuild after a Python update no longer includes environments on the free-threaded build of the
  same version. ([#12])
- Environments in the envs folder whose names start with `.` or contain spaces are listed again;
  only rebuild backups are hidden. ([#12])
- Jupyter kernels: a `kernel.json` that is valid JSON but not a kernel spec (`[]`, `null`, a
  non-list `argv`) is skipped instead of stopping the Virtual Environments page from loading, and
  `JUPYTER_PATH` folders now take precedence over the user folder, as in Jupyter. ([#9])
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
[#5]: https://github.com/faheemkhaskheli9/python-manager/pull/5
[#6]: https://github.com/faheemkhaskheli9/python-manager/pull/6
[#7]: https://github.com/faheemkhaskheli9/python-manager/pull/7
[a036314]: https://github.com/faheemkhaskheli9/python-manager/commit/a036314
[2ea1319]: https://github.com/faheemkhaskheli9/python-manager/commit/2ea1319
[3653ddf]: https://github.com/faheemkhaskheli9/python-manager/commit/3653ddf
[#8]: https://github.com/faheemkhaskheli9/python-manager/pull/8
[#9]: https://github.com/faheemkhaskheli9/python-manager/pull/9
[#10]: https://github.com/faheemkhaskheli9/python-manager/pull/10
[#13]: https://github.com/faheemkhaskheli9/python-manager/pull/13
[#12]: https://github.com/faheemkhaskheli9/python-manager/pull/12
[#11]: https://github.com/faheemkhaskheli9/python-manager/pull/11
