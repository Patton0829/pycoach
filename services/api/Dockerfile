FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/api/pyproject.toml .
COPY services/api/app ./app
COPY services/api/alembic.ini .
COPY services/api/alembic ./alembic
COPY curriculum ./curriculum
RUN pip install --no-cache-dir --no-deps --no-build-isolation .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
