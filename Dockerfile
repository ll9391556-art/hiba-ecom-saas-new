FROM python:3.10
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["gunicorn", "--workers", "4", "--worker-class", "gthread", "--threads", "4", "--timeout", "120", "--bind", "0.0.0.0:7860", "app:app"]
