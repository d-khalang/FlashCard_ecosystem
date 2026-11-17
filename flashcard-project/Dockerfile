# Base images are pinned by digest (Dependabot bumps them). Tag: python:3.12-slim
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV IN_DOCKER=1

COPY requirements.txt .
# Dependencies come from the hashed lock file (see docs/cicd.md), so a rebuild gets the same packages.
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --no-deps .

CMD ["flashcard-bot"]
