"""Compare what a project's code imports with its requirements and the packages installed for it."""

from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .deps import normalize
from .tasks import CommandError, capture

NOT_INSTALLED = "Not installed"  # imported, but no installed package provides it
NOT_DECLARED = "Not declared"  # imported from an installed package the requirements do not name
NOT_IMPORTED = "Not imported"  # required, but the code imports none of its modules (may be a tool)

# Folders never scanned: environments are also skipped by their pyvenv.cfg.
SKIP_DIRS = {"__pycache__", "node_modules", "site-packages", "build", "dist"}

# Runs inside the target interpreter, so it must work on any Python 3.8+ with only the stdlib.
# Prints the top-level modules each installed distribution provides and the standard library's
# module names (sys.stdlib_module_names on 3.10+, the stdlib folder before that).
_SCRIPT = r"""
import json, os, pkgutil, sys, sysconfig
from importlib import metadata

def ident(name):
    return name.isidentifier() and not name.startswith("__")

modules = {}
for dist in metadata.distributions():
    name = dist.metadata["Name"]
    if not name:
        continue
    found = set()
    top = dist.read_text("top_level.txt")
    if top:
        found.update(line.strip() for line in top.splitlines())
    else:
        for file in dist.files or ():
            parts = file.parts
            if not parts or parts[0] == ".." or parts[0].endswith((".dist-info", ".egg-info", ".data")):
                continue
            if len(parts) > 1:
                found.add(parts[0])
            elif file.suffix in (".py", ".pyd", ".so"):
                found.add(parts[0].split(".")[0])
    for module in found:
        if ident(module):
            modules.setdefault(module, [])
            if name not in modules[module]:
                modules[module].append(name)

stdlib = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
if not getattr(sys, "stdlib_module_names", None):
    path = sysconfig.get_paths()["stdlib"]
    stdlib.update(m.name for m in pkgutil.iter_modules([path, os.path.join(path, "lib-dynload")]))
print(json.dumps({"modules": modules, "stdlib": sorted(stdlib)}))
"""


@dataclass(frozen=True)
class ImportCheck:
    name: str  # module for NOT_INSTALLED / NOT_DECLARED, requirement name for NOT_IMPORTED
    status: str
    detail: str  # providing packages, or the first file that imports the module


def _is_env(folder: Path) -> bool:
    return (folder / "pyvenv.cfg").is_file()


def python_files(folder: Path) -> list[Path]:
    """The project's .py files, without hidden folders, environments and build output."""
    result = []
    for root, dirs, files in os.walk(folder):
        here = Path(root)
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith(".") and d not in SKIP_DIRS and not _is_env(here / d))
        result += [here / f for f in sorted(files) if f.endswith(".py")]
    return result


_IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(t, ast.Name) and t.id in _IMPORT_ERRORS for t in types)


def _optional(tree: ast.AST) -> set[int]:
    """ids of the nodes inside ``try`` blocks that catch ImportError: those imports may be missing."""
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(_catches_import_error(h) for h in node.handlers):
            result.update(id(n) for stmt in node.body for n in ast.walk(stmt))
    return result


def module_imports(source: str) -> set[str]:
    """Top-level names of the absolute imports in ``source``, except optional ones (guarded by
    ``try``/``except ImportError``)."""
    tree = ast.parse(source)
    optional = _optional(tree)
    found = set()
    for node in ast.walk(tree):
        if id(node) in optional:
            continue
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def scan(folder: Path) -> tuple[dict[str, Path], set[str], list[Path]]:
    """(top-level module -> first file importing it, the project's own module names, unreadable files)."""
    imports: dict[str, Path] = {}
    local: set[str] = set()
    unreadable = []
    for path in python_files(folder):
        local.add(path.stem)
        if path.name == "__init__.py":
            local.add(path.parent.name)
        try:
            names = module_imports(path.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            unreadable.append(path)
            continue
        for name in sorted(names):
            imports.setdefault(name, path)
    # Folders without __init__.py (namespace packages, src layouts) are importable too.
    for base in (folder, folder / "src"):
        if base.is_dir():
            local.update(p.name for p in base.iterdir() if p.is_dir() and p.name.isidentifier())
    return imports, local, unreadable


def environment(python: Path) -> tuple[dict[str, list[str]], set[str]]:
    """(top-level module -> distribution names providing it, standard library module names)."""
    cmd = [str(python), "-I", "-c", _SCRIPT]
    proc = capture(cmd, timeout=120)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr)
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    return data["modules"], set(data["stdlib"])


def requirement_names(requirements: Iterable[str]) -> dict[str, str]:
    """Normalised name -> name as written, for each requirement that parses."""
    from packaging.requirements import InvalidRequirement, Requirement

    result = {}
    for text in requirements:
        try:
            name = Requirement(text).name
        except InvalidRequirement:
            continue
        result.setdefault(normalize(name), name)
    return result


def compare(imports: dict[str, Path], local: set[str], requirements: Iterable[str],
            modules: dict[str, list[str]], stdlib: set[str], folder: Path) -> list[ImportCheck]:
    """Imports no installed package provides or the requirements do not declare, then requirements
    whose modules are never imported. Requirements that are not installed are left out: their
    modules are unknown, and the requirements comparison already lists them."""
    declared = requirement_names(requirements)
    provided: dict[str, set[str]] = {}  # normalised distribution -> its modules
    for module, dists in modules.items():
        for dist in dists:
            provided.setdefault(normalize(dist), set()).add(module)

    def where(path: Path) -> str:
        try:
            return path.relative_to(folder).as_posix()
        except ValueError:
            return str(path)

    result = []
    used: set[str] = set()
    for module in sorted(imports, key=str.lower):
        if module in local or module in stdlib or module == "__future__":
            continue
        dists = modules.get(module)
        if not dists:
            result.append(ImportCheck(module, NOT_INSTALLED, where(imports[module])))
            continue
        used.update(normalize(d) for d in dists)
        if not any(normalize(d) in declared for d in dists):
            result.append(ImportCheck(module, NOT_DECLARED, ", ".join(sorted(dists, key=str.lower))))
    for key, name in sorted(declared.items()):
        if key in provided and key not in used:
            result.append(ImportCheck(name, NOT_IMPORTED, ", ".join(sorted(provided[key], key=str.lower))))
    return result


def check(folder: Path, requirements: Iterable[str], python: Path) -> tuple[list[ImportCheck], list[Path]]:
    """Compare ``folder``'s imports with ``requirements`` and ``python``'s packages.

    Returns the findings and the files that could not be parsed.
    """
    imports, local, unreadable = scan(folder)
    modules, stdlib = environment(python)
    return compare(imports, local, list(requirements), modules, stdlib, folder), unreadable
