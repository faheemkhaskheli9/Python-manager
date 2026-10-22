"""Read and write the files environments are exported to: requirements.txt and pyproject.toml."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import deps, packages
from .tasks import NULL, CommandError, TaskContext

# Not worth pinning when exporting or cloning; every environment gets its own.
SKIP = deps.KEEP


def _requirement_name(line: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
    return deps.normalize(match.group(1)) if match else ""


def clone_requirements(python: Path) -> str:
    """``freeze`` output for ``python`` without the packaging tools."""
    try:
        frozen = packages.freeze(python)
    except CommandError as exc:
        if "No module named pip" not in exc.output:
            raise
        # No pip in the environment: installed metadata still gives exact versions.
        frozen = "\n".join(f"{d.name}=={d.version}" for d in deps.load_graph(python).values())
    lines = [l for l in frozen.splitlines() if _requirement_name(l) not in SKIP]
    return "\n".join(lines) + "\n" if lines else ""


def pyproject_for(python: Path, name: str, python_version: str) -> str:
    """A minimal pyproject.toml listing the top-level packages (those nothing else requires)."""
    graph = deps.load_graph(python)
    used = deps.required_by(graph)
    top = sorted((d for k, d in graph.items() if k not in used and k not in SKIP), key=lambda d: d.name.lower())
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


def _toml_dependencies(text: str) -> list[str]:
    """``project.dependencies`` without a TOML library (Python < 3.11)."""
    section = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not section:
        return []
    start = re.search(r"^dependencies\s*=\s*\[", section.group(1), re.M)
    if not start:
        return []
    result = []
    for token in re.finditer(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'|#[^\n]*|\]', section.group(1)[start.end():]):
        text = token.group()
        if text == "]":
            break
        if text[0] == '"':
            result.append(json.loads(text))
        elif text[0] == "'":
            result.append(text[1:-1])
    return result


def pyproject_dependencies(path: Path) -> list[str]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:
        return _toml_dependencies(text)
    return list(tomllib.loads(text).get("project", {}).get("dependencies", []))


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
