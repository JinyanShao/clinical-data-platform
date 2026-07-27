FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN python -m venv /opt/venv
COPY pyproject.toml requirements.lock README.md ./
COPY app ./app
RUN pip install --no-cache-dir -c requirements.lock .

COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
COPY demo ./demo

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "clinical_data_platform.main:app", "--host", "0.0.0.0", "--port", "8000"]
