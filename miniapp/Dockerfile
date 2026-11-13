# Mini App image: the built frontend plus the API. Build context is the repo root:
#   docker build -f miniapp/Dockerfile -t flashcard-miniapp .
# Base images are pinned by digest (Dependabot bumps them). Tags: node:22-slim, python:3.12-slim
FROM node:22-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS web
WORKDIR /web
COPY miniapp/package.json miniapp/package-lock.json ./
RUN npm ci
COPY miniapp/index.html miniapp/vite.config.ts miniapp/tsconfig.json ./
COPY miniapp/public public/
COPY miniapp/src src/
RUN npm run build

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
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
