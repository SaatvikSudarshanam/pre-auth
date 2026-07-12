FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System libraries needed by OCR deps (onnxruntime: libgomp; opencv: libGL/glib).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Storage (uploads + sqlite db) is mounted as a volume in docker-compose.
RUN mkdir -p /app/storage/uploads

EXPOSE 8068
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8068"]
