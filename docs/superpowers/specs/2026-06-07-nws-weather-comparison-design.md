# NWS Weather Comparison Tool — Design

**Date:** 2026-06-07
**Status:** Approved design (pending implementation plan)

## Purpose

Post a daily Discord recap comparing **yesterday's observed weather** for two
US locations — default **Des Moines, IA** and **Providence, RI** — with
color-coded, at-a-glance deltas on temperature, humidity, and cloud cover.
Over time, accumulate a running scoreboard so the user can see **which area has
the better weather over the course of a year**, judged against their personal
weather preferences.

## Core decisions (from brainstorming)

| Decision | Choice |
|----------|--------|
| Data reported | **Yesterday's observed** conditions (a next-morning recap), not forecast |
| Data source | NWS API — aggregate raw station observations (`/stations/{id}/observations`) |
| Stats | High/low temp, avg humidity, avg cloud cover ("overcast"), most-common conditions text |
| Units | Imperial (°F). No metric toggle (YAGNI) |
| AI report | Toggleable. Claude API when enabled + key present; deterministic templated fallback otherwise |
| Delivery | Discord **webhook** (write-only, no bot), **rich embed** with an ANSI-colored comparison table |
| Color coding | Per-stat green/red for the favored city; embed side-bar = overall daily winner |
| Tracking | Append daily results to a **local CSV**; show year-to-date scoreboard in the post |
| Runtime | **Plain Python** run one-shot by the Unraid **User Scripts** plugin on a cron schedule |
| Dependencies | **Python standard library only** (no `pip install`) for robustness on RAM-based Unraid |

## Architecture & data flow

A single self-contained script, `weather_compare.py`, stdlib-only, run once per
day by Unraid User Scripts. One pass, then exit:

