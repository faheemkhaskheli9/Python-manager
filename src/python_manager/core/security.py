"""Known vulnerabilities in installed packages, looked up in the OSV database (osv.dev)."""

from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Iterable, Optional

from . import net
from .deps import normalize
from .packages import Package
from .tasks import NULL, TaskContext

QUERY_URL = "https://api.osv.dev/v1/querybatch"
VULN_URL = "https://api.osv.dev/v1/vulns/{id}"
PAGE_URL = "https://osv.dev/vulnerability/{id}"
BATCH = 1000  # querybatch limit


@dataclass(frozen=True)
class Vulnerability:
    id: str
    package: str
    version: str
    summary: str = ""
    aliases: tuple[str, ...] = ()
    severity: str = ""  # e.g. HIGH, MODERATE; empty when OSV has none
    fixed: str = ""  # lowest version that fixes it, empty when unknown

    @property
    def url(self) -> str:
        return PAGE_URL.format(id=self.id)

    @property
    def title(self) -> str:
        cve = next((a for a in self.aliases if a.startswith("CVE-")), "")
        return f"{self.id} ({cve})" if cve else self.id


def _version_key(version: str):
    from packaging.version import Version

    return Version(version)


def fixed_version(vuln: dict, package: str, installed: str) -> str:
    """Lowest fixed version above ``installed`` for ``package``; falls back to the last one listed."""
    fixes = []
    for affected in vuln.get("affected", []):
        pkg = affected.get("package", {})
        if pkg.get("ecosystem") != "PyPI" or normalize(pkg.get("name", "")) != normalize(package):
            continue
        for rng in affected.get("ranges", []):
            fixes += [e["fixed"] for e in rng.get("events", []) if "fixed" in e]
    if not fixes:
        return ""
    try:
        newer = [f for f in fixes if _version_key(f) > _version_key(installed)]
        return min(newer, key=_version_key) if newer else ""
    except Exception:  # packaging missing or a non-PEP 440 version
        return fixes[-1]


def _severity(vuln: dict) -> str:
    severity = (vuln.get("database_specific") or {}).get("severity")
    return str(severity).upper() if severity else ""


def _query(packages: list[Package], ctx: TaskContext) -> dict[str, list[Package]]:
    """Vulnerability id -> the installed packages it affects."""
    found: dict[str, list[Package]] = {}
    for start in range(0, len(packages), BATCH):
        chunk = packages[start:start + BATCH]
        queries = [{"package": {"name": p.name, "ecosystem": "PyPI"}, "version": p.version} for p in chunk]
        while queries:
            ctx.check()
            results = net.post_json(QUERY_URL, {"queries": queries}).get("results", [])
            follow_up = []
            for query, pkg, result in zip(queries, chunk, results):
                for vuln in result.get("vulns") or []:
                    found.setdefault(vuln["id"], []).append(pkg)
                if result.get("next_page_token"):
                    follow_up.append(({**query, "page_token": result["next_page_token"]}, pkg))
            queries = [q for q, _ in follow_up]
            chunk = [p for _, p in follow_up]
    return found


def _details(vuln_id: str) -> Optional[dict]:
    try:
        return net.get_json(VULN_URL.format(id=urllib.parse.quote(vuln_id)))
    except Exception:  # still report the id without details
        return None


def scan(packages: Iterable[Package], ctx: TaskContext = NULL) -> list[Vulnerability]:
    """Known vulnerabilities affecting the installed versions of ``packages``."""
    packages = [p for p in packages if p.name and p.version]
    ctx.log(f"Checking {len(packages)} packages against the OSV database…")
    found = _query(packages, ctx)
    ids = sorted(found)
    details: dict[str, Optional[dict]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for done, (vuln_id, data) in enumerate(zip(ids, pool.map(_details, ids)), 1):
            details[vuln_id] = data
            ctx.progress(done, len(ids))
            ctx.check()
    result = []
    for vuln_id in ids:
        data = details[vuln_id] or {"summary": "Details could not be loaded."}
        for pkg in found[vuln_id]:
            result.append(Vulnerability(
                id=vuln_id,
                package=pkg.name,
                version=pkg.version,
                summary=data.get("summary") or (data.get("details") or "").strip().split("\n")[0],
                aliases=tuple(data.get("aliases") or ()),
                severity=_severity(data),
                fixed=fixed_version(data, pkg.name, pkg.version),
            ))
    result.sort(key=lambda v: (v.package.lower(), v.id))
    affected = len({normalize(v.package) for v in result})
    ctx.log(f"Found {len(result)} known vulnerabilities in {affected} packages." if result
            else "No known vulnerabilities found.")
    return result


def upgrade_specs(vulns: Iterable[Vulnerability]) -> list[str]:
    """Install specs that move each affected package to a version with all known fixes."""
    needed: dict[str, list[str]] = {}
    for v in vulns:
        if v.fixed:
            needed.setdefault(v.package, []).append(v.fixed)
    specs = []
    for name, fixes in sorted(needed.items(), key=lambda kv: kv[0].lower()):
        try:
            target = max(fixes, key=_version_key)
        except Exception:
            target = fixes[-1]
        specs.append(f"{name}>={target}")
    return specs
