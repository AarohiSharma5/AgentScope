FROM python:3.12-slim

# Avoid .pyc files and buffer flushing; keep logs immediate.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5001

# Production WSGI server. run.py exposes `app = create_app()`.
CMD ["gunicorn", "-b", "0.0.0.0:5001", "-w", "2", "--timeout", "60", "run:app"]
