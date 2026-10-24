import csv
import io
import json
import sys
from pathlib import Path

from python_manager.core import licenses, venvs
from python_manager.core.licenses import COPYLEFT, OTHER, PERMISSIVE, PUBLIC_DOMAIN, UNKNOWN, WEAK_COPYLEFT


def entry(**kw):
    return {"name": "pkg", "version": "1.0", "expression": "", "license": "", "classifiers": [], "files": [], **kw}


def test_category():
    assert licenses.category("MIT") == PERMISSIVE
    assert licenses.category("BSD-3-Clause") == PERMISSIVE
    assert licenses.category("Apache Software License") == PERMISSIVE
    assert licenses.category("LGPL-3.0-or-later") == WEAK_COPYLEFT
    assert licenses.category("MPL-2.0") == WEAK_COPYLEFT
    assert licenses.category("GPL-3.0-only") == COPYLEFT
    assert licenses.category("AGPL-3.0") == COPYLEFT
    assert licenses.category("Unlicense") == PUBLIC_DOMAIN
    assert licenses.category("Other/Proprietary License") == OTHER
    assert licenses.category("") == UNKNOWN
    assert licenses.category("MIT OR GPL-2.0") == PERMISSIVE
    assert licenses.category("MIT AND GPL-2.0") == COPYLEFT
    assert licenses.category("GPL-2.0-or-later WITH Classpath-exception-2.0") == COPYLEFT
    assert licenses.category("(MIT OR Apache-2.0) AND GPL-3.0-only") == COPYLEFT
    assert licenses.category("GPL-3.0-only AND (MIT OR Apache-2.0)") == COPYLEFT
    assert licenses.category("MIT OR (GPL-3.0-only AND BSD-3-Clause)") == PERMISSIVE
    assert licenses.category("(LGPL-2.1-or-later WITH foo-exception) OR GPL-3.0") == WEAK_COPYLEFT
    assert licenses.category("Apache Software License OR MIT License") == PERMISSIVE


def test_resolve_prefers_expression_then_classifiers():
    assert licenses.resolve(entry(expression="MIT", license="BSD")).license == "MIT"
    item = licenses.resolve(entry(classifiers=["License :: OSI Approved",
                                               "License :: OSI Approved :: Apache Software License",
                                               "License :: OSI Approved :: MIT License"], license="whatever"))
    assert (item.license, item.source, item.category) == ("Apache-2.0 OR MIT", "classifier", PERMISSIVE)
    assert licenses.resolve(entry(license="BSD-3-Clause")).source == "License"
    assert licenses.resolve(entry(license="UNKNOWN")).license == ""
    long_text = "Copyright (c) 2020 Someone\n\n" + "Permission is hereby granted " * 20
    assert licenses.resolve(entry(license=long_text)).license == "Copyright (c) 2020 Someone"


def test_reports():
    items = [licenses.resolve(entry(name="a", expression="MIT", files=["LICENSE"])),
             licenses.resolve(entry(name="b|c", license="GPL-3.0"))]
    assert licenses.summary(items) == {COPYLEFT: 1, PERMISSIVE: 1}
    rows = list(csv.reader(io.StringIO(licenses.to_csv(items))))
    assert rows[1] == ["a", "1.0", "MIT", PERMISSIVE, "License-Expression", "LICENSE"]
    md = licenses.to_markdown(items, "Licenses of env")
    assert md.startswith("# Licenses of env") and "| b\\|c | 1.0 | GPL-3.0 | Copyleft |" in md
    assert json.loads(licenses.to_json(items))[0]["category"] == PERMISSIVE


def test_scan_real_environment(tmp_path):
    env = venvs.create_at(tmp_path / "env", Path(sys.executable))
    found = {i.name.lower(): i for i in licenses.scan(env.executable)}
    assert "pip" in found and found["pip"].category == PERMISSIVE
