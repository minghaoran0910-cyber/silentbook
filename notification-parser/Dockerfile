FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/app

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:6000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "6000", "--workers", "2", "--timeout-keep-alive", "30"]
