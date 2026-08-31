FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a source change does not invalidate the install layer.
COPY apps/api/pyproject.toml ./pyproject.toml
RUN pip install --upgrade pip && pip install ".[postgres]"

COPY apps/api/app ./app
COPY apps/api/scripts ./scripts

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
