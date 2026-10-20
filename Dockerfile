FROM python:3.10
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# البورت ($PORT) والـ workers/threads فـ gunicorn.conf.py
CMD ["gunicorn", "app:app"]
