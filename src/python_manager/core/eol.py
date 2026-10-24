"""End-of-life status of CPython versions, from a built-in release-cycle table (no network)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

SUPPORTED = "Supported"
ENDS_SOON = "Ends soon"
END_OF_LIFE = "End of life"

SOON = timedelta(days=180)

# End of security support per minor version (https://devguide.python.org/versions/).
# Versions newer than the table are treated as supported; others missing from it as end of life.
END_OF_SUPPORT = {
    (2, 7): date(2020, 1, 1),
    (3, 6): date(2021, 12, 23),
    (3, 7): date(2023, 6, 27),
    (3, 8): date(2024, 10, 7),
    (3, 9): date(2025, 10, 31),
    (3, 10): date(2026, 10, 31),
    (3, 11): date(2027, 10, 31),
    (3, 12): date(2028, 10, 31),
    (3, 13): date(2029, 10, 31),
    (3, 14): date(2030, 10, 31),
    (3, 15): date(2031, 10, 31),
}


@dataclass(frozen=True)
class Support:
    status: str
    end: Optional[date]  # None when the version is newer or older than the table

    @property
    def label(self) -> str:
        if self.end is None:
            return self.status
        if self.status == END_OF_LIFE:
            return f"{self.status} since {self.end.isoformat()}"
        return f"{self.status} (until {self.end.isoformat()})"

    @property
    def needs_attention(self) -> bool:
        return self.status != SUPPORTED


def _minor(version: str) -> Optional[tuple[int, int]]:
    m = re.match(r"(\d+)\.(\d+)", version or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def support(version: str, today: Optional[date] = None) -> Optional[Support]:
    """Support status of a version such as ``3.12.4`` or ``3.14.0rc1``; None when it cannot be read."""
    minor = _minor(version)
    if minor is None:
        return None
    today = today or date.today()
    end = END_OF_SUPPORT.get(minor)
    if end is None:
        # Missing below the newest entry means an old release (2.6, 3.0–3.5).
        return Support(SUPPORTED if minor > max(END_OF_SUPPORT) else END_OF_LIFE, None)
    if today >= end:
        return Support(END_OF_LIFE, end)
    return Support(ENDS_SOON if end - today <= SOON else SUPPORTED, end)
