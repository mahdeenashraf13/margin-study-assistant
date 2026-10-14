FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DB_PATH=/data/study.db
CMD ["sh", "-c", "mkdir -p /data && gunicorn -b 0.0.0.0:${PORT:-8000} app:app"]
