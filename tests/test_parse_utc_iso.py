"""Contract tests for parseUtcIso in review-common.js (naive UTC ISO from server)."""

import math
import re
import unittest
from datetime import datetime, timezone


def parse_utc_iso_ms(iso: str | None) -> float:
    """Python mirror of review-common.js parseUtcIso."""
    if not iso:
        return float("nan")
    s = str(iso).strip()
    if not s:
        return float("nan")
    if re.search(r"[zZ]$", s) or re.search(r"[+-]\d{2}:\d{2}$", s):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return dt.timestamp() * 1000


class ParseUtcIsoTests(unittest.TestCase):
    def test_naive_iso_parsed_as_utc(self):
        naive = "2026-08-26T07:00:13.500632"
        ms = parse_utc_iso_ms(naive)
        expected = datetime(2026, 8, 26, 7, 0, 13, 500632, tzinfo=timezone.utc).timestamp() * 1000
        self.assertAlmostEqual(ms, expected, places=3)

    def test_z_suffix_parsed(self):
        iso = "2026-08-26T07:00:13.500632Z"
        ms = parse_utc_iso_ms(iso)
        expected = datetime(2026, 8, 26, 7, 0, 13, 500632, tzinfo=timezone.utc).timestamp() * 1000
        self.assertAlmostEqual(ms, expected, places=3)

    def test_offset_suffix_parsed(self):
        iso = "2026-08-26T07:00:13.500632+00:00"
        ms = parse_utc_iso_ms(iso)
        expected = datetime(2026, 8, 26, 7, 0, 13, 500632, tzinfo=timezone.utc).timestamp() * 1000
        self.assertAlmostEqual(ms, expected, places=3)

    def test_empty_returns_nan(self):
        self.assertTrue(math.isnan(parse_utc_iso_ms("")))
        self.assertTrue(math.isnan(parse_utc_iso_ms(None)))


if __name__ == "__main__":
    unittest.main()
