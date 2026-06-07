import unittest
import weather_compare as wc
from datetime import date as _date


class TestScaffold(unittest.TestCase):
    def test_dataclasses_importable(self):
        loc = wc.Location("Des Moines", "KDSM", "America/Chicago")
        self.assertEqual(loc.station, "KDSM")
        s = wc.DailySummary(70.0, 50.0, 55.0, 40.0, "Clear", 24)
        self.assertEqual(s.sample_count, 24)


class TestConvert(unittest.TestCase):
    def test_c_to_f(self):
        self.assertAlmostEqual(wc.c_to_f(0), 32.0)
        self.assertAlmostEqual(wc.c_to_f(100), 212.0)
        self.assertAlmostEqual(wc.c_to_f(-40), -40.0)


class TestSeasonalTarget(unittest.TestCase):
    def test_trough_equals_min(self):
        self.assertAlmostEqual(wc.seasonal_target(20, 30.0, 75.0, 20), 30.0, places=6)

    def test_peak_near_max(self):
        self.assertAlmostEqual(wc.seasonal_target(203, 30.0, 75.0, 20), 75.0, places=1)

    def test_june_value(self):
        self.assertAlmostEqual(wc.seasonal_target(158, 30.0, 75.0, 20), 68.8, delta=0.5)


class TestCloudPct(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(wc.cloud_amount_to_pct("CLR"), 0.0)
        self.assertEqual(wc.cloud_amount_to_pct("SKC"), 0.0)
        self.assertEqual(wc.cloud_amount_to_pct("FEW"), 19.0)
        self.assertEqual(wc.cloud_amount_to_pct("SCT"), 44.0)
        self.assertEqual(wc.cloud_amount_to_pct("BKN"), 75.0)
        self.assertEqual(wc.cloud_amount_to_pct("OVC"), 100.0)

    def test_case_and_unknown(self):
        self.assertEqual(wc.cloud_amount_to_pct("ovc"), 100.0)
        self.assertIsNone(wc.cloud_amount_to_pct("XYZ"))
        self.assertIsNone(wc.cloud_amount_to_pct(None))


class TestSummarize(unittest.TestCase):
    def _obs(self, c, h, layers, desc):
        return {
            "temperature": {"value": c},
            "relativeHumidity": {"value": h},
            "cloudLayers": layers,
            "textDescription": desc,
        }

    def test_basic_aggregation(self):
        obs = [
            self._obs(20.0, 50.0, [{"amount": "FEW"}], "Mostly Clear"),
            self._obs(25.0, 60.0, [{"amount": "OVC"}], "Cloudy"),
            self._obs(10.0, 70.0, [], "Clear"),
        ]
        s = wc.summarize(obs)
        self.assertAlmostEqual(s.high_f, wc.c_to_f(25.0))
        self.assertAlmostEqual(s.low_f, wc.c_to_f(10.0))
        self.assertAlmostEqual(s.humidity_pct, 60.0)
        self.assertAlmostEqual(s.cloud_pct, (19.0 + 100.0 + 0.0) / 3.0)
        self.assertEqual(s.sample_count, 3)

    def test_most_common_conditions(self):
        obs = [
            self._obs(1.0, 1.0, [], "Rain"),
            self._obs(1.0, 1.0, [], "Rain"),
            self._obs(1.0, 1.0, [], "Clear"),
        ]
        self.assertEqual(wc.summarize(obs).conditions, "Rain")

    def test_nulls_skipped(self):
        obs = [
            {"temperature": {"value": None}, "relativeHumidity": {"value": None},
             "cloudLayers": None, "textDescription": None},
        ]
        s = wc.summarize(obs)
        self.assertIsNone(s.high_f)
        self.assertIsNone(s.humidity_pct)
        self.assertIsNone(s.cloud_pct)
        self.assertIsNone(s.conditions)
        self.assertEqual(s.sample_count, 1)


class TestLocalDayBounds(unittest.TestCase):
    def test_winter_central(self):
        start, end = wc.local_day_bounds("America/Chicago", _date(2026, 1, 15))
        self.assertEqual(start, "2026-01-15T06:00:00Z")
        self.assertEqual(end, "2026-01-16T06:00:00Z")

    def test_summer_eastern(self):
        start, end = wc.local_day_bounds("America/New_York", _date(2026, 7, 15))
        self.assertEqual(start, "2026-07-15T04:00:00Z")
        self.assertEqual(end, "2026-07-16T04:00:00Z")


class TestTemplatedSummary(unittest.TestCase):
    def test_mentions_diffs_and_winner(self):
        la = wc.Location("Des Moines", "KDSM", "America/Chicago")
        lb = wc.Location("Providence", "KPVD", "America/New_York")
        a = wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Partly Cloudy", 24)
        b = wc.DailySummary(71.0, 55.0, 68.0, 75.0, "Overcast", 24)
        fav = wc.decide_favorability(a, b, 69.0, "high")
        text = wc.templated_summary(la, lb, a, b, fav)
        self.assertIn("Des Moines", text)
        self.assertIn("7", text)
        self.assertIn("less humid", text)
        self.assertIn("Overall", text)

    def test_handles_missing_values(self):
        la = wc.Location("A", "K1", "America/Chicago")
        lb = wc.Location("B", "K2", "America/New_York")
        a = wc.DailySummary(None, None, None, None, None, 0)
        b = wc.DailySummary(None, None, None, None, None, 0)
        fav = wc.decide_favorability(a, b, 60.0, "high")
        text = wc.templated_summary(la, lb, a, b, fav)
        self.assertIsInstance(text, str)
        self.assertTrue(len(text) > 0)


class TestFavorability(unittest.TestCase):
    def _s(self, high, low, hum, cloud):
        return wc.DailySummary(high, low, hum, cloud, "x", 10)

    def test_temp_closer_to_target_wins(self):
        a = self._s(70.0, 50.0, 50.0, 50.0)
        b = self._s(80.0, 60.0, 50.0, 50.0)
        fav = wc.decide_favorability(a, b, 68.0, "high")
        self.assertEqual(fav.temp, "A")

    def test_lower_humidity_and_cloud_win(self):
        a = self._s(70.0, 50.0, 40.0, 30.0)
        b = self._s(70.0, 50.0, 60.0, 80.0)
        fav = wc.decide_favorability(a, b, 70.0, "high")
        self.assertEqual(fav.humidity, "A")
        self.assertEqual(fav.cloud, "A")

    def test_overall_majority_and_target_stored(self):
        a = self._s(69.0, 50.0, 40.0, 90.0)
        b = self._s(40.0, 30.0, 80.0, 10.0)
        fav = wc.decide_favorability(a, b, 70.0, "high")
        self.assertEqual(fav.overall, "A")
        self.assertEqual(fav.target_f, 70.0)

    def test_average_basis(self):
        a = self._s(60.0, 40.0, 50.0, 50.0)
        b = self._s(70.0, 66.0, 50.0, 50.0)
        fav = wc.decide_favorability(a, b, 60.0, "average")
        self.assertEqual(fav.temp, "B")

    def test_ties(self):
        a = self._s(70.0, 50.0, 50.0, 50.0)
        b = self._s(70.0, 50.0, 50.0, 50.0)
        fav = wc.decide_favorability(a, b, 60.0, "high")
        self.assertEqual(fav.temp, "tie")
        self.assertEqual(fav.humidity, "tie")
        self.assertEqual(fav.cloud, "tie")
        self.assertEqual(fav.overall, "tie")

    def test_missing_value_favors_other(self):
        a = self._s(None, None, None, None)
        b = self._s(70.0, 50.0, 50.0, 50.0)
        fav = wc.decide_favorability(a, b, 60.0, "high")
        self.assertEqual(fav.temp, "B")
        self.assertEqual(fav.humidity, "B")
        self.assertEqual(fav.cloud, "B")
        self.assertEqual(fav.overall, "B")


if __name__ == "__main__":
    unittest.main()
