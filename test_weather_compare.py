import unittest
import weather_compare as wc


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


if __name__ == "__main__":
    unittest.main()
