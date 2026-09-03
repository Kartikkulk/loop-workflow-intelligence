FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# pyproject declares `packages = ["app"]`, so the source has to be in place
# before the install — a deps-only layer would fail to build the wheel.
COPY apps/api/pyproject.toml ./pyproject.toml
COPY apps/api/app ./app
COPY apps/api/scripts ./scripts

RUN pip install --upgrade pip && pip install ".[postgres]"

EXPOSE 8000

# Shell form on purpose: Cloud Run, Fly and Heroku all inject $PORT and expect
# the process to bind it. The exec form would pass the literal string "${PORT}"
# to uvicorn. Defaulted so `docker run` locally still lands on 8000.
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
