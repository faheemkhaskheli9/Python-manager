"""PATH check: which python and pip a shell runs, what they shadow, and script folders missing from PATH."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from .tasks import capture

WARNING = "warning"
NOTE = "note"

COMMANDS = ("python", "python3", "pip", "pip3", "uv", "pipx") + (("py",) if sys.platform == "win32" else ())
PYTHONS = ("python", "python3")
PIPS = ("pip", "pip3")

_PROBE = (
    "import json,os,platform,sys,sysconfig;"
    "s=getattr(sysconfig,'get_preferred_scheme',lambda k:os.name+'_user')('user');"
    "print(json.dumps({'version':platform.python_version(),'prefix':sys.prefix,"
    "'user_scripts':sysconfig.get_path('scripts',s)}))"
)
# "pip 24.2 from /usr/lib/python3/dist-packages/pip (python 3.12)"
_PIP_VERSION = re.compile(r"^pip (?P<version>\S+) from (?P<location>.+) \(python (?P<python>\d+\.\d+)\)\s*$")


@dataclass(frozen=True)
class Command:
    name: str
    path: Optional[Path]  # what the shell runs, None when not on PATH
    version: str = ""
    detail: str = ""  # python: its prefix; pip: the Python it installs into
    shadowed: tuple[Path, ...] = ()  # other copies later on PATH, never run


@dataclass(frozen=True)
class Entry:
    path: str
    exists: bool
    duplicate: bool
    pythons: tuple[str, ...] = ()  # python executables in the folder


@dataclass(frozen=True)
class Problem:
    severity: str  # WARNING or NOTE
    message: str
    fix: str = ""


@dataclass
class Report:
    entries: list[Entry] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    @property
    def warnings(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == WARNING]

    def command(self, name: str) -> Optional[Command]:
        return next((c for c in self.commands if c.name == name and c.path), None)

    @property
    def summary(self) -> str:
        warnings, notes = len(self.warnings), len(self.problems) - len(self.warnings)
        if not self.problems:
            return f"PATH looks fine: {len(self.entries)} folders."
        return (f"{warnings} warning{'s' * (warnings != 1)}, {notes} note{'s' * (notes != 1)} "
                f"in {len(self.entries)} PATH folders.")

    def to_text(self) -> str:
        lines = [self.summary, "", "Commands:"]
        for c in self.commands:
            lines.append(f"  {c.name}: {c.path or 'not found'}" + (f"  ({c.version})" if c.version else "")
                         + (f"  {c.detail}" if c.detail else ""))
            lines += [f"    also on PATH: {p}" for p in c.shadowed]
        if self.problems:
            lines += ["", "Problems:"]
            for p in self.problems:
                lines.append(f"  [{p.severity}] {p.message}")
                if p.fix:
                    lines.append(f"    fix: {p.fix}")
        lines += ["", "PATH:"]
        for i, e in enumerate(self.entries, 1):
            notes = ([] if e.exists else ["missing"]) + (["duplicate"] if e.duplicate else [])
            lines.append(f"  {i:>2}. {e.path}" + (f"  [{', '.join(notes)}]" if notes else "")
                         + (f"  {', '.join(e.pythons)}" if e.pythons else ""))
        return "\n".join(lines) + "\n"

    def to_json(self) -> dict:
        return {
            "commands": [{"name": c.name, "path": str(c.path) if c.path else None, "version": c.version,
                          "detail": c.detail, "shadowed": [str(p) for p in c.shadowed]} for c in self.commands],
            "problems": [{"severity": p.severity, "message": p.message, "fix": p.fix} for p in self.problems],
            "path": [{"path": e.path, "exists": e.exists, "duplicate": e.duplicate, "pythons": list(e.pythons)}
                     for e in self.entries],
        }


def _norm(path: str) -> str:
    path = os.path.expandvars(os.path.expanduser(path.strip().strip('"')))
    return os.path.normcase(os.path.realpath(path)) if path else ""


def _same(a, b) -> bool:
    return _norm(str(a)) == _norm(str(b))


def path_dirs(path_env: Optional[str] = None) -> list[str]:
    value = os.environ.get("PATH", "") if path_env is None else path_env
    return [d for d in value.split(os.pathsep) if d.strip()]


def _exts() -> list[str]:
    if sys.platform != "win32":
        return [""]
    return [""] + [e.lower() for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]


def _executable(path: Path) -> bool:
    return path.is_file() and (sys.platform == "win32" or os.access(path, os.X_OK))


def find_all(name: str, dirs: Iterable[str]) -> list[Path]:
    """Every copy of ``name`` on PATH in search order; links to the same file are listed once."""
    found: list[Path] = []
    seen: set[str] = set()
    exts = _exts()
    for directory in dirs:
        for ext in exts:
            if sys.platform == "win32" and not ext and not name.lower().endswith(tuple(exts[1:])):
                continue  # Windows only runs a bare name when it carries an extension
            candidate = Path(os.path.expandvars(os.path.expanduser(directory.strip().strip('"')))) / (name + ext)
            if not _executable(candidate):
                continue
            real = _norm(str(candidate))
            if real not in seen:
                seen.add(real)
                found.append(candidate)
            break
    return found


def store_alias(path: Optional[Path]) -> bool:
    """The Microsoft Store stub that opens the Store instead of running Python."""
    return path is not None and "windowsapps" in (part.lower() for part in path.parts)


def probe_python(executable: Path) -> Optional[dict]:
    try:
        proc = capture([str(executable), "-c", _PROBE], timeout=15)
        return json.loads(proc.stdout.strip().splitlines()[-1]) if proc.returncode == 0 else None
    except Exception:  # not a working Python, timeout, unexpected output
        return None


def parse_pip_version(text: str) -> Optional[dict]:
    m = _PIP_VERSION.match(text.strip().splitlines()[-1] if text.strip() else "")
    return m.groupdict() if m else None


def pip_info(cmd: list) -> Optional[dict]:
    """``pip --version`` of a pip command (``[pip]`` or ``[python, "-m", "pip"]``)."""
    try:
        proc = capture([str(c) for c in cmd] + ["--version"], timeout=30)
    except Exception:
        return None
    return parse_pip_version(proc.stdout) if proc.returncode == 0 else None


def _tool_output(cmd: list[str]) -> str:
    try:
        proc = capture(cmd, timeout=15)
    except Exception:
        return ""
    return proc.stdout.strip().splitlines()[-1].strip() if proc.returncode == 0 and proc.stdout.strip() else ""


def tool_bin_dirs(commands: dict[str, Command]) -> dict[str, str]:
    """Folders uv and pipx put tool commands in, keyed by a label."""
    dirs = {}
    uv, pipx = commands.get("uv"), commands.get("pipx")
    if uv and uv.path:
        dirs["uv tool"] = _tool_output([str(uv.path), "tool", "dir", "--bin"])
    if pipx and pipx.path:
        dirs["pipx"] = _tool_output([str(pipx.path), "environment", "--value", "PIPX_BIN_DIR"])
    return {k: v for k, v in dirs.items() if v}


def _has_files(folder: str) -> bool:
    try:
        return any(p.is_file() for p in Path(folder).iterdir())
    except OSError:
        return False


def _pip_matches(pip: dict, python: dict) -> bool:
    """Whether the pip command is the pip this Python runs with ``-m pip``."""
    own = python.get("pip")
    return bool(own) and own["python"] == pip["python"] and _same(own["location"], pip["location"])


def check(path_env: Optional[str] = None,
          probe: Callable[[Path], Optional[dict]] = None,
          pip: Callable[[list], Optional[dict]] = None,
          tool_dirs: Callable[[dict], dict] = None) -> Report:
    """Inspect ``path_env`` (default: this process's PATH) the way a shell searches it."""
    probe, pip, tool_dirs = probe or probe_python, pip or pip_info, tool_dirs or tool_bin_dirs
    dirs = path_dirs(path_env)
    report = Report()

    seen: set[str] = set()
    for directory in dirs:
        key = _norm(directory)
        folder = Path(os.path.expandvars(os.path.expanduser(directory.strip().strip('"'))))
        pythons = tuple(sorted(p.name for p in _list(folder) if re.match(r"^python(\d+(\.\d+)?t?)?(\.exe)?$",
                                                                       p.name, re.IGNORECASE)))
        report.entries.append(Entry(directory, folder.is_dir(), key in seen, pythons))
        seen.add(key)

    info: dict[str, dict] = {}  # probe results of the python and pip commands
    for name in COMMANDS:
        found = find_all(name, dirs)
        if not found:
            report.commands.append(Command(name, None))
            continue
        first, version, detail = found[0], "", ""
        if name in PYTHONS and not store_alias(first):
            data = probe(first)
            if data:
                info[name] = {**data, "pip": pip([first, "-m", "pip"])}
                version, detail = data["version"], data["prefix"]
        elif name in PIPS:
            data = pip([first])
            if data:
                info[name] = data
                version, detail = data["version"], f"Python {data['python']} · {data['location']}"
        report.commands.append(Command(name, first, version, detail, tuple(found[1:])))

    commands = {c.name: c for c in report.commands}
    report.problems = _problems(report, commands, info, tool_dirs(commands), dirs, path_env is None)
    return report


def _list(folder: Path) -> list[Path]:
    try:
        return list(folder.iterdir())
    except OSError:
        return []


def _problems(report: Report, commands: dict[str, Command], info: dict[str, dict],
              tool_dirs: dict[str, str], dirs: list[str], own_path: bool) -> list[Problem]:
    problems: list[Problem] = []
    python = next((commands[n] for n in PYTHONS if commands[n].path), None)
    if python is None:
        if not (commands.get("py") and commands["py"].path):
            problems.append(Problem(WARNING, "No python or python3 on PATH.",
                                    "Add the folder of an installed Python to PATH."))
    for name in PYTHONS:
        if store_alias(commands[name].path):
            problems.append(Problem(WARNING, f"{name} is the Microsoft Store alias ({commands[name].path}); "
                                             "it opens the Store instead of running Python.",
                                    "Turn it off in Settings → Apps → Advanced app settings → App execution "
                                    "aliases, or put your Python's folder before WindowsApps on PATH."))
    p, p3 = info.get("python"), info.get("python3")
    if p and p3 and not _same(p["prefix"], p3["prefix"]):
        problems.append(Problem(WARNING, f"python ({p['version']}) and python3 ({p3['version']}) are different "
                                         "Pythons.",
                                f"python is {commands['python'].path}, python3 is {commands['python3'].path}."))
    for pip_name, python_name, other in (("pip", "python", "python3"), ("pip3", "python3", "python")):
        used = python_name if python_name in info else other
        pip_data, target = info.get(pip_name), info.get(used)
        if pip_data and target and not _pip_matches(pip_data, target):
            problems.append(Problem(WARNING, f"{pip_name} installs into Python {pip_data['python']} "
                                             f"({pip_data['location']}), but {used} runs Python "
                                             f"{target['version']} ({target['prefix']}).",
                                    f"Use “{used} -m pip”, or reorder PATH so both come from one Python."))
    for name in PYTHONS:
        cmd = commands[name]
        if cmd.path and cmd.shadowed:
            problems.append(Problem(NOTE, f"{name} runs {cmd.path}; {len(cmd.shadowed)} other "
                                          f"{'copy' if len(cmd.shadowed) == 1 else 'copies'} later on PATH "
                                          "never run.", "Run them by their full path or reorder PATH."))

    on_path = {_norm(d) for d in dirs}
    wanted = {}
    if python is not None and info.get(python.name, {}).get("user_scripts"):
        wanted[f"pip install --user ({python.name})"] = info[python.name]["user_scripts"]
    wanted.update(tool_dirs)
    for label, folder in wanted.items():
        if folder and _norm(folder) not in on_path and _has_files(folder):
            problems.append(Problem(WARNING, f"Commands installed by {label} are in {folder}, which is not on PATH.",
                                    f"Add {folder} to PATH"
                                    + (" (uv tool update-shell does it)." if label == "uv tool"
                                       else " (pipx ensurepath does it)." if label == "pipx" else ".")))

    missing = [e.path for e in report.entries if not e.exists]
    if missing:
        problems.append(Problem(NOTE, f"{len(missing)} PATH folder{'s' * (len(missing) != 1)} "
                                      f"{'do' if len(missing) != 1 else 'does'} not exist: {', '.join(missing)}.",
                                "Remove them from PATH."))
    duplicates = [e.path for e in report.entries if e.duplicate]
    if duplicates:
        problems.append(Problem(NOTE, f"{len(duplicates)} PATH folder{'s' * (len(duplicates) != 1)} "
                                      f"already on PATH earlier: {', '.join(duplicates)}.",
                                "Remove the later entries (links to the same folder count as one)."))
    if own_path and os.environ.get("VIRTUAL_ENV"):
        problems.append(Problem(NOTE, f"A virtual environment is active: {os.environ['VIRTUAL_ENV']}.",
                                "Run deactivate to check the PATH without it."))
    return problems
