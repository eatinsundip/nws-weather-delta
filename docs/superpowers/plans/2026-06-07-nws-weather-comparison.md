# NWS Weather Comparison Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stdlib-only Python script that posts a daily Discord recap comparing yesterday's observed weather (temp/humidity/cloud) for two NWS stations, with color-coded deltas, an optional Claude-generated summary, and a CSV-backed year-to-date scoreboard.

**Architecture:** A single deployable script `weather_compare.py` with small, pure, independently testable functions behind injectable transports (`get_json`/`post_json`/clock), plus a thin `main()` that wires them to real env/HTTP. Network calls are isolated so all logic is unit-tested with canned fixtures and zero live network. Run one-shot daily by the Unraid User Scripts plugin.

**Tech Stack:** Python 3.9+ standard library only (`urllib`, `json`, `csv`, `datetime`, `zoneinfo`, `math`, `statistics`, `dataclasses`, `unittest`). No pip packages. NWS API (`api.weather.gov`), Discord webhook, Anthropic Messages API.

---

## Conventions

- **Working directory:** `/home/collin/weather-compare` (already a git repo on branch `main`).
- **Run all tests:** `python3 -m unittest discover -v` (from the project root).
- **Run one test:** `python3 -m unittest test_weather_compare.ClassName.test_name -v`
- City **A** = Des Moines (default), City **B** = Providence (default). Winners are encoded as the strings `"A"`, `"B"`, or `"tie"` everywhere.

## Data model (defined in Task 1, referenced throughout)

```python
@dataclass
class Location:
    name: str
    station: str
    tz: str

@dataclass
class DailySummary:
    high_f: Optional[float]
    low_f: Optional[float]
    humidity_pct: Optional[float]
    cloud_pct: Optional[float]
    conditions: Optional[str]
    sample_count: int

@dataclass
class Favorability:
    temp: str        # "A" | "B" | "tie"
    humidity: str
    cloud: str
    overall: str
    target_f: float

@dataclass
class Scoreboard:
    a_wins: int
    b_wins: int
    ties: int
    a_temp: int
    b_temp: int
    a_humidity: int
    b_humidity: int
    a_cloud: int
    b_cloud: int

@dataclass
class Config:
    webhook_url: str
    loc_a: Location
    loc_b: Location
    user_agent: str
    temp_basis: str          # "high" | "average"
    target_min: float
    target_max: float
    trough_doy: int
    ai_enabled: bool
    anthropic_api_key: Optional[str]
    ai_model: str
    data_dir: str
    recap_date: Optional[str]  # "YYYY-MM-DD" or None
```

---

### Task 1: Project scaffold, data model, .gitignore

**Files:**
- Create: `weather_compare.py`
- Create: `test_weather_compare.py`
- Create: `.gitignore`

- [ ] **Step 1: Write the failing test**

Create `test_weather_compare.py`:

```python
import unittest
import weather_compare as wc


class TestScaffold(unittest.TestCase):
    def test_dataclasses_importable(self):
        loc = wc.Location("Des Moines", "KDSM", "America/Chicago")
        self.assertEqual(loc.station, "KDSM")
        s = wc.DailySummary(70.0, 50.0, 55.0, 40.0, "Clear", 24)
        self.assertEqual(s.sample_count, 24)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestScaffold.test_dataclasses_importable -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'weather_compare'`

- [ ] **Step 3: Write minimal implementation**

Create `weather_compare.py`:

```python
#!/usr/bin/env python3
"""Daily Discord weather comparison between two NWS stations (stdlib-only)."""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import time as _time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from statistics import mean
from typing import Callable, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("weather_compare")


@dataclass
class Location:
    name: str
    station: str
    tz: str


@dataclass
class DailySummary:
    high_f: Optional[float]
    low_f: Optional[float]
    humidity_pct: Optional[float]
    cloud_pct: Optional[float]
    conditions: Optional[str]
    sample_count: int


@dataclass
class Favorability:
    temp: str
    humidity: str
    cloud: str
    overall: str
    target_f: float


@dataclass
class Scoreboard:
    a_wins: int
    b_wins: int
    ties: int
    a_temp: int
    b_temp: int
    a_humidity: int
    b_humidity: int
    a_cloud: int
    b_cloud: int


@dataclass
class Config:
    webhook_url: str
    loc_a: Location
    loc_b: Location
    user_agent: str
    temp_basis: str
    target_min: float
    target_max: float
    trough_doy: int
    ai_enabled: bool
    anthropic_api_key: Optional[str]
    ai_model: str
    data_dir: str
    recap_date: Optional[str]
```

Create `.gitignore`:

