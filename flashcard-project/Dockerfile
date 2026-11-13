# Base images are pinned by digest (Dependabot bumps them). Tag: python:3.12-slim
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

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