1. **Load config** from environment variables (defaults for the two cities).
2. **Compute "yesterday" per city** — each city's own local-day window
   `[00:00, 24:00)` in its timezone, converted to UTC for the API query (DSM's
   yesterday is Central, PVD's is Eastern). Uses stdlib `zoneinfo`. An optional
   `RECAP_DATE=YYYY-MM-DD` overrides "yesterday" for backfill/testing.
3. **Fetch observations** per station:
   `GET https://api.weather.gov/stations/{id}/observations?start=…&end=…`,
   sending the NWS-required `User-Agent` header. Light retry/backoff on
   transient 5xx/network errors.
4. **Summarize** each city from its ~hourly observations (see below).
5. **Compute deltas** (city A − city B) and **per-stat favorability**.
6. **Build summary text** — Claude API if enabled, else templated fallback.
7. **Update the CSV** (upsert by date) and **compute the YTD scoreboard**.
8. **Build the Discord embed** and **POST to the webhook**.
9. **Exit non-zero on hard failure** so a failed run shows red in User Scripts.

Network calls (NWS fetch, Discord post, Claude call) sit behind thin functions
that accept an injectable transport, so all logic is pure and unit-testable
with canned fixtures and no live network.

## Stats & computation

Computed per city from yesterday's observations; null values are skipped
gracefully (a stat with no valid samples reports "n/a"):

| Stat | Computation | Output |
|------|-------------|--------|
| High / Low temp | max / min of `temperature` | °F (NWS returns °C → convert) |
| Avg humidity | mean of `relativeHumidity` | % |
| Cloud cover ("overcast") | each obs's **max** cloud-layer code mapped to a fraction, then averaged over the day | % + word label |
| Conditions | most frequent `textDescription` | text (e.g. "Light Rain") |

**Cloud-layer → percent mapping** (max layer per observation):
`SKC`/`CLR` = 0%, `FEW` ≈ 19%, `SCT` ≈ 44%, `BKN` ≈ 75%, `OVC` = 100%.

Note: a high computed from hourly observations may differ by ~1°F from the
official daily climate high — acceptable for a comparison tool.

## Favorability & color coding

Each day, each of the three core stats "favors" one city (green) or the other
(red); an exact tie awards no point:

| Stat | Favored (green) |
|------|-----------------|
| Temp | closer to the day's **seasonal comfort target** |
| Humidity | **lower** (always preferred, per user) |
| Cloud cover | **lower** (sunnier) |

**Seasonal comfort target** — a smooth curve over the year:

```
target(day_of_year) = MID − AMP · cos( 2π · (day_of_year − TROUGH_DOY) / 365 )
  where MID = (TARGET_MIN + TARGET_MAX) / 2
        AMP = (TARGET_MAX − TARGET_MIN) / 2
```

Defaults: `TARGET_MIN=30` (≈ late January), `TARGET_MAX=75` (≈ late July),
`TROUGH_DOY=20`. Sample values: ~45°F early April, ~69°F on June 7, ~60°F early
October. The temperature compared to the target is the day's **high** by default;
`TEMP_BASIS=average` instead uses the mean of the day's high and low.

**Overall daily winner:** whoever wins **≥2 of the 3** color-coded stats. With
three stats the majority is decisive unless a stat ties; a 1–1 result with one
tie counts as a draw (no winner that day).

## Discord output

One rich embed posted via webhook:

- **Title:** `🌤️ Weather Comparison — <recap date>`
- **Side-bar color:** green when city B (Providence) is the overall winner,
  orange when city A (Des Moines), gray on a tie.
- **Body:** an ```ansi code block rendering a compact, column-aligned table.
  Discord renders real ANSI colors inside ```ansi fences, so favored cells are
  printed in green and unfavored in red — true at-a-glance color.
- **Summary line:** the AI or templated 2–3 sentence comparison.
- **Scoreboard line:** year-to-date, e.g.
  `YTD: Providence 112 – 98 (Temp 95-103 · Humidity 130-68 · Cloud 88-90)`.

Illustrative layout (🟢/🔴 here stand in for ANSI green/red on the values):

```
🌤️  Weather Comparison — Fri, Jun 6 2026

                 Des Moines    Providence      Δ
 High temp         78°F 🔴       71°F 🟢      7°F   (PVD closer to 69° target)
 Low temp          60°F          55°F         5°F
 Humidity          55%  🟢       68%  🔴     13%   (DSM drier)
 Cloud cover       40%  🟢       75%  🔴     35%   (DSM clearer)
 Conditions      Partly Cloudy  Overcast

 Summary: <AI or templated comparison>
 YTD: Providence 112 – 98  (Temp 95-103 · Humidity 130-68 · Cloud 88-90)
```

## AI comparison report (toggleable)

- **Runs when** `AI_ENABLED=true` **and** `ANTHROPIC_API_KEY` is set; otherwise
  silently uses the templated fallback (works out-of-the-box with no key).
- **Model:** `claude-haiku-4-5` by default (fast/cheap for a short blurb),
  overridable via `AI_MODEL`.
- **Call:** plain `urllib` POST to `https://api.anthropic.com/v1/messages`
  (no SDK), ~15s timeout, `max_tokens` ≈ 200. The prompt feeds both cities'
  stats, the deltas, the seasonal target, and which stat favored whom, asking
  for a tight 2–3 sentence comparison. Prompt caching is intentionally skipped
  (one call/day provides no cache benefit). The Claude API request format /
  model ID will be verified against the `claude-api` skill at build time.
- **Fallback:** any failure (no key, HTTP error, timeout, malformed response)
  logs a warning and uses a deterministic templated sentence, e.g.
  *"Yesterday Des Moines was 7°F warmer (closer to the ~69°F seasonal target),
  13% less humid, and clearer than Providence."*

## Persistence & scoreboard

- **File:** `$DATA_DIR/history.csv` (default `./data/history.csv`; on Unraid set
  `DATA_DIR=/mnt/user/appdata/weather-compare/`).
- **One row per recap date:** date, each city's high/low/humidity/cloud/
  conditions, the day's seasonal target, per-stat winners, and overall winner.
- **Upsert by date:** running twice for the same date replaces that row rather
  than appending a duplicate, so the tally never double-counts and missed days
  can be backfilled via `RECAP_DATE`.
- **Scoreboard:** computed fresh from the CSV each run (single source of truth).
  The post shows year-to-date overall day-wins plus per-stat win counts.

## Configuration (environment variables)

| Var | Default | Notes |
|-----|---------|-------|
| `DISCORD_WEBHOOK_URL` | — | **Required** |
| `LOC_A_NAME` / `LOC_A_STATION` / `LOC_A_TZ` | Des Moines / `KDSM` / `America/Chicago` | City A |
| `LOC_B_NAME` / `LOC_B_STATION` / `LOC_B_TZ` | Providence / `KPVD` / `America/New_York` | City B |
| `NWS_USER_AGENT` | `weather-compare (claude@ccaves.net)` | NWS requires a contact UA |
| `TEMP_BASIS` | `high` | `high` or `average` |
| `TARGET_MIN` / `TARGET_MAX` | `30` / `75` | Seasonal curve endpoints (°F) |
| `TROUGH_DOY` | `20` | Day-of-year of coldest target |
| `AI_ENABLED` | `true` | AI used only if also given a key |
| `ANTHROPIC_API_KEY` | — | Enables the AI report |
| `AI_MODEL` | `claude-haiku-4-5` | |
| `DATA_DIR` | `./data` | CSV location |
| `RECAP_DATE` | — | Optional `YYYY-MM-DD` override for backfill/testing |

## File layout

```
weather-compare/
  weather_compare.py        # single deployable script: functions + main()
  test_weather_compare.py   # unit tests (stdlib unittest, zero network)
  README.md                 # Unraid User Scripts setup + env reference
  .env.example              # sample config
  data/                     # CSV history (created at runtime, gitignored)
  docs/superpowers/specs/   # this design doc
```

## Testing

Built test-first with stdlib `unittest`. No live network in the suite.

**Pure logic:** cloud-code→% mapping; `summarize()` with null handling;
seasonal `target()` at known dates (Jan 20→30, Jul 22→75, Jun 7→~69);
favorability decisions incl. ties; delta + direction text; templated fallback;
CSV upsert + YTD tally counts; ANSI-table and embed builders; DST-aware
local-day→UTC windowing.

**Network functions:** `fetch_observations`, `post_to_discord`, and the Claude
call are tested by injecting fake transports (canned NWS JSON, forced errors) to
verify request shape and, critically, the **AI→templated fallback** path.

## Prerequisites & deployment notes

- Requires `python3` available on the Unraid host (e.g. via the **NerdTools**
  plugin). No pip packages needed.
- Deploy by copying `weather_compare.py` to a persistent path (e.g. on the
  array), creating a **User Scripts** entry that exports the env vars and runs
  `python3 /path/weather_compare.py`, and scheduling it daily (after the local
  morning so yesterday's observations are complete).
- `README.md` will document the full setup and a sample User Script.

## Out of scope (v1)

Wind and precipitation stats; metric units; per-city climate normals; graphing
UI; Discord bot/interactivity; more than two locations.
