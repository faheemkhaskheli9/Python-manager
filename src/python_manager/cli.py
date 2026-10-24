"""Command-line interface to the core features, for scripts and CI (no Qt needed)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn, Optional, Sequence

from . import __version__
from .core import eol, health, imports, interpreters, licenses, lock, projects, python_versions, venvs
from .core.tasks import TaskContext


def _print_rows(rows: list[Sequence[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))] if rows else []
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())


def _emit(args: argparse.Namespace, data: list[dict], rows: list[Sequence[str]]) -> None:
    if args.json:
        print(json.dumps(data, indent=2))
    elif rows:
        _print_rows(rows)


def _support(version: str) -> dict:
    support = eol.support(version)
    return {"support": support.status if support else None,
            "end_of_support": support.end.isoformat() if support and support.end else None}


def _support_label(version: str) -> str:
    support = eol.support(version)
    return support.label if support and support.needs_attention else ""


def cmd_pythons(args: argparse.Namespace) -> int:
    found = python_versions.list_installed() + ([] if args.managed else interpreters.find_system_pythons())
    data = [{"name": i.name, "version": i.version, "kind": i.kind, "executable": str(i.executable),
             **_support(i.version)} for i in found]
    _emit(args, data, [(d["version"], d["kind"], _support_label(d["version"]), d["executable"]) for d in data])
    return 0


def cmd_envs(args: argparse.Namespace) -> int:
    data = []
    for env in venvs.list_envs():
        data.append({"name": env.name, "version": env.version, "path": str(env.path),
                     "managed": env.managed, "broken": venvs.is_broken(env), **_support(env.version)})
    _emit(args, data, [(d["name"], d["version"], "broken" if d["broken"] else _support_label(d["version"]),
                        d["path"]) for d in data])
    return 0


def _fail(message: str) -> NoReturn:
    """Exit with 2, like a failed check, so 1 always means "needs attention"."""
    print(f"python-manager-cli: {message}", file=sys.stderr)
    raise SystemExit(2)


def _find(target: str) -> tuple[Path, str]:
    """The interpreter and a display name for an interpreter path, environment folder or environment name."""
    path = Path(target)
    if path.is_dir() and venvs.is_venv(path):
        env = venvs.load(path.resolve(), managed=False)
        return env.executable, env.name
    if path.is_file():
        return path, str(path)
    for env in venvs.list_envs():
        if env.name == target:
            return env.executable, env.name
    _fail(f"{target!r} is not an interpreter, environment folder or environment name")


def _resolve(target: str) -> Path:
    return _find(target)[0]


def _target(target: Optional[str]) -> tuple[Path, str]:
    """``target``, or the current folder's environment (.venv, venv, env) when none is given."""
    if target:
        return _find(target)
    env = projects.Project(Path.cwd()).env()
    if env is None:
        _fail("the current folder has no .venv, venv or env; name an environment or interpreter")
    return env.executable, env.name


def cmd_check(args: argparse.Namespace) -> int:
    if args.targets:
        executables = [_resolve(t) for t in args.targets]
    else:
        executables = [e.executable for e in venvs.list_envs() if e.valid and not venvs.is_broken(e)]
        executables += [i.executable for i in python_versions.list_installed()]
    if not executables:
        print("Nothing to check.", file=sys.stderr)
        return 0
    ctx = TaskContext(log=(lambda m: print(m, file=sys.stderr)) if args.verbose else None)
    reports = health.check_all(executables, ctx, scan_security=not args.no_security)
    chosen = [reports[str(p)] for p in executables]
    data = [{"executable": r.executable, "outdated": r.outdated,
             "vulnerabilities": [{"package": v.package, "version": v.version, "id": v.id} for v in r.vulns],
             "error": r.error, "security_error": r.security_error} for r in chosen]
    rows = []
    for r in chosen:
        rows.append((r.summary, r.executable))
        rows += [(f"  {name}", f"→ {latest}") for name, latest in sorted(r.outdated.items())]
        rows += [(f"  {health.WARN} {v.package} {v.version}", v.id) for v in r.vulns]
    _emit(args, data, rows)
    failed = any(r.error for r in chosen)
    return 2 if failed else 1 if any(r.needs_attention for r in chosen) else 0


def _source(project: projects.Project, name: Optional[str]) -> Optional[projects.Source]:
    if name:
        path = Path(name) if Path(name).is_absolute() else project.path / name
        if not path.is_file():
            _fail(f"{path} does not exist")
        return projects.Source(path)
    sources = project.sources()
    return sources[0] if sources else None


