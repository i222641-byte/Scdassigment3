FROM python:3.12-slim

# OCR system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system rahbar && adduser --system --ingroup rahbar rahbar

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline/ ./pipeline/

USER rahbar

CMD ["python", "-m", "pipeline.run"]
