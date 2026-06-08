FROM python:3.12-slim

# tzdata lets zoneinfo resolve America/Chicago, America/New_York, etc.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY weather_compare.py .

# Defaults; override in `docker run -e ...` or the Unraid template.
# RUN_MODE=schedule makes the process loop and post once daily at POST_TIME.
ENV RUN_MODE=schedule \
    POST_TIME=07:00 \
    DATA_DIR=/data \
    AI_ENABLED=true

VOLUME ["/data"]

ENTRYPOINT ["python3", "weather_compare.py"]
