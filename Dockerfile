FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -U -r requirements.txt
COPY main.py .
# 取り込み状況を覚えておくので、ワーカーは1つ・スレッドで並行処理する
CMD gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:${PORT:-8080} main:app
