FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY registry ./registry
COPY service ./service
COPY client ./client

# Default to running the registry
EXPOSE 5001
CMD ["uvicorn", "registry.app:app", "--host", "0.0.0.0", "--port", "5001"]

