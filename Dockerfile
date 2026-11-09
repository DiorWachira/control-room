# Control Room engine + web UI in one image (M3 runs this on the VM; see infra/docker-compose.yml).
#   docker build -t controlroom .
#   docker run -p 8000:8000 controlroom                      # replay mode
#   docker run -p 8000:8000 -e PROMETHEUS_URL=... controlroom  # live mode

FROM node:22.11-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

FROM python:3.12.7-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY slos.yaml ./
COPY engine/pyproject.toml engine/
COPY engine/controlroom engine/controlroom
RUN pip install --no-cache-dir ./engine && useradd --system --uid 10001 controlroom
COPY --from=web /app/web/dist web/dist
ENV CONTROLROOM_SLOS=/app/slos.yaml CONTROLROOM_WEB_DIST=/app/web/dist
USER controlroom
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "controlroom.api:app", "--host", "0.0.0.0", "--port", "8000"]
