# Mini App image: the built frontend plus the API. Build context is the repo root:
#   docker build -f miniapp/Dockerfile -t flashcard-miniapp .
# Base images are pinned by digest (Dependabot bumps them). Tags: node:22-slim, python:3.12-slim
FROM node:25-slim@sha256:81db02c4b671288a03915da9534dbd54f96d0e7c24d80ccc54f5b36b2e684370 AS web
WORKDIR /web
COPY miniapp/package.json miniapp/package-lock.json ./
RUN npm ci
COPY miniapp/index.html miniapp/vite.config.ts miniapp/tsconfig.json ./
COPY miniapp/public public/
COPY miniapp/src src/
RUN npm run build

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
WORKDIR /app
ENV PYTHONUNBUFFERED=1 IN_DOCKER=1 MINIAPP_STATIC_DIR=/app/web
COPY flashcard-project/requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY flashcard-project/pyproject.toml .
COPY flashcard-project/src/ src/
RUN pip install --no-cache-dir --no-deps .
COPY --from=web /web/dist web/
USER 10001:10001
CMD ["flashcard-miniapp"]
