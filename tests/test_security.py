from python_manager.core import net, security
from python_manager.core.packages import Package

JINJA = {
    "id": "GHSA-462w-v97r-4m45",
    "summary": "Jinja2 sandbox escape",
    "aliases": ["CVE-2019-10906"],
    "database_specific": {"severity": "HIGH"},
    "affected": [
        {"package": {"ecosystem": "PyPI", "name": "jinja2"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.10.1"}]}]},
        {"package": {"ecosystem": "PyPI", "name": "jinja2"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "3.0"}, {"fixed": "3.0.1"}]}]},
    ],
}
JINJA_2 = {
    "id": "PYSEC-2021-66",
    "details": "ReDoS in Jinja2.\nMore text.",
    "affected": [{"package": {"ecosystem": "PyPI", "name": "Jinja2"},
                  "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.11.3"}]}]}],
}
NO_FIX = {"id": "GHSA-nofix", "summary": "Unfixed", "affected": []}


def test_scan(monkeypatch):
    queries = []

    def post_json(url, payload, timeout=60):
        assert url == security.QUERY_URL
        queries.append(payload["queries"])
        results = []
        for q in payload["queries"]:
            name = q["package"]["name"]
            if name == "Jinja2" and "page_token" not in q:
                results.append({"vulns": [{"id": JINJA["id"]}], "next_page_token": "p2"})
            elif name == "Jinja2":
                results.append({"vulns": [{"id": JINJA_2["id"]}]})
            elif name == "oldlib":
                results.append({"vulns": [{"id": NO_FIX["id"]}]})
            else:
                results.append({})
        return {"results": results}

    details = {v["id"]: v for v in (JINJA, JINJA_2, NO_FIX)}
    monkeypatch.setattr(net, "post_json", post_json)
    monkeypatch.setattr(net, "get_json", lambda url, *a, **k: details[url.rsplit("/", 1)[1]])

    pkgs = [Package("Jinja2", "2.10"), Package("requests", "2.32.0"), Package("oldlib", "1.0")]
    vulns = security.scan(pkgs)

    assert [q["package"]["name"] for q in queries[0]] == ["Jinja2", "requests", "oldlib"]
    assert queries[0][0]["version"] == "2.10"
    assert queries[1] == [{"package": {"name": "Jinja2", "ecosystem": "PyPI"}, "version": "2.10", "page_token": "p2"}]
    assert [(v.package, v.id, v.fixed) for v in vulns] == [
        ("Jinja2", "GHSA-462w-v97r-4m45", "2.10.1"),
        ("Jinja2", "PYSEC-2021-66", "2.11.3"),
        ("oldlib", "GHSA-nofix", ""),
    ]
    first = vulns[0]
    assert first.severity == "HIGH"
    assert first.title == "GHSA-462w-v97r-4m45 (CVE-2019-10906)"
    assert first.url == "https://osv.dev/vulnerability/GHSA-462w-v97r-4m45"
    assert vulns[1].summary == "ReDoS in Jinja2."
    assert security.upgrade_specs(vulns) == ["Jinja2>=2.11.3"]


def test_scan_reports_ids_when_details_fail(monkeypatch):
    monkeypatch.setattr(net, "post_json", lambda *a, **k: {"results": [{"vulns": [{"id": "X-1"}]}]})

    def broken(*_a, **_k):
        raise OSError("timeout")

    monkeypatch.setattr(net, "get_json", broken)
    vulns = security.scan([Package("a", "1.0")])
    assert [(v.id, v.fixed) for v in vulns] == [("X-1", "")]
    assert vulns[0].summary


def test_clean_scan_skips_details(monkeypatch):
    monkeypatch.setattr(net, "post_json", lambda *a, **k: {"results": [{}]})
    monkeypatch.setattr(net, "get_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no details needed")))
    assert security.scan([Package("a", "1.0")]) == []


def test_fixed_version_picks_lowest_newer():
    assert security.fixed_version(JINJA, "Jinja2", "3.0") == "3.0.1"
    assert security.fixed_version(JINJA, "jinja2", "2.9") == "2.10.1"
    assert security.fixed_version(JINJA, "other", "2.9") == ""
