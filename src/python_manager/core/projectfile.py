"""Read and write the files environments are exported to: requirements.txt and pyproject.toml."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from . import deps, packages
from .tasks import NULL, CommandError, TaskContext

# Not worth pinning when exporting or cloning; every environment gets its own.
SKIP = deps.KEEP


def _requirement_name(line: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
    return deps.normalize(match.group(1)) if match else ""


def clone_requirements(python: Path, skip: frozenset[str] | set[str] = SKIP) -> str:
    """``freeze`` output for ``python`` without the packages in ``skip`` (the packaging tools)."""
    try:
        frozen = packages.freeze(python)
    except CommandError as exc:
        if "No module named pip" not in exc.output:
            raise
        # No pip in the environment: installed metadata still gives exact versions.
        frozen = "\n".join(f"{d.name}=={d.version}" for d in deps.load_graph(python).values())
    lines = [l for l in frozen.splitlines() if _requirement_name(l) not in skip]
    return "\n".join(lines) + "\n" if lines else ""


def top_level(graph: deps.Graph, skip: frozenset[str] | set[str] = SKIP) -> list[deps.Dist]:
    """Installed packages nothing else requires (what was asked for), sorted by name."""
    used = deps.required_by(graph)
    return sorted((d for k, d in graph.items() if k not in used and k not in skip), key=lambda d: d.name.lower())


def pyproject_for(python: Path, name: str, python_version: str, skip: frozenset[str] | set[str] = SKIP) -> str:
    """A minimal pyproject.toml listing the top-level packages (those nothing else requires)."""
    top = top_level(deps.load_graph(python), skip)
    major_minor = ".".join(python_version.split(".")[:2])
    lines = [
        "[project]",
        f"name = {json.dumps(re.sub(r'[^A-Za-z0-9._-]+', '-', name) or 'project')}",
        'version = "0.1.0"',
        f'requires-python = ">={major_minor}"',
        "dependencies = [",
        *(f"    {json.dumps(f'{d.name}>={d.version}')}," for d in top),
        "]",
        "",
    ]
    return "\n".join(lines)


_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'|#[^\n]*|\{[^}]*\}|\]')


def _toml_table(text: str, table: str) -> str:
    match = re.search(rf"^\[{re.escape(table)}\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    return match.group(1) if match else ""


def _toml_string(value: str) -> str:
    return json.loads(value) if value[0] == '"' else value[1:-1]


def _toml_arrays(text: str, table: str) -> dict[str, list]:
    """Arrays of strings (and ``{include-group = "…"}`` tables) in one TOML table, without a TOML library."""
    body, result = _toml_table(text, table), {}
    for start in re.finditer(r'^\s*("[^"]+"|[A-Za-z0-9_.-]+)\s*=\s*\[', body, re.M):
        key = start.group(1).strip('"')
        items = result[key] = []
        for token in _TOKEN.finditer(body, start.end()):
            value = token.group()
            if value == "]":
                break
            if value[0] in "\"'":
                items.append(_toml_string(value))
            elif value[0] == "{":
                group = re.search(r'include-group\s*=\s*("[^"]*"|\'[^\']*\')', value)
                if group:
                    items.append({"include-group": _toml_string(group.group(1))})
    return result


def _toml_fallback(text: str) -> dict:
    """The parts of a pyproject.toml read here, for Python < 3.11 (no tomllib)."""
    project = _toml_arrays(text, "project")
    for key in ("name", "requires-python"):
        value = re.search(rf'^{key}\s*=\s*("[^"]*"|\'[^\']*\')', _toml_table(text, "project"), re.M)
        if value:
            project[key] = _toml_string(value.group(1))
    project["optional-dependencies"] = _toml_arrays(text, "project.optional-dependencies")
    return {"project": project, "dependency-groups": _toml_arrays(text, "dependency-groups")}


def read_pyproject(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:
        return _toml_fallback(text)
    return tomllib.loads(text)


def pyproject_dependencies(path: Path) -> list[str]:
    return list(read_pyproject(path).get("project", {}).get("dependencies", []))


def pyproject_options(path: Path) -> tuple[list[str], list[str]]:
    """Names of the optional-dependency extras and the dependency groups (PEP 735) in a pyproject.toml."""
    data = read_pyproject(path)
    return list(data.get("project", {}).get("optional-dependencies", {})), list(data.get("dependency-groups", {}))


def pyproject_requirements(path: Path, extras: Iterable[str] = (), groups: Iterable[str] = ()) -> list[str]:
    """The project's dependencies plus those of the chosen extras and dependency groups.

    Extras that name the project itself (``myapp[test]``) and ``include-group`` entries are expanded.
    """
    data = read_pyproject(path)
    project = data.get("project", {})
    own = deps.normalize(project.get("name", "")) if project.get("name") else None
    optional = {deps.normalize(k): v for k, v in project.get("optional-dependencies", {}).items()}
    group_table = {deps.normalize(k): v for k, v in data.get("dependency-groups", {}).items()}
    result: list[str] = []
    seen: set[tuple[str, str]] = set()

    def add(items, kind: str, name: str) -> None:
        if (kind, name) in seen:
            return
        seen.add((kind, name))
        for item in items:
            if isinstance(item, dict):
                included = deps.normalize(item.get("include-group", ""))
                add(group_table.get(included, []), "group", included)
                continue
            match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?\s*(;.*)?$", item)
            if own and match and deps.normalize(match.group(1)) == own and not match.group(3):
                for extra in (match.group(2) or "").split(","):
                    if extra.strip():
                        add(optional.get(deps.normalize(extra), []), "extra", deps.normalize(extra))
                continue
            if item not in result:
                result.append(item)

    add(project.get("dependencies", []), "base", "")
    for extra in extras:
        add(optional.get(deps.normalize(extra), []), "extra", deps.normalize(extra))
    for group in groups:
        add(group_table.get(deps.normalize(group), []), "group", deps.normalize(group))
    return result


def install_file(python: Path, path: Path, ctx: TaskContext = NULL) -> None:
    """Install the packages listed in a requirements file or a pyproject.toml."""
    path = Path(path)
    if path.name.endswith(".toml"):
        specs = pyproject_dependencies(path)
        if specs:
            packages.install(python, specs, ctx)
        else:
            ctx.log(f"{path.name} lists no dependencies.")
    else:
        packages.install_requirements(python, path, ctx)
