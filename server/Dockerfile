FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends chromium chromium-driver && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8001
ENV ENVIRONMENT=production

EXPOSE 8001

CMD ["python", "main.py"]
