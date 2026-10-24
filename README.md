# Python Manager

A cross-platform desktop app (Windows, macOS, Linux) for managing Python from a UI:

- **Python versions** – browse, download, install and uninstall any CPython version
  (including pre-releases and free-threaded builds). Existing system Pythons are detected too.
- **Packages** – list, install (any version from PyPI), upgrade, uninstall and download packages
  for any interpreter or virtual environment. Install from wheel/sdist/`requirements.txt`,
  check for updates and export the environment. Package names autocomplete from the full PyPI list.
- **Update all** – one click lists every outdated package with its installed and new version,
  flags major versions and, on the Projects page, updates the project's requirements exclude.
  Untick what to keep, update the rest, and see what changed plus any broken requirements.
- **Export / lock** – save any environment as `requirements.txt` (all packages or top-level only,
  pinned), `requirements.txt` with hashes, a [PEP 751](https://peps.python.org/pep-0751/)
  `pylock.toml` lock file, or `pyproject.toml`. From the Projects page the file is saved into the
  project folder.
- **Security check** – look up known vulnerabilities in the installed packages in the
  [OSV database](https://osv.dev), see severity and fixed versions, and upgrade to fixed versions.
- **Dependencies** – see what each package requires and what requires it (tree view and a
  "Required by" column). Uninstalling warns about packages that still depend on the selection and
  offers to remove dependencies that are no longer needed.
- **Fast backend** – uses [uv](https://docs.astral.sh/uv/) for installs and environment creation when
  it is on `PATH` (toggle in *File → Settings*), falling back to pip and `venv`.
- **Favourite packages** – star any package; favourites are shown with ★, can be filtered,
  installed into any environment in one click, and optionally installed into new environments.
- **Virtual environments** – create environments from any installed Python, manage their packages,
  open an activated terminal, add existing environments or delete them. Clone an environment
  (optionally onto another Python), update or export it, and create a new environment from a
  `requirements.txt` or `pyproject.toml`.
- **Projects** – add a project folder with `pyproject.toml`, `requirements.txt` or `uv.lock`. The app
  finds its environment (`.venv`, `venv` or `env`) or creates `.venv`, lists each requirement as
  OK, missing or wrong version, and syncs it in one click (`uv sync --frozen` when there is a
  `uv.lock` and uv is installed). Compare against any `requirements*.txt`, or `pyproject.toml` with
  an extra, a dependency group (PEP 735) or all of them; installed packages the requirements do not
  list are shown too. The comparison refreshes when a requirements file or the environment changes.
- **Tools** – command-line tools installed with `uv tool` or pipx in one list, with their commands,
  Python and the latest version on PyPI. Install a tool (optionally on a chosen Python), upgrade
  one or all, or uninstall it.
- **Conda environments** – conda, mamba and micromamba environments are listed read-only on the
  Virtual Environments page with their activation command; their packages can be viewed but are
  changed with conda.
- **Scheduled checks** – every environment is checked in the background (daily by default) for
  outdated and vulnerable packages. Results show in an *Updates* column, as a count next to
  *Virtual Environments* and in a desktop notification (*File → Check environments now*).
- **Disk usage** – size of every environment, installed Python, the download cache and the pip and
  uv caches; clean a cache or delete environments from the same page. Environments whose Python is
  gone or that have not changed for a long time are flagged, and *Select stale* selects them all.
- **Settings** – *File → Settings*: uv on or off, the default Python and folder for new
  environments, how often environments are checked, whether the check includes the security
  lookup and shows notifications, and when an environment counts as stale.
- **Log file** – everything shown in the Output panel, plus errors, is written to a rotating log
  (*File → Open log file*) to attach to bug reports.

## Screenshots

| Packages | Projects |
|---|---|
| ![Packages](docs/screenshots/packages.png) | ![Projects](docs/screenshots/projects.png) |
| **Virtual environments** | **Disk usage** |
| ![Virtual environments](docs/screenshots/virtual-environments.png) | ![Disk usage](docs/screenshots/disk-usage.png) |

## Run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e .[dev]
python-manager          # or: python -m python_manager
```

Requires Python 3.9+ and PySide6 (installed automatically).

## How it works

| Feature | Implementation |
|---|---|
| Python downloads | Relocatable CPython builds from [python-build-standalone](https://github.com/astral-sh/python-build-standalone), verified with SHA-256 and extracted into the app data folder. Uninstall removes that folder. No admin rights needed. |
| Packages | `uv pip … --python <interpreter>` when uv is available, otherwise the interpreter's own `pip`; version details come from the PyPI JSON API. Downloads always use pip. |
| Name autocomplete | PyPI's JSON simple index (`https://pypi.org/simple/`), cached in the app data folder and refreshed weekly. |
| Security check | Installed name/version pairs are sent to the OSV batch API (`api.osv.dev`); nothing else leaves the machine. |
| Dependencies | Read from installed package metadata (`importlib.metadata`) inside the target interpreter. |
| Virtual environments | `uv venv` when uv is available, otherwise standard library `venv`. |
| Projects | Requirements are read from `requirements.txt` (following `-r` includes) or `pyproject.toml` and compared with the environment's installed metadata; markers are evaluated for the environment's Python. |
| Scheduled checks | `pip list --outdated` plus the security check for each environment and app-installed Python, at most once a day; results are cached in `cache/health.json`. |
| Update all | `pip list --outdated` for the list, `pip install --upgrade` for the chosen packages, then `pip check` for broken requirements (uv equivalents when uv is used). |
| Export / lock | Versions come from installed metadata; hashes and file URLs for `pylock.toml` and hashed requirements come from the PyPI JSON API. Packages not on PyPI are left out and listed. |
| Tools | `uv tool list --show-paths` and `pipx list --json`; install, upgrade and uninstall run the same manager's commands. Latest versions come from the PyPI JSON API. |
| Conda | Found without running conda: `~/.conda/environments.txt`, `CONDA_PREFIX`, `CONDA_EXE`, `MAMBA_ROOT_PREFIX` and the usual install folders (`miniconda3`, `anaconda3`, `miniforge3`, …). The Python version is read from `conda-meta`. |
| Disk usage | Folder sizes without following symlinks. pip's cache honours `PIP_CACHE_DIR`; uv's comes from `uv cache dir` and is cleaned with `uv cache clean`. |

App data (installed Pythons, environments, download cache, `config.json`, `logs/`):

| OS | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\PythonManager` |
| macOS | `~/Library/Application Support/PythonManager` |
| Linux | `~/.local/share/python-manager` |

Set `PYTHON_MANAGER_HOME` to use another folder. Set `GITHUB_TOKEN` to raise the GitHub API rate limit
when listing many releases.

## Project layout

```
src/python_manager/
  core/   # UI-independent logic (no Qt): python_versions, packages, deps, venvs, projects, projectfile,
          # lock, security, health, disk, tools, conda, logs
  ui/     # PySide6 widgets: one page per feature, background task runner
tests/    # pytest suite for core (runs offline)
```

## Tests

```bash
pytest
```

## Download

Ready-to-run builds for Windows, macOS (Apple silicon and Intel) and Linux are attached to each
[GitHub release](https://github.com/faheemkhaskheli9/python-manager/releases). Unzip and run
*Python Manager*; no Python installation is needed.

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Every pull request adds its entries under **Unreleased**, each
ending with the PR number, e.g. `([#12])`; CI fails otherwise (label `skip-changelog` for
changes users never notice).

## Release

Rename **Unreleased** in `CHANGELOG.md` to the new version (e.g. `## [0.2.0] - 2026-11-01`),
bump `version` in `pyproject.toml` and `src/python_manager/__init__.py`, then push a version tag; the `release` workflow builds every platform with PyInstaller and publishes
a release with the archives, using that changelog section as release notes:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

Build locally:

```bash
pip install . pyinstaller
pyinstaller --noconfirm --windowed --name "Python Manager" --collect-submodules python_manager src/python_manager/__main__.py
```
