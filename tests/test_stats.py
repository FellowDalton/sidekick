"""compute_stats() must be a deterministic, UTC-binned aggregate over ledger events,
tolerant of pre-learning-layer lines (missing fields), with an injectable `today` so
streak tests are stable; regenerate() must embed it under the feed's "stats" key."""
import datetime as dt
import json, tempfile, unittest
from pathlib import Path

import sidekick


def ev(**over):
    e = {"task": "T", "category": "chore", "completed_at": "2026-06-10T21:30:00Z",
         "sat_for_hours": 50, "orchestrator": None}
    e.update(over)
    return e


TODAY = dt.date(2026, 6, 10)   # a Wednesday


class ComputeStats(unittest.TestCase):
    def test_empty_ledger(self):
        s = sidekick.compute_stats([], today=TODAY)
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["by_category"], {})
        self.assertIsNone(s["median_sat_hours"])
        self.assertEqual(s["by_weekday"], [0] * 7)
        self.assertEqual(s["by_hour"], [0] * 24)
        self.assertEqual(s["streak_days"], 0)

    def test_by_category_counts_and_uncategorized(self):
        s = sidekick.compute_stats([ev(), ev(category="phone"), ev(category=None)], today=TODAY)
        self.assertEqual(s["by_category"], {"chore": 1, "phone": 1, "uncategorized": 1})
        self.assertEqual(s["total"], 3)

    def test_median_ignores_null_and_averages_even_counts(self):
        odd = [ev(sat_for_hours=1), ev(sat_for_hours=100), ev(sat_for_hours=3),
               ev(sat_for_hours=None)]
        self.assertEqual(sidekick.compute_stats(odd, today=TODAY)["median_sat_hours"], 3)
        even = [ev(sat_for_hours=h) for h in (1, 2, 3, 4)]
        self.assertEqual(sidekick.compute_stats(even, today=TODAY)["median_sat_hours"], 2.5)

    def test_weekday_and_hour_histogram_utc(self):
        # 2026-06-10T21:30Z is a Wednesday, hour 21 UTC (23:30 in Copenhagen — binned in UTC)
        s = sidekick.compute_stats([ev()], today=TODAY)
        self.assertEqual(s["by_weekday"], [0, 0, 1, 0, 0, 0, 0])
        self.assertEqual(s["by_hour"][21], 1)
        self.assertEqual(sum(s["by_hour"]), 1)

    def test_streak_counts_back_from_today(self):
        events = [ev(completed_at=f"2026-06-{d:02d}T10:00:00Z") for d in (10, 9, 8, 5)]
        self.assertEqual(sidekick.compute_stats(events, today=TODAY)["streak_days"], 3)

    def test_streak_grace_when_today_is_empty(self):
        # nothing cleared today yet — the streak isn't broken until the day is over
        events = [ev(completed_at=f"2026-06-{d:02d}T10:00:00Z") for d in (9, 8)]
        self.assertEqual(sidekick.compute_stats(events, today=TODAY)["streak_days"], 2)

    def test_streak_broken_by_a_full_missed_day(self):
        events = [ev(completed_at="2026-06-08T10:00:00Z")]
        self.assertEqual(sidekick.compute_stats(events, today=TODAY)["streak_days"], 0)

    def test_tolerates_legacy_and_malformed_events(self):
        events = [
            {"task": "pre-learning-layer line"},        # no category/completed_at/sat_for_hours
            ev(completed_at="not-a-date"),               # unparseable stamp: skipped from bins
            ["not", "a", "dict"],                        # defensive: skipped entirely
        ]
        s = sidekick.compute_stats(events, today=TODAY)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_category"], {"chore": 1, "uncategorized": 1})
        self.assertEqual(sum(s["by_weekday"]), 0)
        self.assertEqual(sum(s["by_hour"]), 0)
        self.assertEqual(s["streak_days"], 0)


class RegenerateEmbedsStats(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "tasks").mkdir()
        (self.vault / "ledger.jsonl").write_text(json.dumps(ev()) + "\n", encoding="utf-8")
        sidekick.configure(str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()

    def test_stats_key_in_feed(self):
        sidekick.regenerate()
        text = (self.vault / "sidekick-data.js").read_text(encoding="utf-8")
        payload = json.loads(text.split("window.SIDEKICK = ", 1)[1].rstrip().rstrip(";"))
        self.assertIn("stats", payload)
        self.assertEqual(payload["stats"]["total"], 1)
        self.assertEqual(payload["stats"]["by_category"], {"chore": 1})
        self.assertEqual(len(payload["stats"]["by_weekday"]), 7)
        self.assertEqual(len(payload["stats"]["by_hour"]), 24)


if __name__ == "__main__":
    unittest.main()
