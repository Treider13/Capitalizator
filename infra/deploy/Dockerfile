# One image, five processes (compose picks the command). python:3.12 — the project pins
# pyarrow/duckdb/pydantic wheels for 3.12; the VPS system Python (3.14) is not used.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=UTC
RUN useradd --create-home --uid 10001 trader
WORKDIR /app
COPY pyproject.toml README.md requirements.lock /app/
COPY src /app/src
COPY infra /app/infra
RUN pip install --no-cache-dir -e ".[live]" && pip check
USER trader
# /data is the userdir (vault): knowledge/, tape/, reports/, secrets/. Mounted, never in the image.
VOLUME ["/data"]
CMD ["python", "-m", "capitalizator.desk", "--userdir", "/data"]
