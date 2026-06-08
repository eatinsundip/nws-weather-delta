import os
import tempfile
import unittest
import urllib.error
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


class TestGenerateSummary(unittest.TestCase):
    def _cfg(self, ai_enabled=True, key="sk-test"):
        la = wc.Location("Des Moines", "KDSM", "America/Chicago")
        lb = wc.Location("Providence", "KPVD", "America/New_York")
        return wc.Config(
            webhook_url="http://hook", loc_a=la, loc_b=lb,
            user_agent="ua", temp_basis="high", target_min=30.0, target_max=75.0,
            trough_doy=20, ai_enabled=ai_enabled, anthropic_api_key=key,
            ai_model="claude-haiku-4-5", data_dir="/tmp", recap_date=None,
        )

    def _summaries(self):
        a = wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Partly Cloudy", 24)
        b = wc.DailySummary(71.0, 55.0, 68.0, 75.0, "Overcast", 24)
        return a, b

    def test_ai_success(self):
        a, b = self._summaries()
        fav = wc.decide_favorability(a, b, 69.0, "high")
        captured = {}

        def fake_post(url, headers, body):
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = body
            return {"content": [{"text": "Iowa was warmer and drier than Rhode Island."}]}

        cfg = self._cfg()
        text = wc.generate_summary(cfg.loc_a, cfg.loc_b, a, b, fav, cfg, fake_post)
        self.assertEqual(text, "Iowa was warmer and drier than Rhode Island.")
        self.assertEqual(captured["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(captured["headers"]["x-api-key"], "sk-test")
        self.assertEqual(captured["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(captured["body"]["model"], "claude-haiku-4-5")

    def test_disabled_uses_templated_without_calling(self):
        a, b = self._summaries()
        fav = wc.decide_favorability(a, b, 69.0, "high")
        cfg = self._cfg(ai_enabled=False)

        def fake_post(url, headers, body):
            raise AssertionError("post_json should not be called when AI disabled")

        text = wc.generate_summary(cfg.loc_a, cfg.loc_b, a, b, fav, cfg, fake_post)
        self.assertEqual(text, wc.templated_summary(cfg.loc_a, cfg.loc_b, a, b, fav))

    def test_api_error_falls_back(self):
        a, b = self._summaries()
        fav = wc.decide_favorability(a, b, 69.0, "high")
        cfg = self._cfg()

        def fake_post(url, headers, body):
            raise RuntimeError("boom")

        text = wc.generate_summary(cfg.loc_a, cfg.loc_b, a, b, fav, cfg, fake_post)
        self.assertEqual(text, wc.templated_summary(cfg.loc_a, cfg.loc_b, a, b, fav))


class TestTemplatedSummary(unittest.TestCase):
    def test_mentions_diffs_and_winner(self):
        la = wc.Location("Des Moines", "KDSM", "America/Chicago")
        lb = wc.Location("Providence", "KPVD", "America/New_York")
        a = wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Partly Cloudy", 24)
        b = wc.DailySummary(71.0, 55.0, 68.0, 75.0, "Overcast", 24)
        fav = wc.decide_favorability(a, b, 69.0, "high")
        text = wc.templated_summary(la, lb, a, b, fav)
        self.assertIn("Des Moines", text)
        self.assertIn("7°F", text)
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


class TestCsvUpsert(unittest.TestCase):
    def _fav(self, overall):
        return wc.Favorability("A", "B", "A", overall, 69.0)

    def _summary(self):
        return wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Clear", 24)

    def test_row_fields(self):
        row = wc.summary_row(_date(2026, 6, 6), self._summary(), self._summary(), self._fav("A"))
        self.assertEqual(row["date"], "2026-06-06")
        self.assertEqual(row["overall_winner"], "A")
        self.assertEqual(set(row.keys()), set(wc.ROW_FIELDS))

    def test_upsert_replaces_same_date(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.csv")
            wc.csv_upsert(path, wc.summary_row(_date(2026, 6, 6), self._summary(), self._summary(), self._fav("A")))
            wc.csv_upsert(path, wc.summary_row(_date(2026, 6, 7), self._summary(), self._summary(), self._fav("B")))
            wc.csv_upsert(path, wc.summary_row(_date(2026, 6, 6), self._summary(), self._summary(), self._fav("B")))
            import csv as _csv
            with open(path, newline="") as f:
                rows = list(_csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            by_date = {r["date"]: r for r in rows}
            self.assertEqual(by_date["2026-06-06"]["overall_winner"], "B")
            self.assertEqual(rows[0]["date"], "2026-06-06")


class TestScoreboard(unittest.TestCase):
    def _summary(self):
        return wc.DailySummary(70.0, 50.0, 50.0, 50.0, "x", 24)

    def test_counts_by_year(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.csv")
            s = self._summary()
            wc.csv_upsert(path, wc.summary_row(_date(2026, 1, 2), s, s, wc.Favorability("A", "A", "B", "A", 30.0)))
            wc.csv_upsert(path, wc.summary_row(_date(2026, 1, 3), s, s, wc.Favorability("B", "B", "B", "B", 30.0)))
            wc.csv_upsert(path, wc.summary_row(_date(2025, 12, 31), s, s, wc.Favorability("A", "A", "A", "A", 30.0)))
            sb = wc.read_scoreboard(path, 2026)
            self.assertEqual(sb.a_wins, 1)
            self.assertEqual(sb.b_wins, 1)
            self.assertEqual(sb.a_temp, 1)
            self.assertEqual(sb.b_temp, 1)
            self.assertEqual(sb.a_humidity, 1)
            self.assertEqual(sb.b_humidity, 1)
            self.assertEqual(sb.b_cloud, 2)
            self.assertEqual(sb.a_cloud, 0)

    def test_missing_file_returns_zeros(self):
        sb = wc.read_scoreboard("/tmp/does-not-exist-xyz.csv", 2026)
        self.assertEqual(sb.a_wins, 0)
        self.assertEqual(sb.b_wins, 0)


class TestAnsiTable(unittest.TestCase):
    def test_colors_favored_cells(self):
        la = wc.Location("Des Moines", "KDSM", "America/Chicago")
        lb = wc.Location("Providence", "KPVD", "America/New_York")
        a = wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Partly Cloudy", 24)
        b = wc.DailySummary(71.0, 55.0, 68.0, 75.0, "Overcast", 24)
        fav = wc.decide_favorability(a, b, 69.0, "high")  # temp B, humidity A, cloud A
        table = wc.build_ansi_table(la, lb, a, b, fav)
        self.assertIn(wc.GREEN, table)
        self.assertIn(wc.RED, table)
        self.assertIn(wc.RESET, table)
        self.assertIn("78", table)
        self.assertIn("71", table)
        self.assertIn("Des Moines", table)
        self.assertIn("Providence", table)

    def test_favored_cell_green_loser_red(self):
        # Pin which cell gets which color (guards against A/B transposition).
        la = wc.Location("Des Moines", "KDSM", "America/Chicago")
        lb = wc.Location("Providence", "KPVD", "America/New_York")
        a = wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Partly Cloudy", 24)
        b = wc.DailySummary(71.0, 55.0, 68.0, 75.0, "Overcast", 24)
        fav = wc.decide_favorability(a, b, 69.0, "high")  # 71 is closer to 69 -> temp favors B
        self.assertEqual(fav.temp, "B")
        high_row = wc.build_ansi_table(la, lb, a, b, fav).split("\n")[1]
        # A (Des Moines, lost temp) is red and appears before B (Providence, won temp) in green
        self.assertLess(high_row.index(wc.RED), high_row.index(wc.GREEN))
        red_seg = high_row[high_row.index(wc.RED):high_row.index(wc.GREEN)]
        green_seg = high_row[high_row.index(wc.GREEN):]
        self.assertIn("78", red_seg)
        self.assertIn("71", green_seg)

    def test_long_conditions_truncated_to_column(self):
        # Long NWS condition strings must not overflow the 13-char column.
        la = wc.Location("Des Moines", "KDSM", "America/Chicago")
        lb = wc.Location("Providence", "KPVD", "America/New_York")
        a = wc.DailySummary(70.0, 50.0, 50.0, 50.0, "Chance Showers And Thunderstorms", 24)
        b = wc.DailySummary(70.0, 50.0, 50.0, 50.0, "Clear", 24)
        cond_row = wc.build_ansi_table(la, lb, a, b, fav=wc.decide_favorability(a, b, 60.0, "high")).split("\n")[-1]
        self.assertNotIn("Thunderstorms", cond_row)

    def test_handles_na(self):
        la = wc.Location("A", "K1", "America/Chicago")
        lb = wc.Location("B", "K2", "America/New_York")
        a = wc.DailySummary(None, None, None, None, None, 0)
        b = wc.DailySummary(None, None, None, None, None, 0)
        fav = wc.decide_favorability(a, b, 60.0, "high")
        table = wc.build_ansi_table(la, lb, a, b, fav)
        self.assertIn("n/a", table)


class TestEmbed(unittest.TestCase):
    def test_structure_and_color(self):
        la = wc.Location("Des Moines", "KDSM", "America/Chicago")
        lb = wc.Location("Providence", "KPVD", "America/New_York")
        a = wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Partly Cloudy", 24)
        b = wc.DailySummary(71.0, 55.0, 68.0, 75.0, "Overcast", 24)
        fav = wc.Favorability("B", "A", "A", "A", 69.0)  # overall A
        sb = wc.Scoreboard(98, 112, 3, 50, 60, 70, 40, 55, 56)
        embed = wc.build_embed(la, lb, a, b, fav, "Summary text.", sb, _date(2026, 6, 6))
        e = embed["embeds"][0]
        self.assertEqual(e["color"], wc.COLOR_A)  # overall A -> orange
        self.assertIn("Weather Comparison", e["title"])
        self.assertIn("2026", e["title"])
        self.assertIn("```ansi", e["description"])
        self.assertIn("Summary text.", e["description"])
        self.assertIn("YTD", e["description"])
        self.assertIn("Providence 112", e["description"])

    def test_color_b_and_tie(self):
        la = wc.Location("A", "K1", "America/Chicago")
        lb = wc.Location("B", "K2", "America/New_York")
        s = wc.DailySummary(70.0, 50.0, 50.0, 50.0, "x", 1)
        sb = wc.Scoreboard(0, 0, 0, 0, 0, 0, 0, 0, 0)
        e_b = wc.build_embed(la, lb, s, s, wc.Favorability("B", "B", "B", "B", 60.0), "t", sb, _date(2026, 6, 6))
        self.assertEqual(e_b["embeds"][0]["color"], wc.COLOR_B)
        e_t = wc.build_embed(la, lb, s, s, wc.Favorability("tie", "tie", "tie", "tie", 60.0), "t", sb, _date(2026, 6, 6))
        self.assertEqual(e_t["embeds"][0]["color"], wc.COLOR_TIE)


class _FakeResp:
    def __init__(self, body):
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestHttp(unittest.TestCase):
    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("temporary")
            return _FakeResp('{"ok": true}')

        out = wc.http_request_json(
            "http://x", {"User-Agent": "ua"}, urlopen=fake_urlopen, sleep=lambda *_: None
        )
        self.assertEqual(out, {"ok": True})
        self.assertEqual(calls["n"], 3)

    def test_client_error_no_retry(self):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError("http://x", 404, "nf", {}, None)

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            wc.http_request_json("http://x", {}, urlopen=fake_urlopen, sleep=lambda *_: None)
        ctx.exception.close()  # HTTPError holds a temp-file handle; close to avoid ResourceWarning

    def test_empty_body_returns_none(self):
        def fake_urlopen(req, timeout=None):
            return _FakeResp("")

        out = wc.http_request_json("http://x", {}, urlopen=fake_urlopen, sleep=lambda *_: None)
        self.assertIsNone(out)

    def test_invalid_retries_raises(self):
        with self.assertRaises(ValueError):
            wc.http_request_json("http://x", {}, retries=0)


class TestNetworkWrappers(unittest.TestCase):
    def test_fetch_observations_parses_features(self):
        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return {"features": [
                {"properties": {"temperature": {"value": 20.0}}},
                {"properties": {"temperature": {"value": 21.0}}},
            ]}

        props = wc.fetch_observations("KDSM", "2026-06-06T05:00:00Z",
                                      "2026-06-07T05:00:00Z", "ua", get_json=fake_get)
        self.assertEqual(len(props), 2)
        self.assertEqual(props[0]["temperature"]["value"], 20.0)
        self.assertIn("/stations/KDSM/observations", captured["url"])
        self.assertIn("start=2026-06-06T05:00:00Z", captured["url"])
        self.assertEqual(captured["headers"]["User-Agent"], "ua")

    def test_post_discord_calls_transport(self):
        captured = {}

        def fake_post(url, headers, body):
            captured["url"] = url
            captured["body"] = body
            return None

        wc.post_discord("http://hook", {"embeds": []}, post_json=fake_post)
        self.assertEqual(captured["url"], "http://hook")
        self.assertEqual(captured["body"], {"embeds": []})


class TestLoadConfig(unittest.TestCase):
    def test_requires_webhook(self):
        with self.assertRaises(SystemExit):
            wc.load_config({})

    def test_defaults(self):
        cfg = wc.load_config({"DISCORD_WEBHOOK_URL": "http://hook"})
        self.assertEqual(cfg.webhook_url, "http://hook")
        self.assertEqual(cfg.loc_a.name, "Des Moines")
        self.assertEqual(cfg.loc_a.station, "KDSM")
        self.assertEqual(cfg.loc_a.tz, "America/Chicago")
        self.assertEqual(cfg.loc_b.station, "KPVD")
        self.assertEqual(cfg.temp_basis, "high")
        self.assertEqual(cfg.target_min, 30.0)
        self.assertEqual(cfg.target_max, 75.0)
        self.assertTrue(cfg.ai_enabled)
        self.assertIsNone(cfg.anthropic_api_key)
        self.assertEqual(cfg.ai_model, "claude-haiku-4-5")
        self.assertEqual(cfg.data_dir, "./data")

    def test_overrides_and_bool_parsing(self):
        cfg = wc.load_config({
            "DISCORD_WEBHOOK_URL": "http://hook",
            "LOC_A_NAME": "Austin", "LOC_A_STATION": "KAUS", "LOC_A_TZ": "America/Chicago",
            "AI_ENABLED": "false", "TARGET_MIN": "25", "TROUGH_DOY": "15",
            "ANTHROPIC_API_KEY": "sk-x", "RECAP_DATE": "2026-06-06",
        })
        self.assertEqual(cfg.loc_a.name, "Austin")
        self.assertFalse(cfg.ai_enabled)
        self.assertEqual(cfg.target_min, 25.0)
        self.assertEqual(cfg.trough_doy, 15)
        self.assertEqual(cfg.recap_date, "2026-06-06")


if __name__ == "__main__":
    unittest.main()
