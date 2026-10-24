import sys
from pathlib import Path

from python_manager.core import deps, sizes, venvs


def test_scan_sums_recorded_files(tmp_path):
    env = venvs.create("sized", Path(sys.executable), tmp_path, with_pip=False)
    site = venvs.site_packages(env)[0]
    (site / "pm_sized").mkdir()
    (site / "pm_sized" / "__init__.py").write_bytes(b"x" * 1000)
    dist = site / "pm_sized-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: pm-sized\nVersion: 1.0\n", encoding="utf-8")
    (dist / "RECORD").write_text("pm_sized/__init__.py,,\npm_sized-1.0.dist-info/METADATA,,\n"
                                 "pm_sized-1.0.dist-info/RECORD,,\n", encoding="utf-8")
    unlisted = site / "pm_bare-1.0.dist-info"
    unlisted.mkdir()
    (unlisted / "METADATA").write_text("Metadata-Version: 2.1\nName: pm_bare\nVersion: 1.0\n", encoding="utf-8")

    result = sizes.scan(env.executable)
    size = result[deps.normalize("pm-sized")]
    assert size > 1000 and size < 2000
    assert result["pm-bare"] is None
