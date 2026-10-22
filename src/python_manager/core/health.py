"""Scheduled checks of environments for outdated and vulnerable packages, cached between runs."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from . import config, packages, paths, security
from .deps import normalize
from .security import Vulnerability
from .tasks import NULL, TaskContext

WARN = "⚠"


@dataclass(frozen=True)
class Report:
    executable: str
    checked: float  # time.time() of the check
    outdated: dict[str, str] = field(default_factory=dict)  # name -> latest version
    vulns: tuple[Vulnerability, ...] = ()
    error: str = ""  # the check failed
    security_error: str = ""  # only the vulnerability lookup failed (e.g. offline)

    @property
    def summary(self) -> str:
        parts = []
        if self.outdated:
            parts.append(f"{len(self.outdated)} outdated")
        if self.vulns:
            parts.append(f"{WARN} {len(self.vulns)} vulnerable")
        if not parts:
            return "check failed" if self.error else "up to date"
        return " · ".join(parts)

    @property
    def needs_attention(self) -> bool:
        return bool(self.outdated or self.vulns)

    def current(self, installed: Iterable[packages.Package]) -> "Report":
        """Only the findings that still apply to ``installed`` (packages may have changed since)."""
        versions = {normalize(p.name): p.version for p in installed}
        outdated = {n: v for n, v in self.outdated.items()
                    if normalize(n) in versions and versions[normalize(n)] != v}
        vulns = tuple(v for v in self.vulns if versions.get(normalize(v.package)) == v.version)
        return Report(self.executable, self.checked, outdated, vulns, self.error, self.security_error)


def cache_file() -> Path:
    return paths.cache_dir() / "health.json"


def _to_json(report: Report) -> dict:
    return asdict(report)


def _from_json(data: dict) -> Report:
    vulns = tuple(Vulnerability(**{**v, "aliases": tuple(v.get("aliases", ()))}) for v in data.get("vulns", ()))
    return Report(data["executable"], float(data.get("checked", 0)), dict(data.get("outdated", {})),
                  vulns, data.get("error", ""), data.get("security_error", ""))


def load() -> dict[str, Report]:
    """Reports from the last check, keyed by interpreter path."""
    try:
        data = json.loads(cache_file().read_text(encoding="utf-8"))
        return {key: _from_json(value) for key, value in data.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def save(reports: dict[str, Report]) -> None:
    target = cache_file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: _to_json(r) for k, r in reports.items()}, indent=1), encoding="utf-8")
    tmp.replace(target)


def check(python: Path, ctx: TaskContext = NULL, scan_security: bool = True) -> Report:
    """Outdated packages and, when ``scan_security``, known vulnerabilities for one interpreter."""
    outdated = packages.outdated(python)
    ctx.check()
    vulns: list[Vulnerability] = []
    security_error = ""
    if scan_security:
        try:
            vulns = security.scan(packages.list_packages(python), ctx)
        except Exception as exc:  # e.g. offline: keep the update results
            security_error = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            ctx.log(f"Security check failed: {security_error}")
    return Report(str(python), time.time(), outdated, tuple(vulns), security_error=security_error)


def check_all(executables: Iterable[Path], ctx: TaskContext = NULL, scan_security: bool = True) -> dict[str, Report]:
    """Check every interpreter, save the reports and return all of them (old ones included)."""
    executables = list(executables)
    reports = load()
    for done, python in enumerate(executables):
        ctx.check()
        ctx.progress(done, len(executables))
        ctx.log(f"Checking {python}")
        try:
            reports[str(python)] = check(python, ctx, scan_security)
        except Exception as exc:  # one broken environment must not stop the rest
            reports[str(python)] = Report(str(python), time.time(), error=str(exc).splitlines()[0])
    known = {str(p) for p in executables}
    reports = {k: r for k, r in reports.items() if k in known or Path(k).exists()}
    save(reports)
    config.set("last_health_check", time.time())
    return reports


def is_due() -> bool:
    if not config.get("auto_check"):
        return False
    hours = float(config.get("auto_check_hours") or 24)
    return time.time() - float(config.get("last_health_check") or 0) >= hours * 3600


def summarize(reports: Iterable[Report]) -> str:
    """One sentence for a notification; empty when nothing needs attention."""
    flagged = [r for r in reports if r.needs_attention]
    if not flagged:
        return ""
    outdated = sum(len(r.outdated) for r in flagged)
    vulns = sum(len(r.vulns) for r in flagged)
    found = []
    if outdated:
        found.append(f"{outdated} outdated package{'s' * (outdated != 1)}")
    if vulns:
        found.append(f"{vulns} known vulnerabilit{'ies' if vulns != 1 else 'y'}")
    envs = len(flagged)
    return f"{envs} environment{'s' * (envs != 1)}: {' and '.join(found)}."