```
__pycache__/
*.pyc
data/
.env
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestScaffold.test_dataclasses_importable -v`
Expected: PASS (OK)

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py .gitignore
git commit -m "feat: scaffold module, data model, gitignore"
```

---

### Task 2: Celsius→Fahrenheit conversion

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test** (add to `test_weather_compare.py`)

```python
class TestConvert(unittest.TestCase):
    def test_c_to_f(self):
        self.assertAlmostEqual(wc.c_to_f(0), 32.0)
        self.assertAlmostEqual(wc.c_to_f(100), 212.0)
        self.assertAlmostEqual(wc.c_to_f(-40), -40.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestConvert -v`
Expected: FAIL — `AttributeError: module 'weather_compare' has no attribute 'c_to_f'`

- [ ] **Step 3: Write minimal implementation** (add to `weather_compare.py`)

```python
def c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestConvert -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add celsius-to-fahrenheit conversion"
```

---

### Task 3: Seasonal comfort target curve

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test**

```python
class TestSeasonalTarget(unittest.TestCase):
    def test_trough_equals_min(self):
        # day-of-year == trough_doy -> coldest target
        self.assertAlmostEqual(wc.seasonal_target(20, 30.0, 75.0, 20), 30.0, places=6)

    def test_peak_near_max(self):
        # half a year after trough -> warmest target
        self.assertAlmostEqual(wc.seasonal_target(203, 30.0, 75.0, 20), 75.0, places=1)

    def test_june_value(self):
        # June 7 (day 158) lands near ~69F with defaults
        self.assertAlmostEqual(wc.seasonal_target(158, 30.0, 75.0, 20), 68.8, delta=0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestSeasonalTarget -v`
Expected: FAIL — `AttributeError: ... has no attribute 'seasonal_target'`

- [ ] **Step 3: Write minimal implementation**

```python
def seasonal_target(day_of_year: int, target_min: float = 30.0,
                    target_max: float = 75.0, trough_doy: int = 20) -> float:
    mid = (target_min + target_max) / 2.0
    amp = (target_max - target_min) / 2.0
    return mid - amp * math.cos(2.0 * math.pi * (day_of_year - trough_doy) / 365.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestSeasonalTarget -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add seasonal comfort target curve"
```

---

### Task 4: Cloud-layer code → percent mapping

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestCloudPct -v`
Expected: FAIL — no attribute `cloud_amount_to_pct`

- [ ] **Step 3: Write minimal implementation**

```python
CLOUD_PCT = {"SKC": 0.0, "CLR": 0.0, "FEW": 19.0, "SCT": 44.0, "BKN": 75.0, "OVC": 100.0}


def cloud_amount_to_pct(code: Optional[str]) -> Optional[float]:
    if code is None:
        return None
    return CLOUD_PCT.get(str(code).strip().upper())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestCloudPct -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add cloud-layer code to percent mapping"
```

---

### Task 5: Summarize a day of observations

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

Input is a list of NWS observation `properties` dicts. Relevant keys per observation:
`temperature: {"value": float|None}`, `relativeHumidity: {"value": float|None}`,
`cloudLayers: [{"amount": "OVC"}, ...]` (may be `[]` for clear or missing/`None`),
`textDescription: str`.

- [ ] **Step 1: Write the failing test**

```python
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
        # cloud per obs: FEW=19, OVC=100, []=0 -> mean = 39.666...
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestSummarize -v`
Expected: FAIL — no attribute `summarize`

- [ ] **Step 3: Write minimal implementation**

```python
def summarize(observations: list) -> DailySummary:
    temps_c, hums, clouds, conditions = [], [], [], []
    for obs in observations:
        t = (obs.get("temperature") or {}).get("value")
        if t is not None:
            temps_c.append(t)
        h = (obs.get("relativeHumidity") or {}).get("value")
        if h is not None:
            hums.append(h)
        layers = obs.get("cloudLayers")
        if layers is not None:
            pcts = [cloud_amount_to_pct(l.get("amount")) for l in layers]
            pcts = [p for p in pcts if p is not None]
            clouds.append(max(pcts) if pcts else 0.0)
        desc = obs.get("textDescription")
        if desc:
            conditions.append(desc)
    return DailySummary(
        high_f=c_to_f(max(temps_c)) if temps_c else None,
        low_f=c_to_f(min(temps_c)) if temps_c else None,
        humidity_pct=mean(hums) if hums else None,
        cloud_pct=mean(clouds) if clouds else None,
        conditions=Counter(conditions).most_common(1)[0][0] if conditions else None,
        sample_count=len(observations),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestSummarize -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: summarize a day of observations into daily stats"
```

---

### Task 6: Local-day → UTC window (DST-aware)

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

Returns the `[00:00, next 00:00)` window of a local calendar date as UTC ISO8601 `...Z` strings for the NWS query.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date as _date


class TestLocalDayBounds(unittest.TestCase):
    def test_winter_central(self):
        # America/Chicago in January is CST (UTC-6)
        start, end = wc.local_day_bounds("America/Chicago", _date(2026, 1, 15))
        self.assertEqual(start, "2026-01-15T06:00:00Z")
        self.assertEqual(end, "2026-01-16T06:00:00Z")

    def test_summer_eastern(self):
        # America/New_York in July is EDT (UTC-4)
        start, end = wc.local_day_bounds("America/New_York", _date(2026, 7, 15))
        self.assertEqual(start, "2026-07-15T04:00:00Z")
        self.assertEqual(end, "2026-07-16T04:00:00Z")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestLocalDayBounds -v`
Expected: FAIL — no attribute `local_day_bounds`

- [ ] **Step 3: Write minimal implementation**

```python
def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_day_bounds(tz_name: str, day: date) -> tuple:
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(day, time(0, 0), tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz)
    return _iso_z(start_local), _iso_z(end_local)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestLocalDayBounds -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add DST-aware local-day to UTC window"
```

---

### Task 7: Favorability decision (per-stat + overall)

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test**

```python
class TestFavorability(unittest.TestCase):
    def _s(self, high, low, hum, cloud):
        return wc.DailySummary(high, low, hum, cloud, "x", 10)

    def test_temp_closer_to_target_wins(self):
        a = self._s(70.0, 50.0, 50.0, 50.0)  # high 70, target 68 -> dist 2
        b = self._s(80.0, 60.0, 50.0, 50.0)  # high 80 -> dist 12
        fav = wc.decide_favorability(a, b, 68.0, "high")
        self.assertEqual(fav.temp, "A")

    def test_lower_humidity_and_cloud_win(self):
        a = self._s(70.0, 50.0, 40.0, 30.0)
        b = self._s(70.0, 50.0, 60.0, 80.0)
        fav = wc.decide_favorability(a, b, 70.0, "high")
        self.assertEqual(fav.humidity, "A")
        self.assertEqual(fav.cloud, "A")

    def test_overall_majority_and_target_stored(self):
        # A wins temp+humidity, B wins cloud -> overall A
        a = self._s(69.0, 50.0, 40.0, 90.0)
        b = self._s(40.0, 30.0, 80.0, 10.0)
        fav = wc.decide_favorability(a, b, 70.0, "high")
        self.assertEqual(fav.overall, "A")
        self.assertEqual(fav.target_f, 70.0)

    def test_average_basis(self):
        # A avg=(60+40)/2=50 dist10; B avg=(70+66)/2=68 dist8 -> B closer
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestFavorability -v`
Expected: FAIL — no attribute `decide_favorability`

- [ ] **Step 3: Write minimal implementation**

```python
def _basis_temp(s: DailySummary, temp_basis: str) -> Optional[float]:
    if temp_basis == "average":
        if s.high_f is None or s.low_f is None:
            return None
        return (s.high_f + s.low_f) / 2.0
    return s.high_f


def _closer(a_val, b_val, target) -> str:
    if a_val is None and b_val is None:
        return "tie"
    if a_val is None:
        return "B"
    if b_val is None:
        return "A"
    da, db = abs(a_val - target), abs(b_val - target)
    if da < db:
        return "A"
    if db < da:
        return "B"
    return "tie"


def _lower(a_val, b_val) -> str:
    if a_val is None and b_val is None:
        return "tie"
    if a_val is None:
        return "B"
    if b_val is None:
        return "A"
    if a_val < b_val:
        return "A"
    if b_val < a_val:
        return "B"
    return "tie"


def decide_favorability(a: DailySummary, b: DailySummary, target_f: float,
                        temp_basis: str = "high") -> Favorability:
    temp = _closer(_basis_temp(a, temp_basis), _basis_temp(b, temp_basis), target_f)
    humidity = _lower(a.humidity_pct, b.humidity_pct)
    cloud = _lower(a.cloud_pct, b.cloud_pct)
    a_pts = sum(1 for w in (temp, humidity, cloud) if w == "A")
    b_pts = sum(1 for w in (temp, humidity, cloud) if w == "B")
    overall = "A" if a_pts > b_pts else "B" if b_pts > a_pts else "tie"
    return Favorability(temp, humidity, cloud, overall, target_f)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestFavorability -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add per-stat and overall favorability decision"
```

---

### Task 8: Templated fallback summary

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test**

```python
class TestTemplatedSummary(unittest.TestCase):
    def test_mentions_diffs_and_winner(self):
        la = wc.Location("Des Moines", "KDSM", "America/Chicago")
        lb = wc.Location("Providence", "KPVD", "America/New_York")
        a = wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Partly Cloudy", 24)
        b = wc.DailySummary(71.0, 55.0, 68.0, 75.0, "Overcast", 24)
        fav = wc.decide_favorability(a, b, 69.0, "high")
        text = wc.templated_summary(la, lb, a, b, fav)
        self.assertIn("Des Moines", text)
        self.assertIn("7", text)        # 7F warmer
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestTemplatedSummary -v`
Expected: FAIL — no attribute `templated_summary`

- [ ] **Step 3: Write minimal implementation**

```python
def templated_summary(loc_a: Location, loc_b: Location, a: DailySummary,
                      b: DailySummary, fav: Favorability) -> str:
    parts = []
    if a.high_f is not None and b.high_f is not None and a.high_f != b.high_f:
        warmer = loc_a.name if a.high_f > b.high_f else loc_b.name
        closer = loc_a.name if fav.temp == "A" else loc_b.name if fav.temp == "B" else "neither"
        parts.append(
            f"{warmer} was {abs(a.high_f - b.high_f):.0f}°F warmer "
            f"(closer to the ~{fav.target_f:.0f}°F seasonal target: {closer})"
        )
    if a.humidity_pct is not None and b.humidity_pct is not None and a.humidity_pct != b.humidity_pct:
        drier = loc_a.name if a.humidity_pct < b.humidity_pct else loc_b.name
        parts.append(f"{drier} was {abs(a.humidity_pct - b.humidity_pct):.0f}% less humid")
    if a.cloud_pct is not None and b.cloud_pct is not None and a.cloud_pct != b.cloud_pct:
        clearer = loc_a.name if a.cloud_pct < b.cloud_pct else loc_b.name
        parts.append(f"{clearer} was clearer (by {abs(a.cloud_pct - b.cloud_pct):.0f}%)")
    if parts:
        lead = "Yesterday " + "; ".join(parts) + "."
    else:
        lead = "Yesterday's conditions were similar between the two cities."
    if fav.overall == "A":
        lead += f" Overall, {loc_a.name} had the more favorable day."
    elif fav.overall == "B":
        lead += f" Overall, {loc_b.name} had the more favorable day."
    else:
        lead += " Overall, it was a wash."
    return lead
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestTemplatedSummary -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add deterministic templated summary"
```

---

### Task 9: AI prompt + summary with fallback

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

`generate_summary` calls the Anthropic Messages API through an injected `post_json(url, headers, body) -> dict` callable; on any failure (disabled, no key, exception, empty/malformed response) it returns the templated summary instead.

> **Note for implementer:** before finalizing, invoke the `claude-api` skill to confirm the Messages API request shape, header names, and that `claude-haiku-4-5` is the correct current model alias. Adjust the body/headers if the skill indicates a change. Do NOT add prompt caching (single daily call — no benefit).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestGenerateSummary -v`
Expected: FAIL — no attribute `generate_summary` / `build_ai_prompt`

- [ ] **Step 3: Write minimal implementation**

```python
def _fmt(v: Optional[float], unit: str) -> str:
    return "n/a" if v is None else f"{v:.0f}{unit}"


def build_ai_prompt(loc_a: Location, loc_b: Location, a: DailySummary,
                    b: DailySummary, fav: Favorability) -> str:
    def line(s: DailySummary) -> str:
        return (f"high {_fmt(s.high_f, '°F')}, low {_fmt(s.low_f, '°F')}, "
                f"humidity {_fmt(s.humidity_pct, '%')}, cloud cover {_fmt(s.cloud_pct, '%')}, "
                f"conditions {s.conditions or 'n/a'}")
    return (
        "Write a brief, friendly 2-3 sentence comparison of yesterday's weather "
        "between two cities. Be concrete and highlight the biggest differences. "
        "No bullet points or headers.\n\n"
        f"Seasonal comfort target: {fav.target_f:.0f}°F "
        "(closer is better; lower humidity and less cloud are better).\n"
        f"{loc_a.name}: {line(a)}\n"
        f"{loc_b.name}: {line(b)}\n"
    )


def generate_summary(loc_a: Location, loc_b: Location, a: DailySummary,
                     b: DailySummary, fav: Favorability, config: Config,
                     post_json: Callable) -> str:
    if not (config.ai_enabled and config.anthropic_api_key):
        return templated_summary(loc_a, loc_b, a, b, fav)
    try:
        body = {
            "model": config.ai_model,
            "max_tokens": 200,
            "messages": [{"role": "user",
                          "content": build_ai_prompt(loc_a, loc_b, a, b, fav)}],
        }
        headers = {
            "x-api-key": config.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        resp = post_json("https://api.anthropic.com/v1/messages", headers, body)
        text = resp["content"][0]["text"].strip()
        if not text:
            raise ValueError("empty AI response")
        return text
    except Exception as exc:  # noqa: BLE001 - any failure must fall back
        log.warning("AI summary failed (%s); using templated fallback", exc)
        return templated_summary(loc_a, loc_b, a, b, fav)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestGenerateSummary -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add AI summary with templated fallback"
```

---

### Task 10: CSV row builder + upsert

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import tempfile
from datetime import date as _date2


class TestCsvUpsert(unittest.TestCase):
    def _fav(self, overall):
        return wc.Favorability("A", "B", "A", overall, 69.0)

    def _summary(self):
        return wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Clear", 24)

    def test_row_fields(self):
        row = wc.summary_row(_date2(2026, 6, 6), self._summary(), self._summary(), self._fav("A"))
        self.assertEqual(row["date"], "2026-06-06")
        self.assertEqual(row["overall_winner"], "A")
        self.assertEqual(set(row.keys()), set(wc.ROW_FIELDS))

    def test_upsert_replaces_same_date(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.csv")
            wc.csv_upsert(path, wc.summary_row(_date2(2026, 6, 6), self._summary(), self._summary(), self._fav("A")))
            wc.csv_upsert(path, wc.summary_row(_date2(2026, 6, 7), self._summary(), self._summary(), self._fav("B")))
            # re-run June 6 with a different winner -> replaces, not appends
            wc.csv_upsert(path, wc.summary_row(_date2(2026, 6, 6), self._summary(), self._summary(), self._fav("B")))
            import csv as _csv
            with open(path, newline="") as f:
                rows = list(_csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            by_date = {r["date"]: r for r in rows}
            self.assertEqual(by_date["2026-06-06"]["overall_winner"], "B")
            self.assertEqual(rows[0]["date"], "2026-06-06")  # sorted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestCsvUpsert -v`
Expected: FAIL — no attribute `summary_row` / `ROW_FIELDS` / `csv_upsert`

- [ ] **Step 3: Write minimal implementation**

```python
ROW_FIELDS = [
    "date", "target_f",
    "a_high", "a_low", "a_humidity", "a_cloud", "a_conditions",
    "b_high", "b_low", "b_humidity", "b_cloud", "b_conditions",
    "temp_winner", "humidity_winner", "cloud_winner", "overall_winner",
]


def _round_or_blank(v: Optional[float]) -> str:
    return "" if v is None else str(round(v, 1))


def summary_row(recap_date: date, a: DailySummary, b: DailySummary,
                fav: Favorability) -> dict:
    return {
        "date": recap_date.isoformat(),
        "target_f": str(round(fav.target_f, 1)),
        "a_high": _round_or_blank(a.high_f), "a_low": _round_or_blank(a.low_f),
        "a_humidity": _round_or_blank(a.humidity_pct), "a_cloud": _round_or_blank(a.cloud_pct),
        "a_conditions": a.conditions or "",
        "b_high": _round_or_blank(b.high_f), "b_low": _round_or_blank(b.low_f),
        "b_humidity": _round_or_blank(b.humidity_pct), "b_cloud": _round_or_blank(b.cloud_pct),
        "b_conditions": b.conditions or "",
        "temp_winner": fav.temp, "humidity_winner": fav.humidity,
        "cloud_winner": fav.cloud, "overall_winner": fav.overall,
    }


def csv_upsert(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    rows = [r for r in rows if r.get("date") != row["date"]]
    rows.append({k: str(row.get(k, "")) for k in ROW_FIELDS})
    rows.sort(key=lambda r: r["date"])
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ROW_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestCsvUpsert -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add CSV row builder and date-keyed upsert"
```

---

### Task 11: Year-to-date scoreboard from CSV

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test**

```python
class TestScoreboard(unittest.TestCase):
    def _summary(self):
        return wc.DailySummary(70.0, 50.0, 50.0, 50.0, "x", 24)

    def test_counts_by_year(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.csv")
            s = self._summary()
            wc.csv_upsert(path, wc.summary_row(_date2(2026, 1, 2), s, s, wc.Favorability("A", "A", "B", "A", 30.0)))
            wc.csv_upsert(path, wc.summary_row(_date2(2026, 1, 3), s, s, wc.Favorability("B", "B", "B", "B", 30.0)))
            wc.csv_upsert(path, wc.summary_row(_date2(2025, 12, 31), s, s, wc.Favorability("A", "A", "A", "A", 30.0)))
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestScoreboard -v`
Expected: FAIL — no attribute `read_scoreboard`

- [ ] **Step 3: Write minimal implementation**

```python
def read_scoreboard(path: str, year: int) -> Scoreboard:
    a = b = t = at = bt = ah = bh = ac = bc = 0
    if os.path.exists(path):
        prefix = f"{year}-"
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                if not r.get("date", "").startswith(prefix):
                    continue
                w = r["overall_winner"]
                a += w == "A"
                b += w == "B"
                t += w == "tie"
                at += r["temp_winner"] == "A"
                bt += r["temp_winner"] == "B"
                ah += r["humidity_winner"] == "A"
                bh += r["humidity_winner"] == "B"
                ac += r["cloud_winner"] == "A"
                bc += r["cloud_winner"] == "B"
    return Scoreboard(a, b, t, at, bt, ah, bh, ac, bc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestScoreboard -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: compute year-to-date scoreboard from CSV"
```

---

### Task 12: ANSI colored comparison table

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

Builds the table body (no ```ansi fences — those are added by the embed). Favored value cells are wrapped in green, the losing side in red, ties uncolored. High row colored by `fav.temp`; humidity row by `fav.humidity`; cloud row by `fav.cloud`; low and conditions rows uncolored.

- [ ] **Step 1: Write the failing test**

```python
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
        # temp favored B (71 closer to 69) -> the B high value is green
        self.assertIn(f"{wc.GREEN}", table)

    def test_handles_na(self):
        la = wc.Location("A", "K1", "America/Chicago")
        lb = wc.Location("B", "K2", "America/New_York")
        a = wc.DailySummary(None, None, None, None, None, 0)
        b = wc.DailySummary(None, None, None, None, None, 0)
        fav = wc.decide_favorability(a, b, 60.0, "high")
        table = wc.build_ansi_table(la, lb, a, b, fav)
        self.assertIn("n/a", table)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestAnsiTable -v`
Expected: FAIL — no attribute `build_ansi_table` / `GREEN`

- [ ] **Step 3: Write minimal implementation**

```python
GREEN = "\x1b[0;32m"
RED = "\x1b[0;31m"
RESET = "\x1b[0m"


def _colorize(text: str, this_side: str, winner: str) -> str:
    if winner == this_side:
        return f"{GREEN}{text}{RESET}"
    if winner in ("A", "B"):  # there is a winner and it's the other side
        return f"{RED}{text}{RESET}"
    return text  # tie -> no color


def _val(v: Optional[float], unit: str) -> str:
    return "n/a" if v is None else f"{v:.0f}{unit}"


def build_ansi_table(loc_a: Location, loc_b: Location, a: DailySummary,
                     b: DailySummary, fav: Favorability) -> str:
    label_w, col_w = 12, 13

    def row(label: str, a_text: str, b_text: str, delta: str,
            winner: Optional[str]) -> str:
        a_cell = a_text.rjust(col_w)
        b_cell = b_text.rjust(col_w)
        if winner is not None:
            a_cell = a_text.rjust(col_w)
            b_cell = b_text.rjust(col_w)
            a_cell = _colorize(a_cell, "A", winner)
            b_cell = _colorize(b_cell, "B", winner)
        return f"{label.ljust(label_w)}{a_cell}{b_cell}   {delta}"

    def diff(x, y, unit):
        if x is None or y is None:
            return ""
        return f"Δ {abs(x - y):.0f}{unit}"

    header = f"{''.ljust(label_w)}{loc_a.name.rjust(col_w)}{loc_b.name.rjust(col_w)}"
    lines = [
        header,
        row("High", _val(a.high_f, "°F"), _val(b.high_f, "°F"),
            diff(a.high_f, b.high_f, "°F"), fav.temp),
        row("Low", _val(a.low_f, "°F"), _val(b.low_f, "°F"),
            diff(a.low_f, b.low_f, "°F"), None),
        row("Humidity", _val(a.humidity_pct, "%"), _val(b.humidity_pct, "%"),
            diff(a.humidity_pct, b.humidity_pct, "%"), fav.humidity),
        row("Cloud", _val(a.cloud_pct, "%"), _val(b.cloud_pct, "%"),
            diff(a.cloud_pct, b.cloud_pct, "%"), fav.cloud),
        row("Conditions", (a.conditions or "n/a"), (b.conditions or "n/a"), "", None),
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestAnsiTable -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: build ANSI-colored comparison table"
```

---

### Task 13: Discord embed builder

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test**

```python
class TestEmbed(unittest.TestCase):
    def test_structure_and_color(self):
        la = wc.Location("Des Moines", "KDSM", "America/Chicago")
        lb = wc.Location("Providence", "KPVD", "America/New_York")
        a = wc.DailySummary(78.0, 60.0, 55.0, 40.0, "Partly Cloudy", 24)
        b = wc.DailySummary(71.0, 55.0, 68.0, 75.0, "Overcast", 24)
        fav = wc.Favorability("B", "A", "A", "A", 69.0)  # overall A
        sb = wc.Scoreboard(98, 112, 3, 50, 60, 70, 40, 55, 56)
        embed = wc.build_embed(la, lb, a, b, fav, "Summary text.", sb, _date2(2026, 6, 6))
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
        e_b = wc.build_embed(la, lb, s, s, wc.Favorability("B", "B", "B", "B", 60.0), "t", sb, _date2(2026, 6, 6))
        self.assertEqual(e_b["embeds"][0]["color"], wc.COLOR_B)
        e_t = wc.build_embed(la, lb, s, s, wc.Favorability("tie", "tie", "tie", "tie", 60.0), "t", sb, _date2(2026, 6, 6))
        self.assertEqual(e_t["embeds"][0]["color"], wc.COLOR_TIE)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestEmbed -v`
Expected: FAIL — no attribute `build_embed` / `COLOR_A`

- [ ] **Step 3: Write minimal implementation**

```python
COLOR_A = 0xE67E22    # orange  (city A / Des Moines wins)
COLOR_B = 0x2ECC71    # green   (city B / Providence wins)
COLOR_TIE = 0x95A5A6  # gray    (tie)


def build_embed(loc_a: Location, loc_b: Location, a: DailySummary, b: DailySummary,
                fav: Favorability, summary_text: str, sb: Scoreboard,
                recap_date: date) -> dict:
    table = build_ansi_table(loc_a, loc_b, a, b, fav)
    color = COLOR_B if fav.overall == "B" else COLOR_A if fav.overall == "A" else COLOR_TIE
    pretty = recap_date.strftime("%a, %b %-d %Y")
    score = (
        f"YTD: {loc_b.name} {sb.b_wins} – {sb.a_wins} {loc_a.name}  "
        f"(Temp {sb.b_temp}-{sb.a_temp} · Humidity {sb.b_humidity}-{sb.a_humidity} "
        f"· Cloud {sb.b_cloud}-{sb.a_cloud})"
    )
    description = f"```ansi\n{table}\n```\n{summary_text}\n\n{score}"
    return {"embeds": [{
        "title": f"\U0001F324️  Weather Comparison — {pretty}",
        "color": color,
        "description": description,
    }]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestEmbed -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: build Discord embed payload"
```

---

### Task 14: HTTP transport helpers (with retry)

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

`http_request_json` accepts injectable `urlopen` and `sleep` so retry/backoff is testable without network. Empty response bodies (e.g. Discord 204) return `None`.

- [ ] **Step 1: Write the failing test**

```python
import io
import urllib.error


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

        with self.assertRaises(urllib.error.HTTPError):
            wc.http_request_json("http://x", {}, urlopen=fake_urlopen, sleep=lambda *_: None)

    def test_empty_body_returns_none(self):
        def fake_urlopen(req, timeout=None):
            return _FakeResp("")

        out = wc.http_request_json("http://x", {}, urlopen=fake_urlopen, sleep=lambda *_: None)
        self.assertIsNone(out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestHttp -v`
Expected: FAIL — no attribute `http_request_json`

- [ ] **Step 3: Write minimal implementation**

```python
def http_request_json(url: str, headers: dict, data: Optional[dict] = None,
                      method: str = "GET", timeout: float = 15.0, retries: int = 3,
                      backoff: float = 2.0, urlopen=urllib.request.urlopen,
                      sleep=_time.sleep):
    body = json.dumps(data).encode() if data is not None else None
    last_exc = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode().strip()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise
            last_exc = exc
        except urllib.error.URLError as exc:
            last_exc = exc
        if attempt < retries - 1:
            sleep(backoff * (attempt + 1))
    raise last_exc


def http_get_json(url: str, headers: dict, **kw):
    return http_request_json(url, headers, method="GET", **kw)


def http_post_json(url: str, headers: dict, body: dict, **kw):
    return http_request_json(url, headers, data=body, method="POST", **kw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestHttp -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add HTTP JSON helpers with retry and empty-body handling"
```

---

### Task 15: fetch_observations + post_discord

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestNetworkWrappers -v`
Expected: FAIL — no attribute `fetch_observations` / `post_discord`

- [ ] **Step 3: Write minimal implementation**

```python
def fetch_observations(station: str, start_iso: str, end_iso: str,
                       user_agent: str, get_json: Callable = http_get_json) -> list:
    url = (f"https://api.weather.gov/stations/{station}/observations"
           f"?start={start_iso}&end={end_iso}")
    headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}
    data = get_json(url, headers)
    features = (data or {}).get("features", [])
    return [f["properties"] for f in features]


def post_discord(webhook_url: str, payload: dict,
                 post_json: Callable = http_post_json) -> None:
    post_json(webhook_url, {"content-type": "application/json"}, payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestNetworkWrappers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: add NWS fetch and Discord post wrappers"
```

---

### Task 16: load_config from environment

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestLoadConfig -v`
Expected: FAIL — no attribute `load_config`

- [ ] **Step 3: Write minimal implementation**

```python
def _bool(value: Optional[str], default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def load_config(env: dict) -> Config:
    webhook = env.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        raise SystemExit("DISCORD_WEBHOOK_URL is required")
    loc_a = Location(env.get("LOC_A_NAME", "Des Moines"),
                     env.get("LOC_A_STATION", "KDSM"),
                     env.get("LOC_A_TZ", "America/Chicago"))
    loc_b = Location(env.get("LOC_B_NAME", "Providence"),
                     env.get("LOC_B_STATION", "KPVD"),
                     env.get("LOC_B_TZ", "America/New_York"))
    return Config(
        webhook_url=webhook,
        loc_a=loc_a,
        loc_b=loc_b,
        user_agent=env.get("NWS_USER_AGENT", "weather-compare (claude@ccaves.net)"),
        temp_basis=env.get("TEMP_BASIS", "high"),
        target_min=float(env.get("TARGET_MIN", "30")),
        target_max=float(env.get("TARGET_MAX", "75")),
        trough_doy=int(env.get("TROUGH_DOY", "20")),
        ai_enabled=_bool(env.get("AI_ENABLED"), True),
        anthropic_api_key=env.get("ANTHROPIC_API_KEY"),
        ai_model=env.get("AI_MODEL", "claude-haiku-4-5"),
        data_dir=env.get("DATA_DIR", "./data"),
        recap_date=env.get("RECAP_DATE"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestLoadConfig -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: load configuration from environment"
```

---

### Task 17: run() orchestration + main()

**Files:**
- Modify: `weather_compare.py`
- Test: `test_weather_compare.py`

`run(config, today, get_json, post_json)` wires everything with injected transports and an injected `today` date. `main()` reads real env/HTTP and sets a non-zero exit on failure.

- [ ] **Step 1: Write the failing test**

```python
class TestRun(unittest.TestCase):
    def _collection(self):
        # one clear-ish obs and one cloudy obs
        return {"features": [
            {"properties": {"temperature": {"value": 20.0},
                            "relativeHumidity": {"value": 50.0},
                            "cloudLayers": [{"amount": "FEW"}],
                            "textDescription": "Mostly Clear"}},
            {"properties": {"temperature": {"value": 25.0},
                            "relativeHumidity": {"value": 60.0},
                            "cloudLayers": [{"amount": "OVC"}],
                            "textDescription": "Cloudy"}},
        ]}

    def test_run_posts_embed_and_writes_csv(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = wc.load_config({"DISCORD_WEBHOOK_URL": "http://hook", "DATA_DIR": d,
                                  "AI_ENABLED": "false"})
            posts = []

            def fake_get(url, headers):
                return self._collection()

            def fake_post(url, headers, body):
                posts.append((url, body))
                return None

            embed = wc.run(cfg, _date2(2026, 6, 7), get_json=fake_get, post_json=fake_post)
            # recap date is yesterday = 2026-06-06
            self.assertIn("Jun 6 2026", embed["embeds"][0]["title"])
            # discord webhook was posted exactly once
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0][0], "http://hook")
            # CSV written with the recap date row
            import csv as _csv
            with open(os.path.join(d, "history.csv"), newline="") as f:
                rows = list(_csv.DictReader(f))
            self.assertEqual(rows[0]["date"], "2026-06-06")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_weather_compare.TestRun -v`
Expected: FAIL — no attribute `run`

- [ ] **Step 3: Write minimal implementation**

```python
def run(config: Config, today: date, get_json: Callable = http_get_json,
        post_json: Callable = http_post_json) -> dict:
    if config.recap_date:
        recap = date.fromisoformat(config.recap_date)
    else:
        recap = today - timedelta(days=1)

    summaries = {}
    for key, loc in (("A", config.loc_a), ("B", config.loc_b)):
        start, end = local_day_bounds(loc.tz, recap)
        obs = fetch_observations(loc.station, start, end, config.user_agent,
                                 get_json=get_json)
        summaries[key] = summarize(obs)
    a, b = summaries["A"], summaries["B"]

    target = seasonal_target(recap.timetuple().tm_yday, config.target_min,
                             config.target_max, config.trough_doy)
    fav = decide_favorability(a, b, target, config.temp_basis)
    summary_text = generate_summary(config.loc_a, config.loc_b, a, b, fav,
                                    config, post_json)

    csv_path = os.path.join(config.data_dir, "history.csv")
    csv_upsert(csv_path, summary_row(recap, a, b, fav))
    sb = read_scoreboard(csv_path, recap.year)

    embed = build_embed(config.loc_a, config.loc_b, a, b, fav, summary_text, sb, recap)
    post_discord(config.webhook_url, embed, post_json=post_json)
    log.info("Posted weather comparison for %s (overall winner: %s)",
             recap.isoformat(), fav.overall)
    return embed


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(os.environ)
    today = datetime.now(ZoneInfo(config.loc_a.tz)).date()
    try:
        run(config, today)
    except Exception:
        log.exception("weather_compare run failed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_weather_compare.TestRun -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest discover -v`
Expected: all tests PASS (OK)

- [ ] **Step 6: Commit**

```bash
git add weather_compare.py test_weather_compare.py
git commit -m "feat: wire run() orchestration and main() entrypoint"
```

---

### Task 18: README, .env.example, and a live smoke run

**Files:**
- Create: `README.md`
- Create: `.env.example`

- [ ] **Step 1: Create `.env.example`**

```bash
# Required
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/XXXX/YYYY

# Locations (defaults shown)
LOC_A_NAME=Des Moines
LOC_A_STATION=KDSM
LOC_A_TZ=America/Chicago
LOC_B_NAME=Providence
LOC_B_STATION=KPVD
LOC_B_TZ=America/New_York

# NWS requires a User-Agent with contact info
NWS_USER_AGENT=weather-compare (claude@ccaves.net)

# Favorability
TEMP_BASIS=high          # high | average
TARGET_MIN=30            # coldest seasonal comfort target (F)
TARGET_MAX=75            # warmest seasonal comfort target (F)
TROUGH_DOY=20            # day-of-year of the coldest target

# AI summary (optional). Uses templated fallback if disabled or no key.
AI_ENABLED=true
ANTHROPIC_API_KEY=
AI_MODEL=claude-haiku-4-5

# Storage
DATA_DIR=/mnt/user/appdata/weather-compare

# Optional: recompute a specific day (YYYY-MM-DD) for backfill/testing
# RECAP_DATE=2026-06-06
```

- [ ] **Step 2: Create `README.md`**

````markdown
# NWS Weather Comparison

Posts a daily Discord recap comparing **yesterday's observed weather** for two
NWS stations (default Des Moines & Providence): high/low temp, humidity, and
cloud cover, with color-coded deltas, an optional Claude-generated summary, and
a year-to-date scoreboard.

Pure Python standard library — **no pip install**. Requires Python 3.9+.

## Configure

Set the environment variables from `.env.example`. Only `DISCORD_WEBHOOK_URL`
is required (create one in your Discord channel: *Edit Channel → Integrations →
Webhooks → New Webhook → Copy URL*).

## Run manually

```bash
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
DATA_DIR="/mnt/user/appdata/weather-compare" \
python3 weather_compare.py
```

Backfill or re-test a specific day (safe to re-run — rows are de-duplicated):

```bash
RECAP_DATE=2026-06-06 DISCORD_WEBHOOK_URL="..." python3 weather_compare.py
```

## Unraid (User Scripts plugin)

1. Ensure `python3` is available (install the **NerdTools** plugin and enable a
   recent Python). Copy `weather_compare.py` to a persistent path on the array,
   e.g. `/boot/config/plugins/user.scripts/scripts/weather-compare/`.
2. In **Settings → User Scripts**, add a new script with this body:

   ```bash
   #!/bin/bash
   export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
   export DATA_DIR="/mnt/user/appdata/weather-compare"
   export ANTHROPIC_API_KEY=""        # leave blank to use the templated summary
   export AI_ENABLED="true"
   python3 /path/to/weather_compare.py
   ```

3. Set the schedule to **Scheduled Daily** (or a custom cron a couple of hours
   after local midnight, so the full prior day of observations is available).
   Because each city's "yesterday" is computed in its own timezone, run it after
   the later city's local midnight — early morning Eastern is safe for both.

## How the comparison works

- **Temp:** the city whose high (or daily average, via `TEMP_BASIS=average`) is
  closest to a seasonal comfort target wins. The target follows a yearly curve
  between `TARGET_MIN` (≈ late Jan) and `TARGET_MAX` (≈ late Jul).
- **Humidity / Cloud:** lower wins.
- **Overall winner:** whoever wins ≥2 of the 3 stats. Each day's result is
  appended to `DATA_DIR/history.csv` and tallied into the year-to-date scoreboard
  shown in the post.

## Tests

```bash
python3 -m unittest discover -v
```
````

- [ ] **Step 3: Run the full test suite once more**

Run: `python3 -m unittest discover -v`
Expected: all PASS.

- [ ] **Step 4: Live smoke run (manual, optional but recommended)**

With a real `DISCORD_WEBHOOK_URL` exported (and optionally `ANTHROPIC_API_KEY`),
run against yesterday and confirm a real embed posts to the channel:

Run: `DATA_DIR=./data DISCORD_WEBHOOK_URL="<real>" python3 weather_compare.py`
Expected: a colored comparison embed appears in Discord; `./data/history.csv`
contains one row for yesterday. Verify the ANSI colors render (Discord desktop/
mobile) and the numbers look sane against weather.gov.

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example
git commit -m "docs: add README and .env.example"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Yesterday's observed recap, per-city local day → Tasks 6, 17 ✓
- Aggregate from station observations → Tasks 5, 15 ✓
- Stats: high/low temp, humidity, cloud cover, conditions → Task 5 ✓
- Cloud "overcast" mapping → Task 4 ✓
- Imperial units (°F) → Task 2 + display formatting (Tasks 8, 12) ✓
- Seasonal comfort target curve (30/75, configurable) → Task 3 ✓
- Favorability: temp-to-target, lower humidity, lower cloud, overall ≥2/3 → Task 7 ✓
- Color coding: ANSI table + embed side-bar color → Tasks 12, 13 ✓
- AI report toggleable + templated fallback → Tasks 8, 9 ✓
- Discord webhook + rich embed → Tasks 13, 15 ✓
- CSV persistence, upsert/de-dup, YTD scoreboard → Tasks 10, 11 ✓
- Config via env vars (full list) → Task 16 ✓
- One-shot run / User Scripts deployment → Tasks 17, 18 ✓
- Stdlib-only, single deployable script → all tasks ✓
- Testing without live network → injected transports throughout ✓

**Placeholder scan:** none — every step contains runnable code/commands.

**Type consistency:** winner strings `"A"|"B"|"tie"` used uniformly; `DailySummary`,
`Favorability`, `Scoreboard`, `Config`, `Location` field names match across Tasks
1–17; `get_json(url, headers)` and `post_json(url, headers, body)` signatures
consistent between Tasks 9, 14, 15, 17; `ROW_FIELDS` keys match `summary_row`,
`csv_upsert`, and `read_scoreboard`.

**Note for implementer:** Task 9 — verify Anthropic Messages API request shape and
the `claude-haiku-4-5` model id via the `claude-api` skill before finalizing.
