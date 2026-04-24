FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY repo/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY repo/ .

ENV HOST=0.0.0.0
ENV PORT=8080

EXPOSE 8080

CMD ["bash", "start.sh"]
