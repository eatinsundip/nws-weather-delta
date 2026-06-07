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


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_day_bounds(tz_name: str, day: date) -> tuple:
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(day, time(0, 0), tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz)
    return _iso_z(start_local), _iso_z(end_local)


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
