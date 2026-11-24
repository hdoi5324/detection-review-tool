import unittest
from datetime import datetime, timedelta

from detection_review.store import StageTiming, _parse_utc, _utc_now


class UtcNowTests(unittest.TestCase):
    def test_utc_now_is_naive_and_parseable(self):
        stamp = _utc_now()
        parsed = _parse_utc(stamp)
        self.assertIsNone(parsed.tzinfo)
        self.assertLess(abs((datetime.utcnow() - parsed).total_seconds()), 5)

    def test_parse_strips_legacy_aware_suffixes(self):
        naive = datetime(2026, 8, 26, 7, 0, 13, 500632)
        self.assertEqual(_parse_utc(naive.isoformat() + "+00:00"), naive)
        self.assertEqual(_parse_utc(naive.isoformat() + "Z"), naive)
        self.assertEqual(_parse_utc(naive.isoformat()), naive)

    def test_elapsed_sec_with_legacy_aware_open_start(self):
        started = (datetime.utcnow() - timedelta(seconds=5)).isoformat() + "+00:00"
        timing = StageTiming(open_start=started)
        elapsed = timing.elapsed_sec()
        self.assertGreater(elapsed, 3)
        self.assertLess(elapsed, 10)


if __name__ == "__main__":
    unittest.main()
