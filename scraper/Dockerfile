FROM python:3.11-slim
WORKDIR /app
COPY scraper/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY shared /app/shared
COPY scraper /app/scraper
COPY config /app/config
ENV SCRAPE_TOPICS_FILE=/app/config/scrape_topics.json
RUN useradd --create-home worker
USER worker
CMD ["python", "-m", "scraper.worker"]
