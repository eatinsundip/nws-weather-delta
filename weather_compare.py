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


GREEN = "\x1b[0;32m"
RED = "\x1b[0;31m"
RESET = "\x1b[0m"


def _colorize(text: str, this_side: str, winner: str) -> str:
    if winner == this_side:
        return f"{GREEN}{text}{RESET}"
    if winner in ("A", "B"):  # there is a winner and it's the other side
        return f"{RED}{text}{RESET}"
    return text  # tie or None -> no color


def _val(v: Optional[float], unit: str) -> str:
    return "n/a" if v is None else f"{v:.0f}{unit}"


def build_ansi_table(loc_a: Location, loc_b: Location, a: DailySummary,
                     b: DailySummary, fav: Favorability) -> str:
    label_w, col_w = 12, 13

    def row(label: str, a_text: str, b_text: str, delta: str,
            winner: Optional[str]) -> str:
        a_cell = _colorize(a_text[:col_w].rjust(col_w), "A", winner)
        b_cell = _colorize(b_text[:col_w].rjust(col_w), "B", winner)
        return f"{label.ljust(label_w)}{a_cell}{b_cell}   {delta}"

    def diff(x, y, unit):
        if x is None or y is None:
            return ""
        return f"Δ {abs(x - y):.0f}{unit}"

    header = f"{''.ljust(label_w)}{loc_a.name[:col_w].rjust(col_w)}{loc_b.name[:col_w].rjust(col_w)}"
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


def http_request_json(url: str, headers: dict, data: Optional[dict] = None,
                      method: str = "GET", timeout: float = 15.0, retries: int = 3,
                      backoff: float = 2.0, urlopen=urllib.request.urlopen,
                      sleep=_time.sleep):
    if retries < 1:
        raise ValueError("retries must be >= 1")
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
