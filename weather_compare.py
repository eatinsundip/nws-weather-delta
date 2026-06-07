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
