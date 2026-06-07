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


def c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def seasonal_target(day_of_year: int, target_min: float = 30.0,
                    target_max: float = 75.0, trough_doy: int = 20) -> float:
    mid = (target_min + target_max) / 2.0
    amp = (target_max - target_min) / 2.0
    return mid - amp * math.cos(2.0 * math.pi * (day_of_year - trough_doy) / 365.0)


CLOUD_PCT = {"SKC": 0.0, "CLR": 0.0, "FEW": 19.0, "SCT": 44.0, "BKN": 75.0, "OVC": 100.0}


def cloud_amount_to_pct(code: Optional[str]) -> Optional[float]:
    if code is None:
        return None
    return CLOUD_PCT.get(str(code).strip().upper())


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
            pcts = [cloud_amount_to_pct(layer.get("amount")) for layer in layers]
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


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_day_bounds(tz_name: str, day: date) -> tuple[str, str]:
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(day, time(0, 0), tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz)
    return _iso_z(start_local), _iso_z(end_local)


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
