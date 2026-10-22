# Python Manager

A cross-platform desktop app (Windows, macOS, Linux) for managing Python from a UI:

- **Python versions** – browse, download, install and uninstall any CPython version
  (including pre-releases and free-threaded builds). Existing system Pythons are detected too.
- **Packages** – list, install (any version from PyPI), upgrade, uninstall and download packages
  for any interpreter or virtual environment. Install from wheel/sdist/`requirements.txt`,
  check for updates, upgrade all outdated packages at once and export `requirements.txt`.
- **Dependencies** – see what each package requires and what requires it (tree view and a
  "Required by" column). Uninstalling warns about packages that still depend on the selection and
  offers to remove dependencies that are no longer needed.
- **Fast backend** – uses [uv](https://docs.astral.sh/uv/) for installs and environment creation when
  it is on `PATH` (toggle under *File → Use uv when installed*), falling back to pip and `venv`.
- **Favourite packages** – star any package; favourites are shown with ★, can be filtered,
  installed into any environment in one click, and optionally installed into new environments.
- **Virtual environments** – create environments from any installed Python, manage their packages,
  open an activated terminal, add existing environments or delete them. Clone an environment
  (optionally onto another Python), export it as `requirements.txt` (pinned) or `pyproject.toml`
  (top-level packages), and create a new environment from either file.
- **Log file** – everything shown in the Output panel, plus errors, is written to a rotating log
  (*File → Open log file*) to attach to bug reports.

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
| Dependencies | Read from installed package metadata (`importlib.metadata`) inside the target interpreter. |
| Virtual environments | `uv venv` when uv is available, otherwise standard library `venv`. |

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
  core/   # UI-independent logic (no Qt): python_versions, packages, deps, venvs, projectfile, logs
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
