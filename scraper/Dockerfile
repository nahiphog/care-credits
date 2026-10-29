FROM python:3.11-slim
WORKDIR /app
COPY scraper/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY shared /app/shared
COPY scraper /app/scraper
RUN useradd --create-home worker
USER worker
CMD ["python", "-m", "scraper.worker"]
