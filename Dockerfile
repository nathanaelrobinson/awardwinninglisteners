# Dockerfile
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv pip install --system --no-cache .
COPY data/cache/ ./data/cache/
COPY --from=web /web/dist ./web/dist
ENV PORT=8080 STORE=sqlite PYTHONUNBUFFERED=1 WINSPOOL_DATA_DIR=/app/data/cache WINSPOOL_WEB_DIST=/app/web/dist
CMD ["sh", "-c", "winspool-serve --host 0.0.0.0 --port ${PORT}"]
