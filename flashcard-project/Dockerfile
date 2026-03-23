FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV IN_DOCKER=1

COPY pyproject.toml .
COPY src/ src/

RUN pip install .

CMD ["flashcard-bot"]
