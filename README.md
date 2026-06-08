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

## Docker / Unraid Community Applications (self-scheduling)

The container runs continuously and posts once per day at `POST_TIME` (interpreted
in City A's timezone) — no User Script or host Python needed.

```bash
docker run -d --name nws-weather-delta --restart unless-stopped \
  -e DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
  -e POST_TIME="07:00" \
  -e ANTHROPIC_API_KEY="" \
  -v /mnt/user/appdata/weather-compare:/data \
  ghcr.io/eatinsundip/nws-weather-delta:latest
```

`RUN_MODE=once` (instead of the default `schedule`) makes it run a single comparison
and exit — handy for a manual test:

```bash
docker run --rm -e RUN_MODE=once -e RECAP_DATE=2026-06-06 \
  -e DISCORD_WEBHOOK_URL="..." -v /mnt/user/appdata/weather-compare:/data \
  ghcr.io/eatinsundip/nws-weather-delta:latest
```

On Unraid, the template at `unraid/nws-weather-delta.xml` exposes all of this as UI
fields (Docker tab → Add Container → template).

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
