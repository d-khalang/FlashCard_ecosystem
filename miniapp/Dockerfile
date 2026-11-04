# Mini App image: the built frontend plus the API. Build context is the repo root:
#   docker build -f miniapp/Dockerfile -t flashcard-miniapp .
FROM node:22-slim AS web
WORKDIR /web
COPY miniapp/package.json miniapp/package-lock.json ./
RUN npm ci
COPY miniapp/index.html miniapp/vite.config.ts miniapp/tsconfig.json ./
COPY miniapp/public public/
COPY miniapp/src src/
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 IN_DOCKER=1 MINIAPP_STATIC_DIR=/app/web
COPY flashcard-project/pyproject.toml .
COPY flashcard-project/src/ src/
RUN pip install --no-cache-dir .
COPY --from=web /web/dist web/
USER 10001:10001
CMD ["flashcard-miniapp"]