def cmd_imports(args: argparse.Namespace) -> int:
    folder = Path(args.project).resolve()
    if not folder.is_dir():
        _fail(f"{folder} is not a folder")
    project = projects.Project(folder)
    env = project.env()
    python = _resolve(args.python) if args.python else env.executable if env else None
    if python is None:
        _fail(f"{folder} has no .venv, venv or env; pass --python")
    source = _source(project, args.requirements)
    requirements = projects.read_requirements(source) if source else []
    checks, unreadable = imports.check(folder, requirements, python)
    data = [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks]
    _emit(args, data, [(c.name, c.status, c.detail) for c in checks])
    for path in unreadable:
        print(f"Skipped (could not parse): {path}", file=sys.stderr)
    if not checks and not args.json:
        print(f"Imports match {source.label if source else 'the requirements'}.")
    return 1 if any(c.status != imports.NOT_IMPORTED for c in checks) else 0


FAIL_CATEGORIES = {c.lower().replace(" ", "-"): c for c in
                   (licenses.COPYLEFT, licenses.WEAK_COPYLEFT, licenses.OTHER, licenses.UNKNOWN)}


def cmd_licenses(args: argparse.Namespace) -> int:
    fail_on = set()
    for name in filter(None, (args.fail_on or "").split(",")):
        if name.strip().lower() not in FAIL_CATEGORIES:
            _fail(f"unknown category {name!r}; use {', '.join(FAIL_CATEGORIES)}")
        fail_on.add(FAIL_CATEGORIES[name.strip().lower()])
    python, name = _target(args.target)
    try:
        items = licenses.scan(python)
    except Exception as exc:
        _fail(f"could not read the packages of {name}: {exc}")
    if args.json or args.format == "json":
        print(licenses.to_json(items), end="")
    elif args.format == "csv":
        print(licenses.to_csv(items), end="")
    elif args.format == "markdown":
        print(licenses.to_markdown(items, f"Licenses · {name}"), end="")
    else:
        _print_rows([(i.name, i.version, i.category, i.license or "—") for i in items])
    flagged = [i for i in items if i.category in fail_on]
    for item in flagged:
        print(f"{item.category}: {item.name} {item.version} ({item.license or 'no licence'})", file=sys.stderr)
    return 1 if flagged else 0


def cmd_export(args: argparse.Namespace) -> int:
    fmt = next(f for f in lock.FORMATS if f.key == args.format)
    python, name = _target(args.target)
    info = interpreters.probe(python)
    if info is None:
        _fail(f"{python} is not a working Python")
    output = Path(args.output or fmt.filename)
    ctx = TaskContext(log=lambda m: print(m, file=sys.stderr))
    try:
        result = lock.export(python, fmt, output, name, info["version"], ctx, exclude_tools=not args.include_tools)
    except Exception as exc:
        _fail(f"export failed: {exc}")
    if args.json:
        print(json.dumps({"path": str(result.path), "packages": result.packages, "skipped": result.skipped},
                         indent=2))
    else:
        print(f"Saved {result.packages} packages to {result.path}.")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python-manager-cli", description="Python Manager from the command line.")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = root.add_subparsers(dest="command", required=True)

    def command(name: str, fn, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument("--json", action="store_true", help="print JSON")
        p.set_defaults(fn=fn)
        return p

    p = command("pythons", cmd_pythons, "List installed and system Pythons.")
    p.add_argument("--managed", action="store_true", help="only Pythons installed by the app")
    command("envs", cmd_envs, "List virtual environments.")
    p = command("check", cmd_check, "Check for outdated and vulnerable packages. "
                                    "Exits 1 when something needs attention, 2 when a check failed.")
    p.add_argument("targets", nargs="*", help="interpreters, environment folders or names (default: all)")
    p.add_argument("--no-security", action="store_true", help="skip the vulnerability lookup")
    p.add_argument("-v", "--verbose", action="store_true", help="log progress to stderr")
    p = command("imports", cmd_imports, "Compare a project's imports with its requirements. "
                                        "Exits 1 when an import is not installed or not declared.")
    p.add_argument("project", nargs="?", default=".", help="project folder (default: current folder)")
    p.add_argument("-r", "--requirements", help="requirements file (default: the first the project has)")
    p.add_argument("--python", help="interpreter or environment (default: the project's environment)")
    p = command("licenses", cmd_licenses, "List the licence of each installed package. "
                                          "Exits 1 when a package is in a --fail-on category.")
    p.add_argument("target", nargs="?", help="interpreter, environment folder or name "
                                             "(default: the current folder's environment)")
    p.add_argument("--format", choices=["table", "csv", "markdown", "json"], default="table")
    p.add_argument("--fail-on", metavar="CATEGORIES",
                   help=f"comma-separated categories that fail the check: {', '.join(FAIL_CATEGORIES)}")
    p = command("export", cmd_export, "Save an environment's packages as requirements, a lock file or pyproject.")
    p.add_argument("target", nargs="?", help="interpreter, environment folder or name "
                                             "(default: the current folder's environment)")
    p.add_argument("--format", choices=[f.key for f in lock.FORMATS], default=lock.PINNED.key,
                   help="; ".join(f"{f.key}: {f.label}" for f in lock.FORMATS))
    p.add_argument("-o", "--output", help="file to write (default: the format's usual name in this folder)")
    p.add_argument("--include-tools", action="store_true", help="keep pip, setuptools and wheel")
    return root


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
