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


if __name__ == "__main__":
    unittest.main()
